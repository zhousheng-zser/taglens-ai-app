from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from core.sync_executor import run_blocking
from core.manage_database import (
    SESSION_ADMIN_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    authenticate_user,
    create_session_token,
    create_tag_task_batch,
    create_time_range,
    create_user,
    delete_tag_task_batch,
    delete_time_range,
    delete_user,
    get_pending_workload_daily,
    get_review_stats,
    get_review_stats_timeseries,
    get_user_by_id,
    list_user_tag_task_batches,
    list_user_time_ranges,
    list_users,
    verify_session_token,
)
from core.tag_task_assignment import get_tag_pending_workload_count


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "reviewer"
    displayName: Optional[str] = None


class CreateTimeRangeRequest(BaseModel):
    rangeName: str
    startTime: str
    endTime: str
    workloadStatus: int = 0
    workloadQa: int = 0
    workloadAiDescription: int = 0
    workloadReviewDescription: int = 0
    workloadEnglishDescription: int = 0
    workloadAccidentQa: int = 0


class CreateTagTaskBatchRequest(BaseModel):
    rangeName: str
    workloadImages: int = 0


def _cookie_kwargs() -> Dict[str, Any]:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": False,
        "path": "/",
        "max_age": SESSION_MAX_AGE_SECONDS,
    }


def _with_time_ranges(user: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(user)
    result["timeRanges"] = list_user_time_ranges(int(user["id"]))
    result["tagTaskBatches"] = list_user_tag_task_batches(int(user["id"]))
    return result


async def get_current_user(
    taglens_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Dict[str, Any]:
    if not taglens_session:
        raise HTTPException(status_code=401, detail="请先登录")
    user = await run_blocking(verify_session_token, taglens_session)
    if not user:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return user


async def require_admin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问")
    return current_user


@router.post("/login")
async def login(request: LoginRequest, response: Response) -> Dict[str, Any]:
    user = await run_blocking(authenticate_user, request.username.strip(), request.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = await run_blocking(create_session_token, int(user["id"]))
    response.set_cookie(SESSION_COOKIE_NAME, token, **_cookie_kwargs())
    response.delete_cookie(SESSION_ADMIN_COOKIE_NAME, path="/")
    time_ranges = await run_blocking(list_user_time_ranges, int(user["id"]))
    tag_batches = await run_blocking(list_user_tag_task_batches, int(user["id"]))
    result = dict(user)
    result["timeRanges"] = time_ranges
    result["tagTaskBatches"] = tag_batches
    return {"success": True, "user": result}


@router.post("/logout")
async def logout(response: Response) -> Dict[str, Any]:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(SESSION_ADMIN_COOKIE_NAME, path="/")
    return {"success": True}


@router.get("/me")
async def me(
    current_user: Dict[str, Any] = Depends(get_current_user),
    taglens_admin_session: Optional[str] = Cookie(default=None, alias=SESSION_ADMIN_COOKIE_NAME),
) -> Dict[str, Any]:
    time_ranges = await run_blocking(list_user_time_ranges, int(current_user["id"]))
    tag_batches = await run_blocking(list_user_tag_task_batches, int(current_user["id"]))
    user = dict(current_user)
    user["timeRanges"] = time_ranges
    user["tagTaskBatches"] = tag_batches
    user["impersonating"] = bool(taglens_admin_session)
    if taglens_admin_session:
        admin_user = await run_blocking(verify_session_token, taglens_admin_session)
        if admin_user and admin_user.get("role") == "admin":
            user["impersonatedByAdmin"] = admin_user.get("displayName") or admin_user.get("username")
    return {"success": True, "user": user}


@router.get("/users")
async def users(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return {"success": True, "users": await run_blocking(list_users, include_password=True)}


@router.post("/users")
async def add_user(
    request: CreateUserRequest,
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    username = request.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if not request.password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    try:
        user = create_user(username, request.password, request.role, request.displayName)
        return {"success": True, "user": user}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/users/{user_id}")
async def remove_user(user_id: int, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    try:
        deleted = delete_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"删除用户失败: {exc}")
    if not deleted:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True}


@router.post("/impersonate/{user_id}")
async def impersonate_user(
    user_id: int,
    response: Response,
    current_user: Dict[str, Any] = Depends(require_admin),
    taglens_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    taglens_admin_session: Optional[str] = Cookie(default=None, alias=SESSION_ADMIN_COOKIE_NAME),
) -> Dict[str, Any]:
    target = await run_blocking(get_user_by_id, user_id)
    if not target or target.get("role") != "reviewer" or not target.get("isActive"):
        raise HTTPException(status_code=400, detail="只能代登录审核员账号")
    if int(current_user["id"]) == user_id and taglens_admin_session:
        raise HTTPException(status_code=400, detail="当前已是该审核员身份")
    if not taglens_admin_session and taglens_session:
        response.set_cookie(SESSION_ADMIN_COOKIE_NAME, taglens_session, **_cookie_kwargs())
    token = await run_blocking(create_session_token, user_id)
    response.set_cookie(SESSION_COOKIE_NAME, token, **_cookie_kwargs())
    return {"success": True, "user": await run_blocking(_with_time_ranges, target)}


@router.post("/stop-impersonate")
async def stop_impersonate(
    response: Response,
    taglens_admin_session: Optional[str] = Cookie(default=None, alias=SESSION_ADMIN_COOKIE_NAME),
) -> Dict[str, Any]:
    if not taglens_admin_session:
        raise HTTPException(status_code=400, detail="当前不是代登录状态")
    admin_user = await run_blocking(verify_session_token, taglens_admin_session)
    if not admin_user or admin_user.get("role") != "admin":
        raise HTTPException(status_code=400, detail="管理员会话已失效，请重新登录")
    response.set_cookie(SESSION_COOKIE_NAME, taglens_admin_session, **_cookie_kwargs())
    response.delete_cookie(SESSION_ADMIN_COOKIE_NAME, path="/")
    return {"success": True, "user": await run_blocking(_with_time_ranges, admin_user)}


@router.get("/users/{user_id}/time-ranges")
async def get_time_ranges(user_id: int, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return {"success": True, "timeRanges": list_user_time_ranges(user_id)}


@router.post("/users/{user_id}/time-ranges")
async def add_time_range(
    user_id: int,
    request: CreateTimeRangeRequest,
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    if not request.rangeName.strip():
        raise HTTPException(status_code=400, detail="时间段名称不能为空")
    if not request.startTime or not request.endTime:
        raise HTTPException(status_code=400, detail="开始时间和结束时间不能为空")
    try:
        time_range = create_time_range(
            user_id=user_id,
            range_name=request.rangeName.strip(),
            start_time=request.startTime,
            end_time=request.endTime,
            workload_status=request.workloadStatus,
            workload_qa=request.workloadQa,
            workload_ai_description=request.workloadAiDescription,
            workload_review_description=request.workloadReviewDescription,
            workload_english_description=request.workloadEnglishDescription,
            workload_accident_qa=request.workloadAccidentQa,
        )
        return {"success": True, "timeRange": time_range}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/time-ranges/{range_id}")
async def remove_time_range(range_id: int, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    deleted = delete_time_range(range_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="时间段不存在")
    return {"success": True}


@router.get("/tag-pending-workload")
async def tag_pending_workload(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    count = await run_blocking(get_tag_pending_workload_count)
    return {"success": True, "pendingImages": count}


@router.get("/users/{user_id}/tag-task-batches")
async def get_tag_task_batches(user_id: int, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return {"success": True, "tagTaskBatches": list_user_tag_task_batches(user_id)}


@router.post("/users/{user_id}/tag-task-batches")
async def add_tag_task_batch(
    user_id: int,
    request: CreateTagTaskBatchRequest,
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    if not request.rangeName.strip():
        raise HTTPException(status_code=400, detail="任务名称不能为空")
    if int(request.workloadImages or 0) <= 0:
        raise HTTPException(status_code=400, detail="分配图片数必须大于 0")
    try:
        batch = create_tag_task_batch(
            user_id=user_id,
            range_name=request.rangeName.strip(),
            workload_images=int(request.workloadImages),
        )
        return {"success": True, "tagTaskBatch": batch}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/tag-task-batches/{batch_id}")
async def remove_tag_task_batch(batch_id: int, _: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    deleted = delete_tag_task_batch(batch_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="标签任务批次不存在")
    return {"success": True}


@router.get("/review-stats")
async def review_stats(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return {"success": True, "stats": get_review_stats()}


@router.get("/pending-workload")
async def pending_workload(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    payload = await run_blocking(get_pending_workload_daily)
    return {"success": True, **payload}


@router.get("/review-stats/timeseries")
async def review_stats_timeseries(
    month: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    date_hour: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    _: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    try:
        payload = get_review_stats_timeseries(
            month=month.strip() if month else None,
            date_key=date.strip() if date else None,
            date_hour=date_hour.strip() if date_hour else None,
            filter_user_id=user_id,
        )
        return {"success": True, **payload}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
