"""缺失标签批量补齐（走统一 LLM 网关，不再 fork 外部脚本）。"""
from __future__ import annotations

import json
import sqlite3
import time
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from core.minio_storage_client import MinIOStorageClient
from services.llm_gateway_client import infer_traffic_image
from services.llm_gateway_service import LLMGatewayError
from services.llm_prompts import build_default_analysis_prompt
from services.text_embedding_service import encode_text_to_vector

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "taglens.db"
MAX_WORKERS = 5

LogCallback = Callable[[str, str], None]


def _noop_log(_line: str, _level: str = "info") -> None:
    pass


class ReextractFatalNetworkError(Exception):
    """网络故障重试耗尽后，终止整批任务。"""


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
        "socket",
        "dns",
        "unreachable",
        "temporary failure",
        "connection reset",
    )
    return any(k in msg for k in keywords)


def get_images_missing_keywords(limit: int = 2000) -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                i.id,
                i.uuid,
                i.relative_path,
                i.file_name,
                i.created_at,
                ar.keywords_json
            FROM images i
            LEFT JOIN analysis_results ar ON i.id = ar.image_id
            WHERE ar.keywords_json IS NULL OR TRIM(ar.keywords_json) = '[]'
            ORDER BY i.created_at DESC
            LIMIT ?
        """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


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

    now = datetime.now().isoformat()
    relative_path = None
    image_uuid = None
    file_name = None

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT relative_path, uuid, file_name FROM images WHERE id = ?",
            (image_id,),
        )
        img_row = cursor.fetchone()
        if not img_row:
            raise ValueError(f"图片 ID {image_id} 不存在于数据库中")
        relative_path = img_row["relative_path"]
        image_uuid = img_row["uuid"]
        file_name = img_row["file_name"]

        cursor.execute("SELECT id FROM analysis_results WHERE image_id = ?", (image_id,))
        existing = cursor.fetchone()

        keywords_json_str = json.dumps(keywords, ensure_ascii=False)
        qwen_captions_json_str = json.dumps(qwen_captions, ensure_ascii=False)
        yolo_objects_json_str = json.dumps(yolo_objects, ensure_ascii=False)

        if existing:
            cursor.execute(
                """
                UPDATE analysis_results
                SET description = ?, keywords_json = ?, qwen_captions_json = ?,
                    yolo_objects_json = ?, created_at = ?
                WHERE image_id = ?
            """,
                (
                    description or "",
                    keywords_json_str,
                    qwen_captions_json_str,
                    yolo_objects_json_str,
                    now,
                    image_id,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO analysis_results
                (image_id, description, keywords_json, qwen_captions_json, yolo_objects_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    image_id,
                    description or "",
                    keywords_json_str,
                    qwen_captions_json_str,
                    yolo_objects_json_str,
                    now,
                ),
            )

        cursor.execute("DELETE FROM keyword_embeddings WHERE image_id = ?", (image_id,))
        embedding_inserted = 0
        for k in keywords:
            try:
                embedding_bytes = encode_text_to_vector(k)
                cursor.execute(
                    """
                    INSERT INTO keyword_embeddings (image_id, keyword, embedding, created_at)
                    VALUES (?, ?, ?, ?)
                """,
                    (image_id, k, embedding_bytes, now),
                )
                embedding_inserted += 1
            except Exception as exc:
                log(f"  -> 警告: keyword 向量化失败 keyword='{k}' err={exc}", "warning")

        if embedding_inserted == 0:
            raise ValueError("所有 keyword 向量化都失败，跳过写入")

        cursor.execute("DELETE FROM tags WHERE image_id = ?", (image_id,))
        for k in keywords:
            try:
                cursor.execute(
                    "INSERT INTO tags (image_id, tag, tag_type) VALUES (?, ?, ?)",
                    (image_id, k, "keyword"),
                )
            except sqlite3.IntegrityError:
                pass
        for o in yolo_objects:
            try:
                cursor.execute(
                    "INSERT INTO tags (image_id, tag, tag_type) VALUES (?, ?, ?)",
                    (image_id, o, "yolo_object"),
                )
            except sqlite3.IntegrityError:
                pass

        conn.commit()
        log(
            f"  -> 成功: 已提交 keywords={len(keywords)} embeddings={embedding_inserted}",
            "success",
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if minio_client and relative_path:
        try:
            import base64 as b64mod

            json_path = relative_path + ".json"
            ai_analysis_json = {
                "semantic_search": {"description": description, "keywords": keywords},
                "training_data": {
                    "qwen_captions": qwen_captions,
                    "yolo_objects": yolo_objects,
                },
                "metadata": {
                    "uuid": image_uuid or "",
                    "file_name": file_name,
                    "created_at": now,
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
                    analysis_result, _mock = infer_traffic_image(
                        provider,
                        data_uri,
                        prompt,
                        allow_mock=False,
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
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        if stop_requested():
            log("检测到已请求停止：不再提交新图片，等待当前任务结束。", "warning")

        futures: dict = {}
        next_idx = 0

        def submit_more() -> None:
            nonlocal next_idx
            while next_idx < total and len(futures) < MAX_WORKERS and not stop_requested():
                futures[executor.submit(process_one, next_idx, candidates[next_idx])] = next_idx
                next_idx += 1

        submit_more()

        while futures:
            done, _pending = wait(list(futures.keys()), timeout=0.5, return_when=FIRST_COMPLETED)
            for future in done:
                futures.pop(future, None)
                try:
                    status = future.result()
                    if status == "success":
                        ok += 1
                    elif status == "skipped":
                        skipped += 1
                    else:
                        fail += 1
                except ReextractFatalNetworkError as exc:
                    # 若用户已请求停止，则允许当前已在跑的任务自然结束，不要强行取消其它 future
                    if stop_requested():
                        log(f"  -> 网络异常已触发致命错误（但已请求停止）：{exc}", "warning")
                        fail += 1
                    else:
                        log(f"\n任务中止: {exc}", "error")
                        # 尝试取消尚未完成的任务（正在运行的会自然结束）
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
                        raise
                except Exception as exc:
                    fail += 1
                    log(f"  -> 失败: {exc}", "error")

            if not stop_requested():
                submit_more()

        if stop_requested():
            log("\n收到停止请求：已停止提交新图片，等待进行中的图片处理完成后退出。", "warning")

    log(f"\n补齐完成: 成功 {ok}，失败 {fail}，跳过 {skipped}", "done")
    return ok, fail
