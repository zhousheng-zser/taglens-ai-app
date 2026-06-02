"""主后端调用独立 LLM 网关服务（HTTP 客户端）。"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from services.http_timeouts import llm_gateway_client_timeout
from services.llm_gateway_service import LLMGatewayError
from services.sync_hard_timeout import HardTimeoutError, call_with_hard_timeout

LLM_GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://127.0.0.1:8020").rstrip("/")
LLM_GATEWAY_TIMEOUT_SEC = float(os.getenv("LLM_GATEWAY_TIMEOUT_SEC", "180"))
# 略大于 httpx 整请求超时，防止客户端 read drip 导致永不返回
LLM_GATEWAY_HARD_TIMEOUT_SEC = float(
    os.getenv("LLM_GATEWAY_HARD_TIMEOUT_SEC", str(LLM_GATEWAY_TIMEOUT_SEC + 20))
)


def _post_json_once(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{LLM_GATEWAY_URL}{path}"
    try:
        with httpx.Client(trust_env=False, timeout=llm_gateway_client_timeout()) as client:
            response = client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise LLMGatewayError(f"LLM 网关连接超时: {url}", status_code=504) from exc
    except httpx.HTTPError as exc:
        raise LLMGatewayError(f"LLM 网关连接失败: {exc}", status_code=502) from exc

    if response.status_code >= 400:
        detail = response.text
        try:
            body = response.json()
            detail = body.get("detail") or body.get("error") or detail
        except Exception:
            pass
        raise LLMGatewayError(
            f"LLM 网关返回 HTTP {response.status_code}: {detail}",
            status_code=response.status_code,
        )
    try:
        return response.json()
    except Exception as exc:
        raise LLMGatewayError(f"LLM 网关响应非 JSON: {exc}") from exc


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return call_with_hard_timeout(
            LLM_GATEWAY_HARD_TIMEOUT_SEC,
            _post_json_once,
            path,
            payload,
        )
    except HardTimeoutError as exc:
        raise LLMGatewayError(f"LLM 网关硬超时: {exc}", status_code=504) from exc


def infer_traffic_image(
    provider: str,
    image_data_uri: str,
    prompt: Optional[str] = None,
    *,
    allow_mock: bool = True,
    camera_name: Optional[str] = None,
    camera_structure: Optional[str] = None,
) -> tuple[dict[str, Any], bool]:
    """
    通过 HTTP 调用独立 LLM 网关。
    camera_* 仅在主后端侧用于拼 prompt 时使用；若已传 prompt 则直接转发。
    """
    if not (prompt or "").strip() and (camera_name or camera_structure):
        from services.llm_prompts import build_default_analysis_prompt

        prompt = build_default_analysis_prompt(camera_name, camera_structure)

    body = _post_json(
        "/llm/infer",
        {
            "provider": provider,
            "image": image_data_uri,
            "prompt": prompt,
        },
    )
    if not body.get("success"):
        raise LLMGatewayError(body.get("error") or "LLM 网关推理失败")
    data = body.get("data")
    if not isinstance(data, dict):
        raise LLMGatewayError("LLM 网关响应缺少 data 字段")
    return data, bool(body.get("mock", False))


def list_providers() -> list[str]:
    with httpx.Client(trust_env=False, timeout=10.0) as client:
        response = client.get(f"{LLM_GATEWAY_URL}/llm/providers")
    response.raise_for_status()
    body = response.json()
    return list(body.get("providers") or [])


def check_gateway_health() -> bool:
    try:
        with httpx.Client(trust_env=False, timeout=5.0) as client:
            response = client.get(f"{LLM_GATEWAY_URL}/health")
        return response.status_code == 200
    except Exception:
        return False
