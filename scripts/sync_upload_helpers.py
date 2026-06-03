#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步任务上传阶段：等待后端就绪、连接失败重试（不退出进程）。"""

import time
from typing import Callable, Optional

import requests

BACKEND_BASE = "http://127.0.0.1:8000"
BACKEND_PROBE_URLS = (
    f"{BACKEND_BASE}/health",
    f"{BACKEND_BASE}/projects",
)
BACKEND_WAIT_MAX_SEC = 30 * 60
BACKEND_WAIT_INTERVAL_SEC = 60
CONSECUTIVE_CONNECTION_FAIL_MAX = 10

_consecutive_connection_failures = 0


def _probe_backend(session: requests.Session) -> bool:
    for url in BACKEND_PROBE_URLS:
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code < 500:
                return True
        except requests.RequestException:
            continue
    return False


def wait_for_backend_ready(
    log: Callable[..., None] = print,
    max_wait_sec: int = BACKEND_WAIT_MAX_SEC,
    interval_sec: int = BACKEND_WAIT_INTERVAL_SEC,
) -> bool:
    """轮询后端直至可用或超时。返回是否就绪。"""
    session = requests.Session()
    session.proxies = {"http": None, "https": None}
    deadline = time.time() + max_wait_sec
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        if _probe_backend(session):
            if attempt > 1:
                log(f"✅ 后端已就绪 (第 {attempt} 次探测)")
            return True
        log(
            f"⏳ 等待后端就绪 ({BACKEND_BASE})，"
            f"{interval_sec}s 后重试 (第 {attempt} 次)..."
        )
        time.sleep(interval_sec)
    log(f"⚠️ 等待后端超时 ({max_wait_sec}s)，将继续尝试上传")
    return False


def on_upload_connection_error(
    exc: Exception,
    log: Callable[..., None] = print,
) -> None:
    """连接被拒绝时累计失败次数，达阈值后阻塞等待后端恢复。"""
    global _consecutive_connection_failures
    _consecutive_connection_failures += 1
    log(
        f"    ❌ 无法连接后端 (第 {_consecutive_connection_failures} 次): {exc}"
    )
    if _consecutive_connection_failures >= CONSECUTIVE_CONNECTION_FAIL_MAX:
        log(
            f"    ⏸ 连续 {CONSECUTIVE_CONNECTION_FAIL_MAX} 次连接失败，"
            f"等待后端恢复..."
        )
        wait_for_backend_ready(log=log)
        _consecutive_connection_failures = 0


def reset_upload_connection_streak() -> None:
    global _consecutive_connection_failures
    _consecutive_connection_failures = 0
