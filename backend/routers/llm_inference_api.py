"""统一 LLM 推理 HTTP 路由（由独立 llm-gateway 进程挂载）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.sync_executor import run_blocking
from schemas.llm_schemas import (
    LLMInferRequest,
    LLMInferResponse,
    LLMProvidersResponse,
    TrafficAnalysisOutput,
)
from services.llm_gateway_service import (
    LLMGatewayError,
    SUPPORTED_PROVIDERS,
    infer_traffic_image,
)

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/providers", response_model=LLMProvidersResponse)
async def list_providers() -> LLMProvidersResponse:
    return LLMProvidersResponse(providers=list(SUPPORTED_PROVIDERS))


@router.post("/infer", response_model=LLMInferResponse)
async def llm_infer(request: LLMInferRequest) -> LLMInferResponse:
    """统一视觉分析：千问 / Gemini / Codex / MiMo。"""
    try:
        result, is_mock = await run_blocking(
            infer_traffic_image,
            request.provider,
            request.image,
            request.prompt,
        )
        validated = TrafficAnalysisOutput(**result)
        return LLMInferResponse(
            success=True,
            provider=request.provider,
            data=validated,
            mock=is_mock,
        )
    except LLMGatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI分析失败: {exc}")
