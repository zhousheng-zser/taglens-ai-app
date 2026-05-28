"""主后端对前端的 LLM 代理：转发到独立 llm-gateway 服务。"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException

from core.sync_executor import run_blocking
from schemas.llm_schemas import LLMInferRequest, LLMInferResponse, LLMProvidersResponse
from services.llm_gateway_client import LLM_GATEWAY_URL, _post_json, check_gateway_health
from services.llm_gateway_service import LLMGatewayError

router = APIRouter(prefix="/llm", tags=["llm-proxy"])


@router.get("/providers", response_model=LLMProvidersResponse)
async def list_providers_proxy() -> LLMProvidersResponse:
    try:
        with httpx.Client(trust_env=False, timeout=10.0) as client:
            response = client.get(f"{LLM_GATEWAY_URL}/llm/providers")
        response.raise_for_status()
        return LLMProvidersResponse(**response.json())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM 网关不可用: {exc}")


@router.post("/infer", response_model=LLMInferResponse)
async def llm_infer_proxy(request: LLMInferRequest) -> LLMInferResponse:
    """代理到独立 LLM 网关（taglens-llm-gateway）。"""
    if not check_gateway_health():
        raise HTTPException(
            status_code=503,
            detail=f"LLM 网关服务不可用，请启动 taglens-llm-gateway（{LLM_GATEWAY_URL}）",
        )

    def _call() -> dict:
        return _post_json("/llm/infer", request.model_dump())

    try:
        body = await run_blocking(_call)
        return LLMInferResponse(**body)
    except LLMGatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"代理 LLM 网关失败: {exc}")
