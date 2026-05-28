#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TagLens 统一 LLM 网关（独立进程）。

启动:
  ./start_llm_gateway.sh
  健康检查: GET http://127.0.0.1:8020/health
  推理: POST http://127.0.0.1:8020/llm/infer
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from routers.llm_inference_api import router as llm_router
from services.llm_gateway_service import test_qwen_connection


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LLM Gateway] 服务启动中...")
    test_qwen_connection()
    print("[LLM Gateway] 可接收请求")
    yield
    print("[LLM Gateway] 服务关闭")


app = FastAPI(
    title="TagLens LLM Gateway",
    description="千问 / Gemini / Codex / MiMo 统一视觉推理服务",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(llm_router)


@app.get("/health")
async def health() -> dict:
    return {
        "success": True,
        "service": "llm-gateway",
        "port_hint": int(os.environ.get("LLM_GATEWAY_PORT", "8020")),
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("LLM_GATEWAY_PORT", "8020"))
    uvicorn.run("llm_gateway_server:app", host="0.0.0.0", port=port, reload=False)
