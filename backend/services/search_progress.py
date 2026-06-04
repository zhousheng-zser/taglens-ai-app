"""标签搜索进度上报（供 NDJSON 流式接口使用）。"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

SearchProgressCallback = Callable[[Dict[str, Any]], None]


class SearchCancelledError(Exception):
    """用户或客户端中断搜索。"""


class SearchCancellation:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise SearchCancelledError("搜索已被用户取消")


class SearchProgress:
    def __init__(
        self,
        callback: Optional[SearchProgressCallback] = None,
        cancellation: Optional[SearchCancellation] = None,
    ) -> None:
        self._callback = callback
        self.cancellation = cancellation or SearchCancellation()

    def check_cancelled(self) -> None:
        self.cancellation.check()

    def report(self, stage: str, percent: float, message: str) -> None:
        self.check_cancelled()
        if not self._callback:
            return
        self._callback(
            {
                "type": "progress",
                "stage": stage,
                "percent": round(max(0.0, min(100.0, percent)), 1),
                "message": message,
            }
        )
