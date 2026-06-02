"""httpx 超时配置：同时限制整请求时长与 connect/read，避免上游慢速 drip 导致永不超时。"""
from __future__ import annotations

import os

import httpx


def build_httpx_timeout(
    total_sec: float,
    *,
    connect_sec: float | None = None,
    read_sec: float | None = None,
    write_sec: float | None = 60.0,
    pool_sec: float | None = 15.0,
) -> httpx.Timeout:
    """
    total_sec: 整次 HTTP 交换的最大 wall-clock（httpx.Timeout 第一个参数）。
    read_sec: 默认与 total 相同，避免仅按「字节间隔」计时。
    """
    total = max(1.0, float(total_sec))
    connect = max(1.0, float(connect_sec if connect_sec is not None else min(15.0, total)))
    read = max(1.0, float(read_sec if read_sec is not None else total))
    write = max(1.0, float(write_sec if write_sec is not None else min(60.0, total)))
    pool = max(1.0, float(pool_sec if pool_sec is not None else min(15.0, total)))
    return httpx.Timeout(timeout=total, connect=connect, read=read, write=write, pool=pool)


def llm_gateway_client_timeout() -> httpx.Timeout:
    total = float(os.getenv("LLM_GATEWAY_TIMEOUT_SEC", "180"))
    return build_httpx_timeout(total)


def mimo_upstream_timeout() -> httpx.Timeout:
    total = float(os.getenv("MIMO_HTTP_TIMEOUT_SEC", "120"))
    return build_httpx_timeout(total)
