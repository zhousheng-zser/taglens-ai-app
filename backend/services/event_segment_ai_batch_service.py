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
    build_public_media_url,
    generate_segment_description_sync,
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
    description: str = ""
    error: str = ""
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
        description = generate_segment_description_sync(segment_video_url, overlay_image_url)
    except Exception as exc:
        return SegmentFillResult(
            success=False,
            error=str(exc),
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
        event_id=event_id,
        segment_index=segment_index,
    )
