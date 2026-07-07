from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.event_database import (
    delete_event_record,
    get_event_record_media_paths,
    get_event_segment_annotations,
    get_event_dict_cache,
    search_events,
    update_event_segment_annotations,
    _get_special_qa_questions,
)
from core.manage_database import (
    get_event_review_records_for_keys,
    list_user_time_ranges,
    upsert_event_review_record,
)
from core.minio_storage_client import get_storage_client
from core.sync_executor import run_blocking
from routers.auth_api import get_current_user, require_admin
from services.event_segment_ai_description_service import (
    SegmentAiMediaError,
    SegmentAiModelError,
    generate_segment_description_sync,
    get_executor,
)


router = APIRouter(prefix="/events", tags=["events"])
EVENT_MINIO_BUCKET = os.getenv("MINIO_BUCKET", "bucket-taglens")


class EventSearchRequest(BaseModel):
    projectIds: List[str] = []
    eventTypeCodes: List[str] = []
    sourceName: Optional[str] = None
    processingStatus: str = "all"
    questionAnswerStatus: str = "all"
    descriptionStatus: str = "all"
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    page: int = 1
    pageSize: int = 20
    assignedTaskCategory: Optional[str] = None


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
    segmentReviewDescriptions: List[str] = []
    segmentDescriptionsEn: List[str] = []
    segmentStatuses: List[str] = []
    questionsAnswersList: List[List[Dict[str, str]]] = []
    accidentQuestionsAnswersList: List[List[Dict[str, str]]] = []
    eventTypeQuestions: List[str] = []
    imageBigUrl: Optional[str] = None
    imageCompositeUrl: Optional[str] = None
    imageOverlayUrl: Optional[str] = None
    fileName: Optional[str] = None
    reviewerId: Optional[int] = None
    reviewerUsername: Optional[str] = None
    reviewerDisplayName: Optional[str] = None
    reviewTime: Optional[str] = None
    statusReviewDone: bool = False
    qaReviewDone: bool = False
    descriptionReviewDone: bool = False
    aiDescriptionDone: bool = False
    reviewDescriptionDone: bool = False
    englishDescriptionDone: bool = False
    accidentQaReviewDone: bool = False
    assignedTaskCategories: Optional[List[str]] = None


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
    segmentReviewDescriptions: List[str]
    segmentDescriptionsEn: List[str]
    segmentStatuses: List[str]
    questionsAnswersList: List[List[Dict[str, str]]] = []
    accidentQuestionsAnswersList: List[List[Dict[str, str]]] = []


class EventDeleteRequest(BaseModel):
    eventId: str
    projectId: str
    eventTypeCode: str


class SegmentAiDescriptionRequest(BaseModel):
    segmentVideoUrl: str = Field(..., min_length=1)
    overlayImageUrl: Optional[str] = None
    segmentIndex: int = 0


class SegmentAiDescriptionResponse(BaseModel):
    success: bool
    description: str


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


def _parse_event_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _format_range_start(value: str) -> str:
    raw = value.strip().replace("T", " ")
    if len(raw) <= 10:
        return f"{raw} 00:00:00.000000"
    return raw


def _format_range_end(value: str) -> str:
    raw = value.strip().replace("T", " ")
    if len(raw) <= 10:
        return f"{raw} 23:59:59.999999"
    return raw


def _range_contains(request_start: str, request_end: str, assigned_start: str, assigned_end: str) -> bool:
    req_start = _parse_event_time(request_start)
    req_end = _parse_event_time(request_end)
    ass_start = _parse_event_time(assigned_start)
    ass_end = _parse_event_time(assigned_end)
    if not req_start or not req_end or not ass_start or not ass_end:
        return False
    return req_start >= ass_start and req_end <= ass_end


