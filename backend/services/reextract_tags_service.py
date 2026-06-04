"""缺失标签批量补齐（走统一 LLM 网关，不再 fork 外部脚本）。"""
from __future__ import annotations

import json
import os
import time
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from typing import Callable, Optional

from core.database import get_images_missing_keywords, update_image_analysis_with_embeddings
from core.minio_storage_client import MinIOStorageClient
from services.llm_gateway_client import LLM_GATEWAY_HARD_TIMEOUT_SEC, infer_traffic_image
from services.llm_gateway_service import LLMGatewayError
from services.llm_prompts import build_default_analysis_prompt
from services.sync_hard_timeout import HardTimeoutError, call_with_hard_timeout
from services.text_embedding_service import encode_text_to_vector

MAX_WORKERS = 5
REEXTRACT_INFER_HARD_TIMEOUT_SEC = float(
    os.getenv("REEXTRACT_INFER_HARD_TIMEOUT_SEC", str(LLM_GATEWAY_HARD_TIMEOUT_SEC + 30))
)
REEXTRACT_STALL_ABORT_SEC = float(os.getenv("REEXTRACT_STALL_ABORT_SEC", "600"))

LogCallback = Callable[[str, str], None]


def _noop_log(_line: str, _level: str = "info") -> None:
    pass


class ReextractFatalNetworkError(Exception):
    """网络故障重试耗尽后，终止整批任务。"""


class ReextractStallError(Exception):
    """长时间无任何图片完成（疑似上游/网关挂死），终止整批任务。"""


def _is_network_error(exc: LLMGatewayError) -> bool:
    msg = (exc.message or "").lower()
    if exc.status_code in (502, 503, 504):
        return True
    keywords = (
        "network error",
        "connection",
        "connect",
        "timeout",
        "timed out",
        "超时",
        "硬超时",
        "socket",
        "dns",
        "unreachable",
        "temporary failure",
        "connection reset",
    )
    return any(k in msg for k in keywords)


def _infer_with_hard_timeout(
    provider: str,
    data_uri: str,
    prompt: str,
) -> dict:
    try:
        result, _mock = call_with_hard_timeout(
            REEXTRACT_INFER_HARD_TIMEOUT_SEC,
            infer_traffic_image,
            provider,
            data_uri,
            prompt,
            allow_mock=False,
        )
        return result
    except HardTimeoutError as exc:
        raise LLMGatewayError(f"推理硬超时: {exc}", status_code=504) from exc


def update_database_with_analysis(
    image_id: int,
    analysis_result: dict,
    minio_client: Optional[MinIOStorageClient] = None,
    log: LogCallback = _noop_log,
) -> None:
    semantic = analysis_result.get("semantic_search", {})
    training = analysis_result.get("training_data", {})

    description = semantic.get("description", "")
    keywords = semantic.get("keywords", [])
    qwen_captions = training.get("qwen_captions", {})
    yolo_objects = training.get("yolo_objects", [])

    if not isinstance(keywords, list) or len(keywords) == 0:
        raise ValueError("AI 分析结果 keywords 为空，跳过写入")
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    if not keywords:
        raise ValueError("AI 分析结果 keywords 清洗后为空，跳过写入")

    keyword_embeddings: list[tuple[str, bytes]] = []
    for k in keywords:
        try:
            keyword_embeddings.append((k, encode_text_to_vector(k)))
        except Exception as exc:
            log(f"  -> 警告: keyword 向量化失败 keyword='{k}' err={exc}", "warning")

    if not keyword_embeddings:
        raise ValueError("所有 keyword 向量化都失败，跳过写入")

    meta = update_image_analysis_with_embeddings(
        image_id,
        description or "",
        keywords,
        qwen_captions,
        yolo_objects,
        keyword_embeddings,
    )
    log(
        f"  -> 成功: 已提交 keywords={len(keywords)} embeddings={len(keyword_embeddings)}",
        "success",
    )

    relative_path = meta.get("relative_path")
    if minio_client and relative_path:
        try:
            json_path = relative_path + ".json"
            ai_analysis_json = {
                "semantic_search": {"description": description, "keywords": keywords},
                "training_data": {
                    "qwen_captions": qwen_captions,
                    "yolo_objects": yolo_objects,
                },
                "metadata": {
                    "uuid": meta.get("uuid") or "",
                    "file_name": meta.get("file_name"),
                    "created_at": meta.get("created_at") or datetime.now().isoformat(),
                    "image_path": relative_path,
                },
            }
            json_bytes = json.dumps(ai_analysis_json, ensure_ascii=False, indent=2).encode(
                "utf-8"
            )
            minio_client.upload_file_data(json_bytes, json_path, "application/json")
            log(f"  -> JSON 已上传 MinIO: {json_path}", "success")
        except Exception as exc:
            log(f"  -> 警告: JSON 上传 MinIO 失败: {exc}", "warning")


