"""批量为事件分段生成 AI 描述并写回 event.db（专用 7 线程池，与单段 API 分离）。"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from core.event_database import (
    get_event_segment_annotation_snapshot,
    update_event_segment_description_at_index,
)
from services.event_segment_ai_description_service import (
    SegmentAiMediaError,
    SegmentAiModelError,
    build_public_media_url,
    fetch_segment_video_bytes,
    format_model_error,
    generate_segment_description_sync,
    inspect_video_damage,
)
from services.segment_damaged_video_registry import is_known_damaged, record_damaged

SEGMENT_DESC_FILL_MAX_WORKERS = max(
    1,
    int(os.getenv("EVENT_SEGMENT_DESC_FILL_WORKERS", "7")),
)
# 本地 QRL 冷启动慢：网络类失败间隔重试，默认 2 分钟 × 5 次（运行时读 .env，见 get_batch_max_workers）
def _max_retries() -> int:
    return max(1, int(os.getenv("EVENT_SEGMENT_DESC_FILL_MAX_RETRIES", "5")))


def _retry_wait_sec() -> int:
    return max(1, int(os.getenv("EVENT_SEGMENT_DESC_FILL_RETRY_WAIT_SEC", "120")))
_BATCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=SEGMENT_DESC_FILL_MAX_WORKERS,
    thread_name_prefix="segment-desc-fill",
)

_event_write_locks: Dict[Tuple[str, str, str], threading.Lock] = {}
_locks_guard = threading.Lock()


def get_batch_executor() -> ThreadPoolExecutor:
    return _BATCH_EXECUTOR


def get_batch_max_workers() -> int:
    """运行时读取 .env（main.py 在 import 本模块之后才 load_dotenv）。"""
    return max(1, int(os.getenv("EVENT_SEGMENT_DESC_FILL_WORKERS", "4")))


def _event_lock_key(item: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(item["event_id"]),
        str(item["project_id"]),
        str(item["event_type_corrected"]),
    )


def _lock_for_event(key: Tuple[str, str, str]) -> threading.Lock:
    with _locks_guard:
        if key not in _event_write_locks:
            _event_write_locks[key] = threading.Lock()
        return _event_write_locks[key]


class SegmentDescFillFatalNetworkError(Exception):
    """网络故障重试耗尽后，终止整批分段描述补齐。"""


def _retry_wait_label() -> str:
    sec = _retry_wait_sec()
    if sec >= 60 and sec % 60 == 0:
        return f"{sec // 60} 分钟后"
    return f"{sec} 秒后"


def _is_network_error_message(message: str) -> bool:
    msg = (message or "").lower()
    if any(code in msg for code in ("502", "503", "504")):
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
        "连接超时",
        "连接失败",
    )
    return any(k in msg for k in keywords)


@dataclass
class SegmentFillResult:
    success: bool
    skipped: bool = False
    description: str = ""
    error: str = ""
    damage_log: str = ""
    event_id: str = ""
    segment_index: int = 0
    recorded_damaged: bool = False


def _should_record_damaged(error: str) -> bool:
    """补齐永久失败（非网络、非 QRL 服务不可用）时写入损坏列表。"""
    if _is_network_error_message(error):
        return False
    msg = (error or "").lower()
    if "404" in msg and ("qrl" in msg or "api" in msg or "not found" in msg):
        return False
    if "qrl 视觉 api 不可用" in msg or "qrl 视觉 api 返回 404" in msg:
        return False
    if "未能下载视频" in error or "媒体拉取" in error:
        return False
    return bool((error or "").strip())


def _record_fill_failure(segment_media_path: str, reason: str) -> bool:
    if not segment_media_path or not _should_record_damaged(reason):
        return False
    text = (reason or "").replace("\t", " ").replace("\n", " ").strip()
    if len(text) > 500:
        text = text[:500] + "…"
    return record_damaged(segment_media_path, f"补齐失败: {text}")


def fill_one_segment_description(
    item: Dict[str, Any],
    log_sink: Optional[list[tuple[str, str]]] = None,
) -> SegmentFillResult:
    event_id = str(item["event_id"])
    project_id = str(item["project_id"])
    event_type = str(item["event_type_corrected"])
    segment_index = int(item["segment_index"])
    segment_media_path = str(item.get("segment_media_path") or "").strip()

    def _log(message: str, level: str = "info") -> None:
        if log_sink is not None:
            log_sink.append((message, level))

    if segment_media_path and is_known_damaged(segment_media_path):
        return SegmentFillResult(
            success=False,
            skipped=True,
            error="视频损坏（历史记录，跳过检测与补齐）",
            damage_log="损坏程度=已记录（跳过 ffmpeg 检测）",
            event_id=event_id,
            segment_index=segment_index,
        )

    segment_video_url = build_public_media_url(item["segment_media_path"])
    overlay_path = item.get("overlay_media_path")
    overlay_image_url = build_public_media_url(overlay_path) if overlay_path else None

    video_bytes = None
    video_ct = ""
    max_retries = _max_retries()
    retry_wait = _retry_wait_sec()
    for attempt in range(1, max_retries + 1):
        try:
            video_bytes, video_ct = fetch_segment_video_bytes(segment_video_url)
            break
        except SegmentAiMediaError as exc:
            err = str(exc)
            if (_is_network_error_message(err) or "媒体拉取" in err) and attempt < max_retries:
                _log(
                    f"  -> 网络异常，{_retry_wait_label()}重试: {err}",
                    "warning",
                )
                time.sleep(retry_wait)
                continue
            return SegmentFillResult(
                success=False,
                error=err,
                damage_log="损坏程度=未知（未能下载视频）",
                event_id=event_id,
                segment_index=segment_index,
            )

    damage_report = inspect_video_damage(video_bytes)
    damage_log = damage_report.log_line()
    if damage_report.should_skip:
        reason = damage_report.skip_reason or "视频损坏"
        recorded = False
        if segment_media_path:
            recorded = record_damaged(segment_media_path, reason)
        return SegmentFillResult(
            success=False,
            skipped=True,
            error=f"视频损坏，跳过补齐（未调用 QRL）: {reason}",
            damage_log=damage_log,
            event_id=event_id,
            segment_index=segment_index,
            recorded_damaged=recorded,
        )

    description = None
    for attempt in range(1, max_retries + 1):
        try:
            _log(
                f"  -> 正在调用 QRL 视觉模型...（第 {attempt}/{max_retries} 次）",
                "progress",
            )
            description = generate_segment_description_sync(
                segment_video_url,
                overlay_image_url,
                video_bytes=video_bytes,
                video_content_type=video_ct,
            )
            break
        except SegmentAiMediaError as exc:
            message = str(exc)
            is_damaged = "视频损坏" in message or "跳过补齐" in message
            if is_damaged and segment_media_path:
                record_damaged(segment_media_path, message)
            return SegmentFillResult(
                success=False,
                skipped=is_damaged,
                error=message,
                damage_log=damage_log,
                event_id=event_id,
                segment_index=segment_index,
            )
        except SegmentAiModelError as exc:
            err = format_model_error(exc)
            if _is_network_error_message(err):
                if attempt < max_retries:
                    _log(
                        f"  -> 网络异常，{_retry_wait_label()}重试: {err}",
                        "warning",
                    )
                    time.sleep(retry_wait)
                    continue
                raise SegmentDescFillFatalNetworkError(
                    f"连续 {max_retries} 次网络异常，"
                    "终止整批事件分段描述补齐任务。"
                ) from exc
            recorded = _record_fill_failure(segment_media_path, err)
            return SegmentFillResult(
                success=False,
                error=err,
                damage_log=damage_log,
                event_id=event_id,
                segment_index=segment_index,
                recorded_damaged=recorded,
            )
        except Exception as exc:
            err = str(exc)
            if _is_network_error_message(err):
                if attempt < max_retries:
                    _log(
                        f"  -> 网络异常，{_retry_wait_label()}重试: {err}",
                        "warning",
                    )
                    time.sleep(retry_wait)
                    continue
                raise SegmentDescFillFatalNetworkError(
                    f"连续 {max_retries} 次网络异常，"
                    "终止整批事件分段描述补齐任务。"
                ) from exc
            recorded = _record_fill_failure(segment_media_path, err)
            return SegmentFillResult(
                success=False,
                error=err,
                damage_log=damage_log,
                event_id=event_id,
                segment_index=segment_index,
                recorded_damaged=recorded,
            )

    if description is None:
        raise SegmentDescFillFatalNetworkError("模型调用未返回结果，终止任务。")

    lock_key = _event_lock_key(item)
    with _lock_for_event(lock_key):
        snapshot = get_event_segment_annotation_snapshot(event_id, project_id, event_type)
        if snapshot and (snapshot["segment_descriptions"][segment_index] or "").strip():
            return SegmentFillResult(
                success=True,
                description=snapshot["segment_descriptions"][segment_index],
                damage_log=damage_log,
                event_id=event_id,
                segment_index=segment_index,
            )
        update_event_segment_description_at_index(
            event_id=event_id,
            project_id=project_id,
            event_type_corrected=event_type,
            segment_index=segment_index,
            description=description,
        )

    return SegmentFillResult(
        success=True,
        description=description,
        damage_log=damage_log,
        event_id=event_id,
        segment_index=segment_index,
    )
