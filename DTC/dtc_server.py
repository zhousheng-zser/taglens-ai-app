#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DTC 本地分割服务：启动时加载模型，HTTP 接口与 TagLens 前端 /dtc/* 兼容。

启动:
  cd DTC && ./start_dtc_server.sh
  或: DTC_SERVER_PORT=8010 ./start_dtc_server.sh

健康检查: GET http://127.0.0.1:8010/health
"""
from __future__ import annotations

import base64
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from infer_engine import DEFAULT_ADAPTER_SCALE, DEFAULT_CATEGORY, DEFAULT_CHECKPOINT, engine
import server_task_service as task_svc

DTC_ROOT = Path(__file__).resolve().parent


class CreatePathTaskRequest(BaseModel):
    backendPath: str
    prompt: str
    threshold: float = 0.3
    category: str = Field(default=DEFAULT_CATEGORY, pattern="^(concept|simple|complex)$")
    adapter_scale: float = Field(default=DEFAULT_ADAPTER_SCALE, gt=0)


class CreateUploadRunTaskRequest(BaseModel):
    imageSetId: str
    prompt: str
    threshold: float = 0.3
    category: str = Field(default=DEFAULT_CATEGORY, pattern="^(concept|simple|complex)$")
    adapter_scale: float = Field(default=DEFAULT_ADAPTER_SCALE, gt=0)


class SegmentPathSyncRequest(BaseModel):
    """同步推理（适合少量图片；大批量请用 /dtc/tasks/path 异步任务）。"""
    backendPath: str
    prompt: str
    threshold: float = 0.3
    category: str = Field(default=DEFAULT_CATEGORY, pattern="^(concept|simple|complex)$")
    adapter_scale: float = Field(default=DEFAULT_ADAPTER_SCALE, gt=0)
    output: Optional[str] = None


class SegmentImageBase64Item(BaseModel):
    name: str = "image.jpg"
    data: str = Field(..., description="图片 base64，可带 data:image/...;base64, 前缀")


class SegmentImagesJsonRequest(BaseModel):
    """请求体传图：无需 backendPath，响应内联 LabelMe JSON 与可选 comparison 图。"""
    images: List[SegmentImageBase64Item]
    prompt: str
    threshold: float = 0.3
    includeComparison: bool = True
    category: str = Field(default=DEFAULT_CATEGORY, pattern="^(concept|simple|complex)$")
    adapter_scale: float = Field(default=DEFAULT_ADAPTER_SCALE, gt=0)


def _parse_bool_form(value: str, default: bool = True) -> bool:
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _decode_image_base64(data: str) -> bytes:
    raw = (data or "").strip()
    if "," in raw and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=False)
    except Exception as exc:
        raise ValueError(f"base64 解码失败: {exc}") from exc


async def _images_from_uploads(files: List[UploadFile]) -> List[Tuple[str, bytes]]:
    items: List[Tuple[str, bytes]] = []
    for uf in files:
        name = (uf.filename or "image.jpg").strip() or "image.jpg"
        body = await uf.read()
        if not body:
            raise ValueError(f"图片为空: {name}")
        items.append((name, body))
    return items


def _validate_threshold(threshold: float) -> None:
    if not (0 < float(threshold) < 1):
        raise HTTPException(status_code=400, detail="threshold 必须在 (0,1) 之间")


@asynccontextmanager
async def lifespan(app: FastAPI):
    checkpoint = os.environ.get("DTC_CHECKPOINT", str(DEFAULT_CHECKPOINT))
    category = os.environ.get("DTC_CATEGORY", DEFAULT_CATEGORY)
    adapter_scale = float(os.environ.get("DTC_ADAPTER_SCALE", str(DEFAULT_ADAPTER_SCALE)))
    print(
        f"[DTC Server] 正在加载模型 checkpoint={checkpoint} "
        f"category={category} adapter_scale={adapter_scale} ..."
    )
    try:
        engine.load(checkpoint=checkpoint, category=category, adapter_scale=adapter_scale)
        print("[DTC Server] 模型加载完成，可接收请求")
    except Exception as exc:
        print(f"[DTC Server] 模型加载失败: {exc}")
        raise
    yield
    print("[DTC Server] 服务关闭")


app = FastAPI(
    title="DTC Segmentation Server",
    description="本地 DTC 分割服务（模型常驻 GPU）",
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


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "success": engine.loaded,
        "algorithm": "dtc",
        "model_loaded": engine.loaded,
        "load_error": engine.load_error,
        "checkpoint": engine._checkpoint if engine.loaded else None,
        "category_default": DEFAULT_CATEGORY,
        "adapter_scale_default": DEFAULT_ADAPTER_SCALE,
        "port_hint": int(os.environ.get("DTC_SERVER_PORT", "8010")),
    }


# ---------- 与 TagLens 前端兼容的 /dtc 路由 ----------


@app.post("/dtc/image-sets/upload")
async def upload_image_set_chunk(
    files: List[UploadFile] = File(...),
    imageSetId: str = Form(""),
) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一张图片")
    try:
        image_set = task_svc.upload_chunk_to_image_set(files=files, image_set_id=imageSetId.strip() or None)
        return {"success": True, "imageSet": image_set}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dtc/image-sets")
async def list_image_sets() -> Dict[str, Any]:
    return {"success": True, "imageSets": task_svc.list_image_sets()}


@app.delete("/dtc/image-sets/{image_set_id}")
async def delete_image_set(image_set_id: str) -> Dict[str, Any]:
    try:
        result = task_svc.delete_image_set(image_set_id)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/dtc/tasks/upload-run")
async def create_upload_run_task(req: CreateUploadRunTaskRequest) -> Dict[str, Any]:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    if not req.imageSetId.strip():
        raise HTTPException(status_code=400, detail="imageSetId 不能为空")
    if not (0 < float(req.threshold) < 1):
        raise HTTPException(status_code=400, detail="threshold 必须在 (0,1) 之间")
    if not engine.loaded:
        raise HTTPException(status_code=503, detail=engine.load_error or "模型未就绪")
    try:
        task = task_svc.create_upload_task_from_image_set(
            req.imageSetId.strip(),
            req.prompt.strip(),
            float(req.threshold),
            req.category,
            float(req.adapter_scale),
        )
        return {"success": True, "task": task}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/dtc/tasks/path")
async def create_path_task(req: CreatePathTaskRequest) -> Dict[str, Any]:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    if not (0 < float(req.threshold) < 1):
        raise HTTPException(status_code=400, detail="threshold 必须在 (0,1) 之间")
    if not engine.loaded:
        raise HTTPException(status_code=503, detail=engine.load_error or "模型未就绪")
    try:
        task = task_svc.create_path_task(
            req.backendPath.strip(),
            req.prompt.strip(),
            float(req.threshold),
            req.category,
            float(req.adapter_scale),
        )
        return {"success": True, "task": task}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/dtc/segment/images")
async def segment_images_multipart(
    files: List[UploadFile] = File(..., description="一张或多张图片"),
    prompt: str = Form(...),
    threshold: float = Form(0.3),
    includeComparison: str = Form("true"),
    category: str = Form(DEFAULT_CATEGORY),
    adapter_scale: float = Form(DEFAULT_ADAPTER_SCALE),
) -> Dict[str, Any]:
    """
    上传图片直接分割（无需 backendPath）。
    includeComparison=false 时不返回 comparisonImageBase64。
    """
    if not engine.loaded:
        raise HTTPException(status_code=503, detail=engine.load_error or "模型未就绪")
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一张图片")
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    _validate_threshold(threshold)
    try:
        images = await _images_from_uploads(files)
        summary = engine.run_images(
            images=images,
            prompt=prompt.strip(),
            threshold=float(threshold),
            include_comparison=_parse_bool_form(includeComparison, True),
            category=category,
            adapter_scale=float(adapter_scale),
        )
        return {"success": True, **summary}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/dtc/segment/images/json")
async def segment_images_json(req: SegmentImagesJsonRequest) -> Dict[str, Any]:
    """JSON 传图（images[].data 为 base64），响应格式同 /dtc/segment/images。"""
    if not engine.loaded:
        raise HTTPException(status_code=503, detail=engine.load_error or "模型未就绪")
    if not req.images:
        raise HTTPException(status_code=400, detail="images 不能为空")
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    _validate_threshold(req.threshold)
    try:
        images: List[Tuple[str, bytes]] = []
        for item in req.images:
            name = (item.name or "image.jpg").strip() or "image.jpg"
            raw = _decode_image_base64(item.data)
            if not raw:
                raise ValueError(f"图片为空: {name}")
            images.append((name, raw))
        summary = engine.run_images(
            images=images,
            prompt=req.prompt.strip(),
            threshold=float(req.threshold),
            include_comparison=req.includeComparison,
            category=req.category,
            adapter_scale=float(req.adapter_scale),
        )
        return {"success": True, **summary}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/dtc/segment/sync")
async def segment_path_sync(req: SegmentPathSyncRequest) -> Dict[str, Any]:
    """同步分割：请求阻塞至目录处理完成，直接返回 results。"""
    if not engine.loaded:
        return {"success": False, "error": engine.load_error or "模型未就绪"}
    if not req.prompt.strip():
        return {"success": False, "error": "prompt 不能为空"}
    if not (0 < float(req.threshold) < 1):
        return {"success": False, "error": "threshold 必须在 (0,1) 之间"}
    backend = req.backendPath.strip()
    if not backend or not Path(backend).exists():
        return {"success": False, "error": "backendPath 不存在"}

    import uuid
    from datetime import datetime

    task_id = uuid.uuid4().hex[:12]
    date = datetime.now().strftime("%y%m%d")
    output_base = req.output or str(DTC_ROOT / "output" / date / f"sync_{task_id}")

    try:
        summary = engine.run_batch(
            input_dir=backend,
            output_base=output_base,
            prompt=req.prompt.strip(),
            threshold=float(req.threshold),
            category=req.category,
            adapter_scale=float(req.adapter_scale),
        )
        return {"success": True, **summary}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/dtc/tasks")
async def list_tasks() -> Dict[str, Any]:
    return {"success": True, "tasks": task_svc.list_tasks()}


@app.get("/dtc/tasks/{task_id}")
async def get_task(task_id: str) -> Dict[str, Any]:
    task = task_svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "task": task}


@app.get("/dtc/tasks/{task_id}/results")
async def get_task_results(task_id: str) -> Dict[str, Any]:
    task = task_svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    results = task_svc.get_task_results(task_id)
    return {"success": True, "task": task, "results": results}


@app.get("/dtc/tasks/{task_id}/zip")
async def download_task_zip(task_id: str):
    zip_path = task_svc.get_task_zip_path(task_id)
    if not zip_path or not zip_path.exists():
        raise HTTPException(status_code=404, detail="结果 ZIP 不存在")
    return FileResponse(path=str(zip_path), filename=zip_path.name, media_type="application/zip")


@app.get("/dtc/tasks/{task_id}/artifact")
async def download_artifact(task_id: str, file_path: str):
    task = task_svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    fp = Path(file_path)
    if not fp.exists() or not fp.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    allowed_root = Path(task["output_base"]).resolve()
    try:
        resolved = fp.resolve()
        resolved.relative_to(allowed_root)
    except Exception:
        raise HTTPException(status_code=400, detail="非法文件路径")
    return FileResponse(path=str(resolved), filename=resolved.name)


@app.delete("/dtc/tasks/{task_id}")
async def delete_task(task_id: str) -> Dict[str, Any]:
    try:
        result = task_svc.delete_task(task_id)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("DTC_SERVER_PORT", "8010"))
    uvicorn.run("dtc_server:app", host="0.0.0.0", port=port, reload=False)