def run_reextract_batch(
    limit: int,
    provider: str,
    log: LogCallback = _noop_log,
    stop_event: Optional[threading.Event] = None,
) -> tuple[int, int]:
    """批量补齐缺失标签。返回 (成功数, 失败数)。"""
    prompt = build_default_analysis_prompt()
    log(f"任务启动: 补齐缺失标签 (最新 {limit} 张, 模型: {provider})", "start")

    try:
        minio_client = MinIOStorageClient(skip_bucket_check=True)
        log("MinIO 客户端连接成功", "info")
    except Exception as exc:
        log(f"MinIO 客户端初始化失败: {exc}", "error")
        return 0, 0

    candidates = get_images_missing_keywords(limit=limit)
    total = len(candidates)
    if total == 0:
        log("没有找到 keywords_json 为空的记录，任务无需执行", "warning")
        return 0, 0

    log(f"待补齐记录数: {total}", "info")

    def stop_requested() -> bool:
        return bool(stop_event and stop_event.is_set())

    def process_one(index: int, img: dict) -> str:
        image_id = img["id"]
        rel_path = img.get("relative_path") or ""
        uuid_val = img.get("uuid") or ""
        log(f"\n[{index + 1}/{total}] 处理图片: id={image_id} uuid={uuid_val} path={rel_path}", "info")

        if stop_requested():
            log("  -> 已请求停止：跳过该图片（不会再处理新任务）", "warning")
            return "skipped"

        if not rel_path:
            log("  -> 失败: relative_path 为空", "error")
            return "failed"
        try:
            log("  -> 正在从 MinIO 下载图片...", "progress")
            img_bytes = minio_client.download_file_data(rel_path)
            mime_type = "image/jpeg"
            lower = rel_path.lower()
            if lower.endswith(".png"):
                mime_type = "image/png"
            elif lower.endswith(".webp"):
                mime_type = "image/webp"
            import base64

            data_uri = (
                f"data:{mime_type};base64,"
                f"{base64.b64encode(img_bytes).decode('utf-8')}"
            )
            analysis_result = None
            for attempt in range(1, 4):
                try:
                    log(
                        f"  -> 正在调用统一 LLM 网关 ({provider})...（第 {attempt}/3 次）",
                        "progress",
                    )
                    analysis_result = _infer_with_hard_timeout(
                        provider,
                        data_uri,
                        prompt,
                    )
                    break
                except LLMGatewayError as exc:
                    if _is_network_error(exc):
                        if attempt < 3:
                            log(
                                f"  -> 网络异常，2秒后重试: {exc.message}",
                                "warning",
                            )
                            time.sleep(2)
                            continue
                        raise ReextractFatalNetworkError(
                            "连续 3 次网络异常，终止整批缺失标签补齐任务。"
                        ) from exc
                    raise

            if analysis_result is None:
                raise ReextractFatalNetworkError("模型调用未返回结果，终止任务。")

            log("  -> 正在更新数据库...", "progress")
            update_database_with_analysis(
                image_id, analysis_result, minio_client, log=log
            )
            return "success"
        except LLMGatewayError as exc:
            log(f"  -> 失败: {exc.message}", "error")
            return "failed"
        except Exception as exc:
            log(f"  -> 失败: {exc}", "error")
            return "failed"

    ok = 0
    fail = 0
    skipped = 0
    last_progress_at = time.monotonic()

    def touch_progress() -> None:
        nonlocal last_progress_at
        last_progress_at = time.monotonic()

    touch_progress()

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            if stop_requested():
                log("检测到已请求停止：不再提交新图片，等待当前任务结束。", "warning")

            futures: dict = {}
            next_idx = 0

            def submit_more() -> None:
                nonlocal next_idx
                while next_idx < total and len(futures) < MAX_WORKERS and not stop_requested():
                    futures[executor.submit(process_one, next_idx, candidates[next_idx])] = (
                        next_idx
                    )
                    next_idx += 1

            submit_more()

            while futures:
                done, _pending = wait(
                    list(futures.keys()),
                    timeout=5.0,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    stalled_for = time.monotonic() - last_progress_at
                    if stalled_for >= REEXTRACT_STALL_ABORT_SEC:
                        pending_count = sum(1 for f in futures if not f.done())
                        log(
                            f"\n任务中止: 已连续 {stalled_for:.0f}s 无任何图片完成 "
                            f"（阈值 {REEXTRACT_STALL_ABORT_SEC:.0f}s），"
                            f"仍有 {pending_count} 个并发任务可能卡在 MiMo/网关。"
                            "请重启 LLM 网关后重新运行本任务。",
                            "error",
                        )
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
                        raise ReextractStallError(
                            f"无进展超过 {REEXTRACT_STALL_ABORT_SEC:.0f}s"
                        )
                    continue

                for future in done:
                    futures.pop(future, None)
                    try:
                        status = future.result()
                        touch_progress()
                        if status == "success":
                            ok += 1
                        elif status == "skipped":
                            skipped += 1
                        else:
                            fail += 1
                    except ReextractFatalNetworkError as exc:
                        if stop_requested():
                            log(
                                f"  -> 网络异常已触发致命错误（但已请求停止）：{exc}",
                                "warning",
                            )
                            fail += 1
                        else:
                            log(f"\n任务中止: {exc}", "error")
                            for pending in futures:
                                if not pending.done():
                                    pending.cancel()
                            raise
                    except ReextractStallError:
                        raise
                    except Exception as exc:
                        touch_progress()
                        fail += 1
                        log(f"  -> 失败: {exc}", "error")

                if not stop_requested():
                    submit_more()

            if stop_requested():
                log(
                    "\n收到停止请求：已停止提交新图片，等待进行中的图片处理完成后退出。",
                    "warning",
                )

    except ReextractStallError:
        log(f"\n补齐中止（无进展超时）: 已成功 {ok}，失败 {fail}，跳过 {skipped}", "done")
        raise

    log(f"\n补齐完成: 成功 {ok}，失败 {fail}，跳过 {skipped}", "done")
    return ok, fail
