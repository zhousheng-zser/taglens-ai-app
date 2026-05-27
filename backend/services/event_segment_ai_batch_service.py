"""批量为事件分段生成 AI 描述并写回 event.db（专用 7 线程池，与单段 API 分离）。"""
from __future__ import annotations

import os
import threading
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
    return SEGMENT_DESC_FILL_MAX_WORKERS


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


@dataclass
class SegmentFillResult:
    success: bool
    skipped: bool = False
    description: str = ""
    error: str = ""
    damage_log: str = ""
    event_id: str = ""
    segment_index: int = 0


def fill_one_segment_description(item: Dict[str, Any]) -> SegmentFillResult:
    event_id = str(item["event_id"])
    project_id = str(item["project_id"])
    event_type = str(item["event_type_corrected"])
    segment_index = int(item["segment_index"])

    segment_video_url = build_public_media_url(item["segment_media_path"])
    overlay_path = item.get("overlay_media_path")
    overlay_image_url = build_public_media_url(overlay_path) if overlay_path else None

    try:
        video_bytes, video_ct = fetch_segment_video_bytes(segment_video_url)
    except SegmentAiMediaError as exc:
        return SegmentFillResult(
            success=False,
            error=f"媒体拉取失败: {exc}",
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

    try:
        description = generate_segment_description_sync(
            segment_video_url,
            overlay_image_url,
            video_bytes=video_bytes,
            video_content_type=video_ct,
        )
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
        return SegmentFillResult(
            success=False,
            error=format_model_error(exc),
            damage_log=damage_log,
            event_id=event_id,
            segment_index=segment_index,
        )
    except Exception as exc:
        return SegmentFillResult(
            success=False,
            error=str(exc),
            damage_log=damage_log,
            event_id=event_id,
            segment_index=segment_index,
        )

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
