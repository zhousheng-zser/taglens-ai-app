# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from services import dtc_task_storage as storage

PROJECT_ROOT = Path(__file__).parent.parent.parent
SAM3_ROOT = PROJECT_ROOT / "sam3"
SAM3_INFER = SAM3_ROOT / "infer.py"
VENV_PYTHON = PROJECT_ROOT / "backend" / "venv" / "bin" / "python"

_dispatch_lock = threading.Lock()


def _date_token() -> str:
    return datetime.now().strftime("%y%m%d")


def _safe_text(text: str) -> str:
    return (text or "").replace(" ", "_").replace("/", "_")


def _task_id() -> str:
    return uuid.uuid4().hex[:12]


def _image_set_id() -> str:
    return uuid.uuid4().hex[:12]


def _build_task_paths(task_id: str, date_token: str) -> Dict[str, Path]:
    return {
        "output_base": SAM3_ROOT / "output" / date_token / task_id,
        "log_file": PROJECT_ROOT / "data" / "dtc_tasks" / f"{task_id}.log",
    }


def _build_image_set_input_path(image_set_id: str, date_token: str) -> Path:
    return SAM3_ROOT / "input" / date_token / image_set_id


def _resolve_backend_input_path(backend_path: str) -> Optional[Path]:
    """
    兼容前端传入的多种路径：
    1) 绝对路径；
    2) 项目内相对路径（相对 PROJECT_ROOT）；
    3) 仅传 image_set_id，自动在 sam3/input 下递归定位。
    """
    raw = (backend_path or "").strip()
    if not raw:
        return None

    candidates = [
        Path(raw),
        PROJECT_ROOT / raw,
        SAM3_ROOT / "input" / raw,
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()

    # 前端仅传 imageSetId 时，在 sam3/input/*/<imageSetId> 递归查找
    recursive = list((SAM3_ROOT / "input").glob(f"**/{raw}"))
    for p in recursive:
        if p.exists():
            return p.resolve()
    return None


def _save_upload_files(input_root: Path, files: List[Any]) -> None:
    input_root.mkdir(parents=True, exist_ok=True)
    for f in files:
        filename = os.path.basename(f.filename or "upload.jpg")
        data = f.file.read()
        with open(input_root / filename, "wb") as out:
            out.write(data)


def _make_task_record(mode: str, prompt: str, threshold: float, input_path: str, output_base: str) -> Dict[str, Any]:
    return {
        "task_id": _task_id(),
        "mode": mode,
        "date": _date_token(),
        "prompt": prompt,
        "threshold": float(threshold),
        "input_path": input_path,
        "output_base": output_base,
    }


def upload_chunk_to_image_set(
    files: List[Any],
    image_set_id: Optional[str] = None,
) -> Dict[str, Any]:
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
    else:
        date = _date_token()
        new_image_set_id = _image_set_id()
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


def create_upload_task_from_image_set(image_set_id: str, prompt: str, threshold: float) -> Dict[str, Any]:
    image_set = storage.get_image_set(image_set_id)
    if not image_set:
        raise ValueError("图片集不存在")
    input_path = Path(image_set.get("input_path") or "")
    if not input_path.exists() or not input_path.is_dir():
        raise ValueError("图片集目录不存在")

    task = _make_task_record("upload", prompt, threshold, str(input_path), "")
    task["image_set_id"] = image_set_id
    paths = _build_task_paths(task["task_id"], task["date"])
    task["output_base"] = str(paths["output_base"])
    created = storage.create_task(task)
    trigger_dispatch()
    return created


def create_path_task(backend_path: str, prompt: str, threshold: float) -> Dict[str, Any]:
    resolved = _resolve_backend_input_path(backend_path)
    if resolved is None:
        raise ValueError("backend_path 不存在")
    task = _make_task_record("path", prompt, threshold, str(resolved), "")
    paths = _build_task_paths(task["task_id"], task["date"])
    task["output_base"] = str(paths["output_base"])
    created = storage.create_task(task)
    trigger_dispatch()
    return created


def _normalize_comparison_source(stem: str, json_map: Dict[str, Dict[str, Any]]) -> str:
    if stem in json_map:
        return stem
    if "_" in stem:
        parent, suffix = stem.rsplit("_", 1)
        if suffix.isdigit() and parent in json_map:
            return parent
    return stem


def _collect_results(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    out_dir = Path(task["output_base"]) / f"{_safe_text(task['prompt'])}_{task['threshold']}"
    if not out_dir.exists():
        return []
    json_map: Dict[str, Dict[str, Any]] = {}
    for jf in out_dir.glob("*.json"):
        source = jf.stem
        json_map[source] = {
            "sourceName": jf.stem,
            "jsonName": jf.name,
            "jsonPath": str(jf),
        }

    results: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for img in sorted(out_dir.glob("*_comparison.png")):
        stem = img.name.rsplit("_comparison.png", 1)[0]
        source = _normalize_comparison_source(stem, json_map)
        item = dict(json_map.get(source, {"sourceName": source}))
        item["sourceName"] = source
        item["imageName"] = img.name
        item["imagePath"] = str(img)
        results.append(item)
        seen.add(source)

    for s, it in json_map.items():
        if s not in seen:
            results.append(dict(it))
    return results


def _normalize_results_index(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将历史重 payload results 归一化为轻量索引结构。"""
    normalized: List[Dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "sourceName": item.get("sourceName"),
                "imageName": item.get("imageName"),
                "imagePath": item.get("imagePath"),
                "jsonName": item.get("jsonName"),
                "jsonPath": item.get("jsonPath"),
            }
        )
    return normalized


def _run_task(task: Dict[str, Any]) -> None:
    task_id = str(task["task_id"])
    log_file = _build_task_paths(task_id, task["date"])["log_file"]
    log_file.parent.mkdir(parents=True, exist_ok=True)
    output_base = task["output_base"]
    Path(output_base).mkdir(parents=True, exist_ok=True)

    if not VENV_PYTHON.exists():
        raise RuntimeError(f"venv python 不存在: {VENV_PYTHON}")

    cmd = (
        f"\"{VENV_PYTHON}\" \"{SAM3_INFER}\" "
        f"-i \"{task['input_path']}\" "
        f"-o \"{output_base}\" "
        f"-t \"{task['prompt']}\" "
        f"--th {task['threshold']}"
    )

    try:
        with open(log_file, "a", encoding="utf-8") as lf:
            lf.write(f"\n===== START {datetime.now().isoformat()} =====\n")
            lf.write(f"{cmd}\n")
            lf.flush()
            proc = subprocess.Popen(
                ["bash", "-lc", cmd],
                stdout=lf,
                stderr=lf,
                # infer.py 内部使用了相对模型路径 "./sam3_pt"，需在 sam3 目录下执行
                cwd=str(SAM3_ROOT),
            )
            ret = proc.wait()

        if ret == 0:
            results = _collect_results(task)
            storage.update_task(
                task_id,
                {
                    "status": "success",
                    "finished_at": datetime.now().isoformat(),
                    "result_count": len(results),
                    # 持久化结果索引，避免前端刷新后依赖实时目录扫描
                    "results": results,
                },
            )
        else:
            storage.update_task(
                task_id,
                {
                    "status": "failed",
                    "finished_at": datetime.now().isoformat(),
                    "error": f"infer.py exited with code {ret}",
                },
            )
    except Exception as e:
        storage.update_task(
            task_id,
            {
                "status": "failed",
                "finished_at": datetime.now().isoformat(),
                "error": str(e),
            },
        )
    finally:
        trigger_dispatch()


def trigger_dispatch() -> None:
    with _dispatch_lock:
        next_task = storage.pop_next_queued_to_running()
        if not next_task:
            return
        t = threading.Thread(target=_run_task, args=(next_task,), daemon=True)
        t.start()


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_task(task_id)


def list_tasks() -> List[Dict[str, Any]]:
    items = storage.list_tasks()
    # 任务列表接口返回轻量字段，避免把大 results 索引反复下发造成卡顿
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
        normalized = _normalize_results_index(saved_results)
        # 若发现历史数据含重字段，回写轻量索引，避免后续重复大包返回
        if normalized != saved_results:
            storage.update_task(task_id, {"results": normalized, "result_count": len(normalized)})
        return normalized

    # 兼容历史任务：若未持久化 results，则回退扫描并回填
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

    output_base = Path(task.get("output_base") or "")
    deleted_paths: List[str] = []

    if output_base.exists():
        shutil.rmtree(output_base, ignore_errors=True)
        deleted_paths.append(str(output_base))

    # 清理任务日志
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

    tasks = storage.list_tasks()
    for t in tasks:
        if t.get("image_set_id") == image_set_id and t.get("status") == "running":
            raise ValueError("该图片集存在运行中的任务，暂不能删除")

    deleted_paths: List[str] = []
    input_path = Path(image_set.get("input_path") or "")
    if input_path.exists():
        shutil.rmtree(input_path, ignore_errors=True)
        deleted_paths.append(str(input_path))

    storage.delete_image_set(image_set_id)
    return {"image_set_id": image_set_id, "deleted_paths": deleted_paths}

