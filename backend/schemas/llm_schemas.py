"""统一 LLM 网关请求/响应模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

LLMProviderName = Literal["qwen", "gemini", "codex", "mimo"]


class SemanticSearch(BaseModel):
    description: str
    keywords: list[str]


class TrainingData(BaseModel):
    qwen_captions: Dict[str, Any] | List[str]
    yolo_objects: list[str]


class TrafficAnalysisOutput(BaseModel):
    semantic_search: SemanticSearch
    training_data: TrainingData


class LLMInferRequest(BaseModel):
    provider: LLMProviderName = Field(..., description="模型提供商: qwen/gemini/codex/mimo")
    image: str = Field(..., description="Base64 data URI")
    prompt: Optional[str] = Field(None, description="自定义提示词；为空时使用默认交通分析 Prompt")


class LLMInferResponse(BaseModel):
    success: bool = True
    provider: LLMProviderName
    data: TrafficAnalysisOutput
    mock: bool = False


class LLMProvidersResponse(BaseModel):
    success: bool = True
    providers: List[str]