def _apply_reviewer_time_scope(
    request: EventSearchRequest,
    current_user: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    if current_user.get("role") == "admin":
        return request.startDate, request.endDate, None

    ranges = list_user_time_ranges(int(current_user["id"]))
    if not ranges:
        raise HTTPException(status_code=403, detail="当前审核员尚未分配事件任务时间段")

    if not request.startDate or not request.endDate:
        first_range = ranges[0]
        return _format_range_start(first_range["startTime"]), _format_range_end(first_range["endTime"]), first_range

    for item in ranges:
        if _range_contains(request.startDate, request.endDate, item["startTime"], item["endTime"]):
            return request.startDate, request.endDate, item

    raise HTTPException(status_code=403, detail="查询时间范围不在当前审核员的任务分配内")


def _is_status_review_done(segment_statuses: List[str], segment_count: int) -> bool:
    if segment_count <= 0 or len(segment_statuses) < segment_count:
        return False
    return all(status in {"正样本", "负样本"} for status in segment_statuses[:segment_count])


def _is_segment_text_list_done(items: List[str], segment_count: int) -> bool:
    if segment_count <= 0 or len(items) < segment_count:
        return False
    return all(bool((item or "").strip()) for item in items[:segment_count])


def _is_ai_description_done(segment_descriptions: List[str], segment_count: int) -> bool:
    return _is_segment_text_list_done(segment_descriptions, segment_count)


def _is_review_description_done(segment_review_descriptions: List[str], segment_count: int) -> bool:
    return _is_segment_text_list_done(segment_review_descriptions, segment_count)


def _is_english_description_done(segment_descriptions_en: List[str], segment_count: int) -> bool:
    return _is_segment_text_list_done(segment_descriptions_en, segment_count)


def _is_description_review_done(segment_descriptions: List[str], segment_count: int) -> bool:
    return _is_ai_description_done(segment_descriptions, segment_count)


def _is_qa_review_done(questions_answers_list: List[List[Dict[str, str]]], segment_count: int) -> bool:
    if segment_count <= 0 or len(questions_answers_list) < segment_count:
        return False
    for segment_items in questions_answers_list[:segment_count]:
        if not segment_items:
            return False
        for qa in segment_items:
            if not str(qa.get("question", "")).strip() or not str(qa.get("answer", "")).strip():
                return False
    return True


def _is_accident_qa_done(
    event_type_code: str,
    segment_statuses: List[str],
    accident_questions_answers_list: List[List[Dict[str, str]]],
    segment_count: int,
) -> bool:
    questions = _get_special_qa_questions(event_type_code)
    if not questions:
        return True
    positive_indexes = [
        idx
        for idx, status in enumerate(segment_statuses[:segment_count])
        if status == "正样本"
    ]
    if not positive_indexes:
        return True
    if len(accident_questions_answers_list) < segment_count:
        return False
    for idx in positive_indexes:
        segment_items = accident_questions_answers_list[idx] or []
        if len(segment_items) < len(questions):
            return False
        for question, qa in zip(questions, segment_items):
            if str(qa.get("question", "")).strip() != question:
                return False
            if not str(qa.get("answer", "")).strip():
                return False
    return True


def _merge_reviewer_save_fields(
    current_user: Dict[str, Any],
    event_id: str,
    project_id: str,
    event_type_code: str,
    segment_descriptions: List[str],
    segment_review_descriptions: List[str],
    segment_descriptions_en: List[str],
    segment_statuses: List[str],
    questions_answers_list: List[List[Dict[str, str]]],
    accident_questions_answers_list: List[List[Dict[str, str]]],
) -> Tuple[
    List[str],
    List[str],
    List[str],
    List[str],
    List[List[Dict[str, str]]],
    List[List[Dict[str, str]]],
]:
    from core.task_assignment import get_reviewer_editable_categories

    editable = get_reviewer_editable_categories(
        int(current_user["id"]),
        str(current_user.get("role") or ""),
        event_id,
        project_id,
        event_type_code,
    )
    if editable is None:
        return (
            segment_descriptions,
            segment_review_descriptions,
            segment_descriptions_en,
            segment_statuses,
            questions_answers_list,
            accident_questions_answers_list,
        )

    existing = get_event_segment_annotations(event_id, project_id, event_type_code)
    if "ai_description" not in editable:
        segment_descriptions = existing["segment_descriptions"]
    if "review_description" not in editable:
        segment_review_descriptions = existing["segment_review_descriptions"]
    if "english_description" not in editable:
        segment_descriptions_en = existing["segment_descriptions_en"]
    if "status" not in editable:
        segment_statuses = existing["segment_statuses"]
    if "qa" not in editable:
        questions_answers_list = existing["questions_answers_list"]
    if "accident_qa" not in editable:
        accident_questions_answers_list = existing["accident_questions_answers_list"]
    return (
        segment_descriptions,
        segment_review_descriptions,
        segment_descriptions_en,
        segment_statuses,
        questions_answers_list,
        accident_questions_answers_list,
    )


@router.get("/meta", response_model=EventMetaResponse)
async def get_event_meta(_: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    cache = await run_blocking(get_event_dict_cache)
    return {
        "success": True,
        "projectOptions": cache["projectOptions"],
        "eventTypeOptions": cache["eventTypeOptions"],
    }


@router.post("/search", response_model=EventSearchResponse)
async def search_events_api(
    request: EventSearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if request.page < 1:
        raise HTTPException(status_code=400, detail="page 必须大于等于 1")
    if request.pageSize < 1:
        raise HTTPException(status_code=400, detail="pageSize 必须大于等于 1")
    if request.processingStatus not in {"all", "processed", "unprocessed"}:
        raise HTTPException(status_code=400, detail="processingStatus 取值非法")
    if request.questionAnswerStatus not in {"all", "all_answered", "all_unanswered", "partially_answered"}:
        raise HTTPException(status_code=400, detail="questionAnswerStatus 取值非法")
    if request.descriptionStatus not in {"all", "all_edited", "all_unedited", "partially_edited"}:
        raise HTTPException(status_code=400, detail="descriptionStatus 取值非法")
    if request.assignedTaskCategory:
        from core.task_assignment import TASK_CATEGORIES

        if request.assignedTaskCategory not in TASK_CATEGORIES:
            raise HTTPException(status_code=400, detail="assignedTaskCategory 取值非法")

    try:
        scoped_start_date, scoped_end_date, matched_range = _apply_reviewer_time_scope(request, current_user)
        event_keys_filter = None
        if matched_range is not None:
            from core.task_assignment import (
                TASK_CATEGORIES,
                get_user_assigned_keys,
                get_user_assigned_keys_for_category,
                time_range_has_workload,
            )

            if time_range_has_workload(matched_range):
                user_id = int(current_user["id"])
                range_id = int(matched_range["id"])
                category = (request.assignedTaskCategory or "").strip()
                if category and category in TASK_CATEGORIES:
                    event_keys_filter = get_user_assigned_keys_for_category(user_id, range_id, category)
                else:
                    event_keys_filter = get_user_assigned_keys(user_id, range_id)

        def _search() -> tuple[list, int]:
            rows, total = search_events(
                project_ids=request.projectIds,
                event_type_codes=request.eventTypeCodes,
                source_name=request.sourceName,
                processing_status=request.processingStatus,
                question_answer_status=request.questionAnswerStatus,
                description_status=request.descriptionStatus,
                start_date=scoped_start_date,
                end_date=scoped_end_date,
                page=request.page,
                page_size=request.pageSize,
                event_keys_filter=event_keys_filter,
            )
            keys = [
                (item["eventId"], item["projectId"], item["eventTypeCode"])
                for item in rows
            ]
            review_map = get_event_review_records_for_keys(keys)
            for item in rows:
                review = review_map.get((item["eventId"], item["projectId"], item["eventTypeCode"]))
                if review:
                    item.update(review)
            return rows, total

        results, total = await run_blocking(_search)
        if current_user.get("role") != "admin":
            from core.task_assignment import get_assigned_categories_map_for_user

            keys = [
                (item["eventId"], item["projectId"], item["eventTypeCode"])
                for item in results
            ]
            category_map = get_assigned_categories_map_for_user(int(current_user["id"]), keys)
            for item in results:
                key = (item["eventId"], item["projectId"], item["eventTypeCode"])
                categories = category_map.get(key)
                if categories:
                    item["assignedTaskCategories"] = categories
        return {"success": True, "results": results, "total": total}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"事件搜索失败: {exc}")


@router.post("/segment-ai-description", response_model=SegmentAiDescriptionResponse)
async def generate_segment_ai_description_api(
    request: SegmentAiDescriptionRequest,
    _: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    segment_video_url = (request.segmentVideoUrl or "").strip()
    if not segment_video_url:
        raise HTTPException(status_code=400, detail="segmentVideoUrl 不能为空")

    overlay_url = (request.overlayImageUrl or "").strip() or None
    loop = asyncio.get_running_loop()
    executor = get_executor()

    try:
        description = await loop.run_in_executor(
            executor,
            generate_segment_description_sync,
            segment_video_url,
            overlay_url,
        )
    except SegmentAiMediaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SegmentAiModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI 分段描述生成失败: {exc}") from exc

    return {"success": True, "description": description}


@router.post("/segment-annotations")
async def update_event_segment_annotations_api(
    request: EventSegmentAnnotationUpdateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if len(request.segmentDescriptions) != len(request.segmentStatuses):
        raise HTTPException(status_code=400, detail="segmentDescriptions 与 segmentStatuses 长度不一致")
    if len(request.segmentReviewDescriptions) != len(request.segmentDescriptions):
        raise HTTPException(status_code=400, detail="segmentReviewDescriptions 与 segmentDescriptions 长度不一致")
    if len(request.segmentDescriptionsEn) != len(request.segmentDescriptions):
        raise HTTPException(status_code=400, detail="segmentDescriptionsEn 与 segmentDescriptions 长度不一致")
    if len(request.questionsAnswersList) != len(request.segmentDescriptions):
        raise HTTPException(status_code=400, detail="questionsAnswersList 与 segmentDescriptions 长度不一致")
    if len(request.accidentQuestionsAnswersList) != len(request.segmentDescriptions):
        raise HTTPException(status_code=400, detail="accidentQuestionsAnswersList 与 segmentDescriptions 长度不一致")
    valid_status = {"正样本", "负样本", "待定"}
    if any(item not in valid_status for item in request.segmentStatuses):
        raise HTTPException(status_code=400, detail="segmentStatuses 含非法值")
    try:
        (
            segment_descriptions,
            segment_review_descriptions,
            segment_descriptions_en,
            segment_statuses,
            questions_answers_list,
            accident_questions_answers_list,
        ) = _merge_reviewer_save_fields(
            current_user,
            request.eventId,
            request.projectId,
            request.eventTypeCode,
            request.segmentDescriptions,
            request.segmentReviewDescriptions,
            request.segmentDescriptionsEn,
            request.segmentStatuses,
            request.questionsAnswersList,
            request.accidentQuestionsAnswersList,
        )
        update_event_segment_annotations(
            event_id=request.eventId,
            project_id=request.projectId,
            event_type_corrected=request.eventTypeCode,
            segment_descriptions=segment_descriptions,
            segment_review_descriptions=segment_review_descriptions,
            segment_descriptions_en=segment_descriptions_en,
            segment_statuses=segment_statuses,
            questions_answers_list=questions_answers_list,
            accident_questions_answers_list=accident_questions_answers_list,
        )
        segment_count = len(segment_descriptions)
        review = upsert_event_review_record(
            event_id=request.eventId,
            project_id=request.projectId,
            event_type_code=request.eventTypeCode,
            reviewer=current_user,
            status_review_done=_is_status_review_done(segment_statuses, segment_count),
            qa_review_done=_is_qa_review_done(questions_answers_list, segment_count),
            ai_description_done=_is_ai_description_done(segment_descriptions, segment_count),
            review_description_done=_is_review_description_done(
                segment_review_descriptions, segment_count
            ),
            english_description_done=_is_english_description_done(
                segment_descriptions_en, segment_count
            ),
            accident_qa_done=_is_accident_qa_done(
                request.eventTypeCode,
                segment_statuses,
                accident_questions_answers_list,
                segment_count,
            ),
        )
        return {"success": True, "review": review}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"分段标注保存失败: {exc}")


@router.post("/delete")
async def delete_event_api(
    request: EventDeleteRequest,
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
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
