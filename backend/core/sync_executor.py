"""
在 async 路由中执行同步阻塞代码，避免占用 FastAPI/uvicorn 事件循环。
重 CPU/IO（数据库、MinIO、Faiss、BGE、子进程）应通过 run_blocking 调用。

使用独立线程池，避免与 asyncio 默认池（及大批量后台任务的 to_thread）争抢，
导致登录等轻量接口长时间排队。
"""
from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Callable, TypeVar

T = TypeVar("T")

_SYNC_POOL_WORKERS = max(8, int(os.getenv("SYNC_EXECUTOR_WORKERS", "64")))
_SYNC_EXECUTOR = ThreadPoolExecutor(
    max_workers=_SYNC_POOL_WORKERS,
    thread_name_prefix="sync-blocking",
)


async def run_blocking(func: Callable[..., T], /, *args, **kwargs) -> T:
    """在专用线程池中运行同步函数，不阻塞事件循环。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_SYNC_EXECUTOR, partial(func, *args, **kwargs))
