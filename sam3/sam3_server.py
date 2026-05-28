#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAM3 本地分割服务：启动时加载模型，HTTP 接口前缀 /sam3/*

启动: cd sam3 && ./start_sam3_server.sh
健康检查: GET http://127.0.0.1:8011/health
"""
from __future__ import annotations

import base64
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from infer_engine import DEFAULT_MODEL_DIR, engine
import server_task_service as task_svc

SAM3_ROOT = Path(__file__).resolve().parent


class CreatePathTaskRequest(BaseModel):
    backendPath: str
    prompt: str
    threshold: float = 0.3
    infer_mode: str = Field(default="mask", pattern="^(mask|bbox)$")


class CreateUploadRunTaskRequest(BaseModel):
    imageSetId: str
    prompt: str
    threshold: float = 0.3
    infer_mode: str = Field(default="mask", pattern="^(mask|bbox)$")


class SegmentPathSyncRequest(BaseModel):
    backendPath: str
    prompt: str
    threshold: float = 0.3
    infer_mode: str = Field(default="mask", pattern="^(mask|bbox)$")
    output: Optional[str] = None


class SegmentImageBase64Item(BaseModel):
    name: str = "image.jpg"
    data: str = Field(..., description="图片 base64，可带 data:image/...;base64, 前缀")


class SegmentImagesJsonRequest(BaseModel):
    images: List[SegmentImageBase64Item]
    prompt: str
    threshold: float = 0.3
    inferMode: str = Field(default="mask", pattern="^(mask|bbox)$")
    includeJsonImageData: bool = True
    includeMaskImageBase64: bool = True
    includeOverlayImageBase64: bool = True
    model_config = ConfigDict(extra="forbid")


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
    model_dir = os.environ.get("SAM3_MODEL_DIR", str(DEFAULT_MODEL_DIR))
    print(f"[SAM3 Server] 正在加载模型 model_dir={model_dir} ...")
    try:
        engine.load(model_dir=model_dir)
        print("[SAM3 Server] 模型加载完成，可接收请求")
    except Exception as exc:
        print(f"[SAM3 Server] 模型加载失败: {exc}")
        raise
    yield
    print("[SAM3 Server] 服务关闭")


app = FastAPI(
    title="SAM3 Segmentation Server",
    description="本地 SAM3 分割服务（模型常驻 GPU）",
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
        "algorithm": "sam3",  # backward compatibility
        "modelKey": "dtc_v1",
        "modelName": "DTC-Fine-grained",
        "modelAlias": "DTC-Fine",
        "model_loaded": engine.loaded,
        "load_error": engine.load_error,
        "model_dir": engine._model_dir if engine.loaded else None,
        "port_hint": int(os.environ.get("SAM3_SERVER_PORT", "8011")),
    }


@app.post("/sam3/image-sets/upload")
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


@app.get("/sam3/image-sets")
async def list_image_sets() -> Dict[str, Any]:
    return {"success": True, "imageSets": task_svc.list_image_sets()}


@app.delete("/sam3/image-sets/{image_set_id}")
async def delete_image_set(image_set_id: str) -> Dict[str, Any]:
    try:
        return {"success": True, **task_svc.delete_image_set(image_set_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sam3/tasks/upload-run")
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
            req.imageSetId.strip(), req.prompt.strip(), float(req.threshold), req.infer_mode
        )
        return {"success": True, "task": task}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sam3/tasks/path")
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
            req.infer_mode,
        )
        return {"success": True, "task": task}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sam3/segment/images")
async def segment_images_multipart(
    request: Request,
    files: List[UploadFile] = File(..., description="一张或多张图片"),
    prompt: str = Form(...),
    threshold: float = Form(0.3),
    inferMode: str = Form("mask"),
    includeJsonImageData: str = Form("true"),
    includeMaskImageBase64: str = Form("true"),
    includeOverlayImageBase64: str = Form("true"),
) -> Dict[str, Any]:
    """上传图片直接分割（无需 backendPath）。"""
    if not engine.loaded:
        raise HTTPException(status_code=503, detail=engine.load_error or "模型未就绪")
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一张图片")
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    _validate_threshold(threshold)
    form_data = await request.form()
    if "includeComparison" in form_data:
        raise HTTPException(status_code=400, detail="参数 includeComparison 已移除，请使用 includeMaskImageBase64/includeOverlayImageBase64")
    try:
        images = await _images_from_uploads(files)
        summary = engine.run_images(
            images=images,
            prompt=prompt.strip(),
            threshold=float(threshold),
            infer_mode=inferMode,
            include_json_image_data=_parse_bool_form(includeJsonImageData, True),
            include_mask_image_base64=_parse_bool_form(includeMaskImageBase64, True),
            include_overlay_image_base64=_parse_bool_form(includeOverlayImageBase64, True),
        )
        return {"success": True, **summary}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/dtc-fine/segment/images")
async def segment_images_multipart_fine(
    request: Request,
    files: List[UploadFile] = File(..., description="一张或多张图片"),
    prompt: str = Form(...),
    threshold: float = Form(0.3),
    inferMode: str = Form("mask"),
    includeJsonImageData: str = Form("true"),
    includeMaskImageBase64: str = Form("true"),
    includeOverlayImageBase64: str = Form("true"),
) -> Dict[str, Any]:
    """DTC-Fine 外部别名接口（与 /sam3/segment/images 行为一致）。"""
    return await segment_images_multipart(
        request=request,
        files=files,
        prompt=prompt,
        threshold=threshold,
        inferMode=inferMode,
        includeJsonImageData=includeJsonImageData,
        includeMaskImageBase64=includeMaskImageBase64,
        includeOverlayImageBase64=includeOverlayImageBase64,
    )


@app.post("/sam3/segment/images/json")
async def segment_images_json(req: SegmentImagesJsonRequest) -> Dict[str, Any]:
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
            infer_mode=req.inferMode,
            include_json_image_data=req.includeJsonImageData,
            include_mask_image_base64=req.includeMaskImageBase64,
            include_overlay_image_base64=req.includeOverlayImageBase64,
        )
        return {"success": True, **summary}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/sam3/segment/sync")
async def segment_path_sync(req: SegmentPathSyncRequest) -> Dict[str, Any]:
    if not engine.loaded:
        return {"success": False, "error": engine.load_error or "模型未就绪"}
    if not req.prompt.strip():
        return {"success": False, "error": "prompt 不能为空"}
    backend = req.backendPath.strip()
    if not backend or not Path(backend).exists():
        return {"success": False, "error": "backendPath 不存在"}
    import uuid
    from datetime import datetime

    task_id = uuid.uuid4().hex[:12]
    date = datetime.now().strftime("%y%m%d")
    output_base = req.output or str(SAM3_ROOT / "output" / date / f"sync_{task_id}")
    try:
        summary = engine.run_batch(
            backend,
            output_base,
            req.prompt.strip(),
            float(req.threshold),
            infer_mode=req.infer_mode,
        )
        return {
            "success": True,
            "algorithm": "sam3",
            "modelKey": "dtc_v1",
            "modelName": "DTC-Fine-grained",
            "modelAlias": "DTC-Fine",
            **summary,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/sam3/tasks")
async def list_tasks() -> Dict[str, Any]:
    return {"success": True, "tasks": task_svc.list_tasks()}


@app.get("/sam3/tasks/{task_id}")
async def get_task(task_id: str) -> Dict[str, Any]:
    task = task_svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "task": task}


@app.get("/sam3/tasks/{task_id}/results")
async def get_task_results(task_id: str) -> Dict[str, Any]:
    task = task_svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "task": task, "results": task_svc.get_task_results(task_id)}


@app.get("/sam3/tasks/{task_id}/zip")
async def download_task_zip(task_id: str):
    zip_path = task_svc.get_task_zip_path(task_id)
    if not zip_path or not zip_path.exists():
        raise HTTPException(status_code=404, detail="结果 ZIP 不存在")
    return FileResponse(path=str(zip_path), filename=zip_path.name, media_type="application/zip")


@app.get("/sam3/tasks/{task_id}/artifact")
async def download_artifact(task_id: str, file_path: str):
    task = task_svc.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    fp = Path(file_path)
    if not fp.exists() or not fp.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    allowed_roots = [Path(task["output_base"]).resolve()]
    input_path = str(task.get("input_path") or "").strip()
    if input_path:
        allowed_roots.append(Path(input_path).resolve())
    try:
        resolved = fp.resolve()
        if not any((resolved == root or root in resolved.parents) for root in allowed_roots):
            raise ValueError("out of allowed roots")
    except Exception:
        raise HTTPException(status_code=400, detail="非法文件路径")
    return FileResponse(path=str(resolved), filename=fp.name)


@app.delete("/sam3/tasks/{task_id}")
async def delete_task(task_id: str) -> Dict[str, Any]:
    try:
        return {"success": True, **task_svc.delete_task(task_id)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("SAM3_SERVER_PORT", "8011"))
    uvicorn.run("sam3_server:app", host="0.0.0.0", port=port, reload=False)
