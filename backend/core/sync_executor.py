"""
在 async 路由中执行同步阻塞代码，避免占用 FastAPI/uvicorn 事件循环。
重 CPU/IO（数据库、MinIO、Faiss、BGE、子进程）应通过 run_blocking 调用。
"""
from __future__ import annotations

import asyncio
from typing import Callable, TypeVar

T = TypeVar("T")


async def run_blocking(func: Callable[..., T], /, *args, **kwargs) -> T:
    """在线程池中运行同步函数，不阻塞事件循环。"""
    return await asyncio.to_thread(func, *args, **kwargs)
