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

SEGMENT_DESC_FILL_MAX_WORKERS = max(
    1,
    int(os.getenv("EVENT_SEGMENT_DESC_FILL_WORKERS", "7")),
)
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


def fill_one_segment_description(
    item: Dict[str, Any],
    log_sink: Optional[list[tuple[str, str]]] = None,
) -> SegmentFillResult:
    event_id = str(item["event_id"])
    project_id = str(item["project_id"])
    event_type = str(item["event_type_corrected"])
    segment_index = int(item["segment_index"])

    def _log(message: str, level: str = "info") -> None:
        if log_sink is not None:
            log_sink.append((message, level))

    segment_video_url = build_public_media_url(item["segment_media_path"])
    overlay_path = item.get("overlay_media_path")
    overlay_image_url = build_public_media_url(overlay_path) if overlay_path else None

    video_bytes = None
    video_ct = ""
    for attempt in range(1, 4):
        try:
            video_bytes, video_ct = fetch_segment_video_bytes(segment_video_url)
            break
        except SegmentAiMediaError as exc:
            err = f"媒体拉取失败: {exc}"
            if _is_network_error_message(err) and attempt < 3:
                _log(f"  -> 网络异常，2秒后重试: {err}", "warning")
                time.sleep(2)
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
        return SegmentFillResult(
            success=False,
            skipped=True,
            error=f"视频损坏，跳过补齐（未调用 RLQ）: {reason}",
            damage_log=damage_log,
            event_id=event_id,
            segment_index=segment_index,
        )

    description = None
    for attempt in range(1, 4):
        try:
            _log(f"  -> 正在调用 RLQ 视觉模型...（第 {attempt}/3 次）", "progress")
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
                if attempt < 3:
                    _log(f"  -> 网络异常，2秒后重试: {err}", "warning")
                    time.sleep(2)
                    continue
                raise SegmentDescFillFatalNetworkError(
                    "连续 3 次网络异常，终止整批事件分段描述补齐任务。"
                ) from exc
            return SegmentFillResult(
                success=False,
                error=err,
                damage_log=damage_log,
                event_id=event_id,
                segment_index=segment_index,
            )
        except Exception as exc:
            err = str(exc)
            if _is_network_error_message(err):
                if attempt < 3:
                    _log(f"  -> 网络异常，2秒后重试: {err}", "warning")
                    time.sleep(2)
                    continue
                raise SegmentDescFillFatalNetworkError(
                    "连续 3 次网络异常，终止整批事件分段描述补齐任务。"
                ) from exc
            return SegmentFillResult(
                success=False,
                error=err,
                damage_log=damage_log,
                event_id=event_id,
                segment_index=segment_index,
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
