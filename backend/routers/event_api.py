from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.event_database import (
    delete_event_record,
    get_event_record_media_paths,
    get_event_dict_cache,
    search_events,
    update_event_segment_annotations,
)
from core.minio_storage_client import get_storage_client


router = APIRouter(prefix="/events", tags=["events"])
EVENT_MINIO_BUCKET = os.getenv("MINIO_BUCKET", "bucket-taglens")


class EventSearchRequest(BaseModel):
    projectIds: List[str] = []
    eventTypeCodes: List[str] = []
    sourceName: Optional[str] = None
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    page: int = 1
    pageSize: int = 20


class EventSearchResult(BaseModel):
    eventId: str
    uuid: str
    projectId: str
    projectName: str
    eventTypeCode: str
    eventTypeName: str
    sourceName: str
    startTime: str
    videoPath: Optional[str] = None
    videoUrl: Optional[str] = None
    segmentCount: int = 0
    segmentPaths: List[str] = []
    segmentUrls: List[str] = []
    segmentDescriptions: List[str] = []
    segmentStatuses: List[str] = []
    imageBigUrl: Optional[str] = None
    fileName: Optional[str] = None


class EventSearchResponse(BaseModel):
    success: bool
    results: List[EventSearchResult]
    total: int


class EventOptionItem(BaseModel):
    code: str
    name: str


class EventMetaResponse(BaseModel):
    success: bool
    projectOptions: List[EventOptionItem]
    eventTypeOptions: List[EventOptionItem]


class EventSegmentAnnotationUpdateRequest(BaseModel):
    eventId: str
    projectId: str
    eventTypeCode: str
    segmentDescriptions: List[str]
    segmentStatuses: List[str]


class EventDeleteRequest(BaseModel):
    eventId: str
    projectId: str
    eventTypeCode: str


def _normalize_to_object_name(raw_path: str) -> str:
    value = (raw_path or "").strip()
    if not value:
        return ""
    if f"/{EVENT_MINIO_BUCKET}/" in value:
        value = value.split(f"/{EVENT_MINIO_BUCKET}/", 1)[1]
    elif value.startswith(f"{EVENT_MINIO_BUCKET}/"):
        value = value[len(EVENT_MINIO_BUCKET) + 1 :]
    return value.lstrip("/")


def _extract_folder_prefixes(image_paths: str, video_path: str) -> List[str]:
    prefixes: set[str] = set()
    candidates = [item.strip() for item in (image_paths or "").split(",") if item.strip()]
    if video_path and str(video_path).strip():
        candidates.append(str(video_path).strip())

    for path in candidates:
        object_name = _normalize_to_object_name(path)
        if "/" not in object_name:
            continue
        folder = object_name.rsplit("/", 1)[0].strip("/")
        if not folder:
            continue
        if not folder.startswith("event_data/"):
            continue
        prefixes.add(f"{folder}/")
    return sorted(prefixes)


@router.get("/meta", response_model=EventMetaResponse)
async def get_event_meta() -> Dict[str, Any]:
    cache = get_event_dict_cache()
    return {
        "success": True,
        "projectOptions": cache["projectOptions"],
        "eventTypeOptions": cache["eventTypeOptions"],
    }


@router.post("/search", response_model=EventSearchResponse)
async def search_events_api(request: EventSearchRequest) -> Dict[str, Any]:
    if request.page < 1:
        raise HTTPException(status_code=400, detail="page 必须大于等于 1")
    if request.pageSize < 1:
        raise HTTPException(status_code=400, detail="pageSize 必须大于等于 1")

    try:
        results, total = search_events(
            project_ids=request.projectIds,
            event_type_codes=request.eventTypeCodes,
            source_name=request.sourceName,
            start_date=request.startDate,
            end_date=request.endDate,
            page=request.page,
            page_size=request.pageSize,
        )
        return {"success": True, "results": results, "total": total}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"事件搜索失败: {exc}")


@router.post("/segment-annotations")
async def update_event_segment_annotations_api(request: EventSegmentAnnotationUpdateRequest) -> Dict[str, Any]:
    if len(request.segmentDescriptions) != len(request.segmentStatuses):
        raise HTTPException(status_code=400, detail="segmentDescriptions 与 segmentStatuses 长度不一致")
    valid_status = {"正样本", "负样本", "待定"}
    if any(item not in valid_status for item in request.segmentStatuses):
        raise HTTPException(status_code=400, detail="segmentStatuses 含非法值")
    try:
        update_event_segment_annotations(
            event_id=request.eventId,
            project_id=request.projectId,
            event_type_corrected=request.eventTypeCode,
            segment_descriptions=request.segmentDescriptions,
            segment_statuses=request.segmentStatuses,
        )
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"分段标注保存失败: {exc}")


@router.post("/delete")
async def delete_event_api(request: EventDeleteRequest) -> Dict[str, Any]:
    try:
        record = get_event_record_media_paths(
            event_id=request.eventId,
            project_id=request.projectId,
            event_type_corrected=request.eventTypeCode,
        )
        folder_prefixes = _extract_folder_prefixes(
            image_paths=record.get("image_paths", ""),
            video_path=record.get("video_path", ""),
        )

        deleted_objects = 0
        client = get_storage_client(skip_bucket_check=True)
        for prefix in folder_prefixes:
            for obj in client.client.list_objects(EVENT_MINIO_BUCKET, prefix=prefix, recursive=True):
                client.client.remove_object(EVENT_MINIO_BUCKET, obj.object_name)
                deleted_objects += 1

        delete_event_record(
            event_id=request.eventId,
            project_id=request.projectId,
            event_type_corrected=request.eventTypeCode,
        )

        return {
            "success": True,
            "bucket": EVENT_MINIO_BUCKET,
            "deletedPrefixes": folder_prefixes,
            "deletedObjects": deleted_objects,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"删除事件失败: {exc}")
