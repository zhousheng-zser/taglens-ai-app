# -*- coding: utf-8 -*-
"""
DTC 本地服务任务调度：内存队列 + 常驻引擎推理（无子进程）。
"""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from infer_engine import (
    DEFAULT_ADAPTER_SCALE,
    DEFAULT_CATEGORY,
    DtcInferEngine,
    _collect_results,
    _date_token,
    _safe_text,
    _task_id,
    engine,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys

if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from services import dtc_task_storage as storage  # noqa: E402

DTC_ROOT = Path(__file__).resolve().parent
_dispatch_lock = threading.Lock()


def _build_task_paths(task_id: str, date_token: str) -> Dict[str, Path]:
    return {
        "output_base": DTC_ROOT / "output" / date_token / task_id,
        "log_file": PROJECT_ROOT / "data" / "dtc_tasks" / f"{task_id}.log",
    }


def _build_image_set_input_path(image_set_id: str, date_token: str) -> Path:
    return DTC_ROOT / "input" / date_token / image_set_id


def _save_upload_files(input_root: Path, files: List[Any]) -> None:
    input_root.mkdir(parents=True, exist_ok=True)
    for f in files:
        filename = os.path.basename(f.filename or "upload.jpg")
        data = f.file.read()
        with open(input_root / filename, "wb") as out:
            out.write(data)


def _make_task_record(
    mode: str,
    prompt: str,
    threshold: float,
    input_path: str,
    output_base: str,
    category: str = DEFAULT_CATEGORY,
    adapter_scale: float = DEFAULT_ADAPTER_SCALE,
) -> Dict[str, Any]:
    return {
        "task_id": _task_id(),
        "mode": mode,
        "algorithm": "dtc",
        "date": _date_token(),
        "prompt": prompt,
        "threshold": float(threshold),
        "category": category,
        "adapter_scale": float(adapter_scale),
        "input_path": input_path,
        "output_base": output_base,
    }


def upload_chunk_to_image_set(files: List[Any], image_set_id: Optional[str] = None) -> Dict[str, Any]:
    if image_set_id:
        image_set = storage.get_image_set(image_set_id)
        if not image_set:
            raise ValueError("图片集不存在")
        input_root = Path(image_set["input_path"])
        _save_upload_files(input_root, files)
        count = len([p for p in input_root.iterdir() if p.is_file()])
        updated = storage.update_image_set(image_set_id, {"file_count": count})
        if not updated:
            raise ValueError("图片集更新失败")
        return updated

    date = _date_token()
    new_image_set_id = uuid.uuid4().hex[:12]
    input_root = _build_image_set_input_path(new_image_set_id, date)
    _save_upload_files(input_root, files)
    count = len([p for p in input_root.iterdir() if p.is_file()])
    return storage.create_image_set(
        {
            "image_set_id": new_image_set_id,
            "date": date,
            "mode": "upload",
            "input_path": str(input_root),
            "file_count": count,
        }
    )


def create_upload_task_from_image_set(
    image_set_id: str,
    prompt: str,
    threshold: float,
    category: str = DEFAULT_CATEGORY,
    adapter_scale: float = DEFAULT_ADAPTER_SCALE,
) -> Dict[str, Any]:
    image_set = storage.get_image_set(image_set_id)
    if not image_set:
        raise ValueError("图片集不存在")
    input_path = Path(image_set.get("input_path") or "")
    if not input_path.exists() or not input_path.is_dir():
        raise ValueError("图片集目录不存在")

    task = _make_task_record(
        "upload", prompt, threshold, str(input_path), "", category, adapter_scale
    )
    task["image_set_id"] = image_set_id
    paths = _build_task_paths(task["task_id"], task["date"])
    task["output_base"] = str(paths["output_base"])
    created = storage.create_task(task)
    trigger_dispatch()
    return created


def create_path_task(
    backend_path: str,
    prompt: str,
    threshold: float,
    category: str = DEFAULT_CATEGORY,
    adapter_scale: float = DEFAULT_ADAPTER_SCALE,
) -> Dict[str, Any]:
    if not backend_path or not Path(backend_path).exists():
        raise ValueError("backend_path 不存在")
    task = _make_task_record("path", prompt, threshold, backend_path, "", category, adapter_scale)
    paths = _build_task_paths(task["task_id"], task["date"])
    task["output_base"] = str(paths["output_base"])
    created = storage.create_task(task)
    trigger_dispatch()
    return created


def _run_task(task: Dict[str, Any], infer_engine: DtcInferEngine) -> None:
    task_id = str(task["task_id"])
    log_file = _build_task_paths(task_id, task["date"])["log_file"]
    log_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(log_file, "a", encoding="utf-8") as lf:
            lf.write(f"\n===== START {datetime.now().isoformat()} (in-process engine) =====\n")
            lf.write(
                f"input={task['input_path']} output={task['output_base']} "
                f"prompt={task['prompt']} th={task['threshold']}\n"
            )
            lf.flush()
            infer_engine._execute_task(task)
            results = _collect_results(task)
            updates: Dict[str, Any] = {
                "status": "success",
                "finished_at": datetime.now().isoformat(),
                "result_count": len(results),
                "results": results,
            }
            if task.get("warnings"):
                updates["error"] = "部分图片失败: " + "; ".join(task["warnings"][:3])
            storage.update_task(task_id, updates)
            lf.write(f"===== SUCCESS count={len(results)} =====\n")
    except Exception as exc:
        storage.update_task(
            task_id,
            {
                "status": "failed",
                "finished_at": datetime.now().isoformat(),
                "error": str(exc),
            },
        )
        with open(log_file, "a", encoding="utf-8") as lf:
            lf.write(f"===== FAILED {exc} =====\n")
    finally:
        trigger_dispatch(infer_engine)


def trigger_dispatch(infer_engine: Optional[DtcInferEngine] = None) -> None:
    eng = infer_engine or engine
    with _dispatch_lock:
        next_task = storage.pop_next_queued_to_running()
        if not next_task:
            return
        t = threading.Thread(target=_run_task, args=(next_task, eng), daemon=True)
        t.start()


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_task(task_id)


def list_tasks() -> List[Dict[str, Any]]:
    items = storage.list_tasks()
    light_items: List[Dict[str, Any]] = []
    for t in items:
        x = dict(t)
        x.pop("results", None)
        light_items.append(x)
    return light_items


def list_image_sets() -> List[Dict[str, Any]]:
    return storage.list_image_sets()


def get_task_results(task_id: str) -> List[Dict[str, Any]]:
    task = storage.get_task(task_id)
    if not task:
        return []
    saved_results = task.get("results")
    if isinstance(saved_results, list) and saved_results:
        return saved_results
    results = _collect_results(task)
    if results:
        storage.update_task(task_id, {"results": results, "result_count": len(results)})
    return results


def get_task_zip_path(task_id: str) -> Optional[Path]:
    task = storage.get_task(task_id)
    if not task:
        return None
    folder = Path(task["output_base"]) / f"{_safe_text(task['prompt'])}_{task['threshold']}"
    if not folder.exists():
        return None
    zip_base = folder.parent / f"{task_id}_{_safe_text(task['prompt'])}_{task['threshold']}"
    zip_file = shutil.make_archive(str(zip_base), "zip", root_dir=str(folder))
    return Path(zip_file)


def delete_task(task_id: str) -> Dict[str, Any]:
    task = storage.get_task(task_id)
    if not task:
        raise ValueError("任务不存在")
    if task.get("status") == "running":
        raise ValueError("运行中的任务不能删除，请稍后重试")

    deleted_paths: List[str] = []
    output_base = Path(task.get("output_base") or "")
    if output_base.exists():
        shutil.rmtree(output_base, ignore_errors=True)
        deleted_paths.append(str(output_base))

    log_file = _build_task_paths(task_id, str(task.get("date") or _date_token()))["log_file"]
    if log_file.exists():
        log_file.unlink(missing_ok=True)
        deleted_paths.append(str(log_file))

    storage.delete_task(task_id)
    trigger_dispatch()
    return {"task_id": task_id, "deleted_paths": deleted_paths}


def delete_image_set(image_set_id: str) -> Dict[str, Any]:
    image_set = storage.get_image_set(image_set_id)
    if not image_set:
        raise ValueError("图片集不存在")

    for t in storage.list_tasks():
        if t.get("image_set_id") == image_set_id and t.get("status") == "running":
            raise ValueError("该图片集存在运行中的任务，暂不能删除")

    deleted_paths: List[str] = []
    input_path = Path(image_set.get("input_path") or "")
    if input_path.exists():
        shutil.rmtree(input_path, ignore_errors=True)
        deleted_paths.append(str(input_path))

    storage.delete_image_set(image_set_id)
    return {"image_set_id": image_set_id, "deleted_paths": deleted_paths}
