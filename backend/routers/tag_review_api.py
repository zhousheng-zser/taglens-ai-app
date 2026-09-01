from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.database import search_images
from core.sync_executor import run_blocking
from core.tag_task_assignment import (
    get_tag_assigned_uuids,
    get_tag_batch_for_user,
)
from routers.auth_api import get_current_user


router = APIRouter(tags=["tag-review"])


class TagSearchRequest(BaseModel):
    assignedBatchId: Optional[int] = None
    query: Optional[str] = None
    queries: Optional[List[str]] = None
    limit: Optional[int] = 100
    page: Optional[int] = 1
    pageSize: Optional[int] = 20
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    cameraName: Optional[str] = None
    bizCategory: Optional[str] = None
    filePath: Optional[str] = None
    descriptionKeywords: Optional[List[str]] = None
    tagExtracted: Optional[bool] = None


async def require_admin_or_tag_assignee(
    image_uuid: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if current_user.get("role") == "admin":
        return current_user
    user_id = int(current_user["id"])
    if await run_blocking(is_tag_image_editable_by_user, user_id, image_uuid):
        return current_user
    raise HTTPException(status_code=403, detail="无权修改该图片")


def _tag_search_sync(request: TagSearchRequest, current_user: Dict[str, Any]) -> Dict[str, Any]:
    page = max(1, int(request.page or 1))
    page_size = max(1, int(request.pageSize or 20))
    uuid_filter: Optional[List[str]] = None

    if current_user.get("role") != "admin":
        batch_id = request.assignedBatchId
        if not batch_id:
            raise HTTPException(status_code=400, detail="请选择标签任务批次")
        user_id = int(current_user["id"])
        batch = get_tag_batch_for_user(user_id, int(batch_id))
        if not batch:
            raise HTTPException(status_code=403, detail="标签任务批次不存在或无权访问")
        uuid_filter = get_tag_assigned_uuids(user_id, int(batch_id))
        if not uuid_filter:
            return {"success": True, "results": [], "total": 0}

    results, total_count = search_images(
        query=(request.query or "").strip(),
        limit=10000,
        start_date=request.startDate,
        end_date=request.endDate,
        camera_name=request.cameraName,
        biz_category=request.bizCategory,
        file_path=request.filePath,
        description_keywords=request.descriptionKeywords,
        tag_extracted=request.tagExtracted,
        uuid_filter=uuid_filter,
        page=page,
        page_size=page_size,
    )

    formatted = []
    for row in results:
        formatted.append(
            {
                "id": row["id"],
                "uuid": row["uuid"],
                "filePath": row["filePath"],
                "fileName": row.get("fileName"),
                "createdAt": row["createdAt"],
                "description": row.get("description") or "",
                "keywords": row.get("keywords") or [],
                "tags": row.get("tags") or [],
                "qwenCaptions": row.get("qwenCaptions") or [],
                "yoloObjects": row.get("yoloObjects") or [],
                "szName": row.get("szName"),
                "szTagRefs": row.get("szTagRefs") or [],
                "similarity": row.get("similarity"),
            }
        )
    return {"success": True, "results": formatted, "total": total_count}


@router.post("/images/tag-search")
async def tag_search_api(
    request: TagSearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return await run_blocking(_tag_search_sync, request, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"标签搜索失败: {exc}") from exc
