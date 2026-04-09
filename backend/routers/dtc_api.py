from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, File, HTTPException, UploadFile, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services import dtc_task_service

router = APIRouter(prefix="/dtc", tags=["dtc"])


class CreatePathTaskRequest(BaseModel):
    backendPath: str
    prompt: str
    threshold: float = 0.3


class CreateUploadRunTaskRequest(BaseModel):
    imageSetId: str
    prompt: str
    threshold: float = 0.3


@router.post("/image-sets/upload")
async def upload_image_set_chunk(
    files: List[UploadFile] = File(...),
    imageSetId: str = Form(""),
) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一张图片")
    try:
        image_set = dtc_task_service.upload_chunk_to_image_set(
            files=files,
            image_set_id=imageSetId.strip() or None,
        )
        return {"success": True, "imageSet": image_set}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/image-sets")
async def list_image_sets() -> Dict[str, Any]:
    return {"success": True, "imageSets": dtc_task_service.list_image_sets()}


@router.delete("/image-sets/{image_set_id}")
async def delete_image_set(image_set_id: str) -> Dict[str, Any]:
    try:
        result = dtc_task_service.delete_image_set(image_set_id)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/upload-run")
async def create_upload_run_task(req: CreateUploadRunTaskRequest) -> Dict[str, Any]:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    if not req.imageSetId.strip():
        raise HTTPException(status_code=400, detail="imageSetId 不能为空")
    if not (0 < float(req.threshold) < 1):
        raise HTTPException(status_code=400, detail="threshold 必须在 (0,1) 之间")
    try:
        task = dtc_task_service.create_upload_task_from_image_set(
            req.imageSetId.strip(), req.prompt.strip(), float(req.threshold)
        )
        return {"success": True, "task": task}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/path")
async def create_path_task(req: CreatePathTaskRequest) -> Dict[str, Any]:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    if not (0 < float(req.threshold) < 1):
        raise HTTPException(status_code=400, detail="threshold 必须在 (0,1) 之间")
    try:
        task = dtc_task_service.create_path_task(req.backendPath.strip(), req.prompt.strip(), float(req.threshold))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"success": True, "task": task}


@router.get("/tasks")
async def list_tasks() -> Dict[str, Any]:
    return {"success": True, "tasks": dtc_task_service.list_tasks()}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> Dict[str, Any]:
    task = dtc_task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "task": task}


@router.get("/tasks/{task_id}/results")
async def get_task_results(task_id: str) -> Dict[str, Any]:
    task = dtc_task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    results = dtc_task_service.get_task_results(task_id)
    return {"success": True, "task": task, "results": results}


@router.get("/tasks/{task_id}/zip")
async def download_task_zip(task_id: str):
    zip_path = dtc_task_service.get_task_zip_path(task_id)
    if not zip_path or not zip_path.exists():
        raise HTTPException(status_code=404, detail="结果 ZIP 不存在")
    return FileResponse(
        path=str(zip_path),
        filename=os.path.basename(str(zip_path)),
        media_type="application/zip",
    )


@router.get("/tasks/{task_id}/artifact")
async def download_artifact(task_id: str, file_path: str):
    task = dtc_task_service.get_task(task_id)
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


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str) -> Dict[str, Any]:
    try:
        result = dtc_task_service.delete_task(task_id)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

