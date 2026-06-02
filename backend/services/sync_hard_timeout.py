"""对可能挂死的同步阻塞调用施加 wall-clock 硬超时（不依赖 httpx read 间隔）。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, TypeVar

T = TypeVar("T")


class HardTimeoutError(TimeoutError):
    """阻塞调用超过硬超时上限。"""


def call_with_hard_timeout(
    timeout_sec: float,
    func: Callable[..., T],
    /,
    *args,
    **kwargs,
) -> T:
    """
    在独立线程中执行 func，主线程最多等待 timeout_sec 秒。
    超时后抛出 HardTimeoutError（底层线程可能仍在运行，需靠连接超时或进程重启回收）。
    """
    if timeout_sec <= 0:
        raise ValueError("timeout_sec must be positive")

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="hard-timeout") as pool:
        future = pool.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_sec)
        except FuturesTimeoutError as exc:
            name = getattr(func, "__name__", repr(func))
            raise HardTimeoutError(
                f"{name} 超过硬超时 {timeout_sec:.0f}s"
            ) from exc
