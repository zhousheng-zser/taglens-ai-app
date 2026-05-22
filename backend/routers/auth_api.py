from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from core.sync_executor import run_blocking
from core.manage_database import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    authenticate_user,
    create_session_token,
    create_time_range,
    create_user,
    delete_time_range,
    delete_user,
    get_review_stats,
    get_review_stats_timeseries,
    list_user_time_ranges,
    list_users,
    verify_session_token,
)


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
    time_ranges = await run_blocking(list_user_time_ranges, int(user["id"]))
    result = dict(user)
    result["timeRanges"] = time_ranges
    return {"success": True, "user": result}


@router.post("/logout")
async def logout(response: Response) -> Dict[str, Any]:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"success": True}


@router.get("/me")
async def me(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    time_ranges = await run_blocking(list_user_time_ranges, int(current_user["id"]))
    user = dict(current_user)
    user["timeRanges"] = time_ranges
    return {"success": True, "user": user}


@router.get("/users")
async def users(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return {"success": True, "users": list_users()}


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


@router.get("/review-stats")
async def review_stats(_: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    return {"success": True, "stats": get_review_stats()}


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
