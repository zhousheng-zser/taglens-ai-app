# -*- coding: utf-8 -*-
"""
SAM3 任务存储（JSON 文件）
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "sam3_tasks"
TASKS_FILE = DATA_DIR / "tasks.json"
IMAGE_SETS_FILE = DATA_DIR / "image_sets.json"
_LOCK = Lock()


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_unlocked() -> Dict[str, Dict[str, Any]]:
    if not TASKS_FILE.exists():
        return {}
    try:
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _load_image_sets_unlocked() -> Dict[str, Dict[str, Any]]:
    if not IMAGE_SETS_FILE.exists():
        return {}
    try:
        with open(IMAGE_SETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_unlocked(tasks: Dict[str, Dict[str, Any]]) -> None:
    _ensure_dir()
    tmp = TASKS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    tmp.replace(TASKS_FILE)


def _save_image_sets_unlocked(image_sets: Dict[str, Dict[str, Any]]) -> None:
    _ensure_dir()
    tmp = IMAGE_SETS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(image_sets, f, ensure_ascii=False, indent=2)
    tmp.replace(IMAGE_SETS_FILE)


def _next_queue_index(tasks: Dict[str, Dict[str, Any]]) -> int:
    m = 0
    for t in tasks.values():
        q = int(t.get("queue_index", 0) or 0)
        if q > m:
            m = q
    return m + 1


def create_task(task: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        tasks = _load_unlocked()
        now = datetime.now().isoformat()
        task_id = str(task["task_id"])
        task.setdefault("status", "queued")
        if task.get("status") == "queued":
            task.setdefault("queue_index", _next_queue_index(tasks))
        else:
            task.setdefault("queue_index", None)
        task.setdefault("created_at", now)
        task.setdefault("updated_at", now)
        task.setdefault("started_at", None)
        task.setdefault("finished_at", None)
        task.setdefault("error", None)
        task.setdefault("result_count", 0)
        tasks[task_id] = task
        _save_unlocked(tasks)
        return dict(task)


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        tasks = _load_unlocked()
        task = tasks.get(task_id)
    return dict(task) if task else None


def list_tasks() -> List[Dict[str, Any]]:
    with _LOCK:
        tasks = _load_unlocked()
        items = [dict(v) for v in tasks.values()]
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


def update_task(task_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _LOCK:
        tasks = _load_unlocked()
        task = tasks.get(task_id)
        if not task:
            return None
        task.update(updates)
        task["updated_at"] = datetime.now().isoformat()
        tasks[task_id] = task
        _save_unlocked(tasks)
        return dict(task)

def delete_task(task_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        tasks = _load_unlocked()
        task = tasks.pop(task_id, None)
        if task is None:
            return None
        _save_unlocked(tasks)
        return dict(task)


def has_running_task() -> bool:
    with _LOCK:
        tasks = _load_unlocked()
        return any(t.get("status") == "running" for t in tasks.values())


def pop_next_queued_to_running() -> Optional[Dict[str, Any]]:
    with _LOCK:
        tasks = _load_unlocked()
        if any(t.get("status") == "running" for t in tasks.values()):
            return None

        queued = [t for t in tasks.values() if t.get("status") == "queued"]
        if not queued:
            return None
        queued.sort(key=lambda x: int(x.get("queue_index", 0) or 0))
        target = queued[0]
        now = datetime.now().isoformat()
        target["status"] = "running"
        target["started_at"] = now
        target["updated_at"] = now
        tasks[str(target["task_id"])] = target
        _save_unlocked(tasks)
        return dict(target)


def enqueue_task(task_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        tasks = _load_unlocked()
        task = tasks.get(task_id)
        if not task:
            return None
        if task.get("status") == "queued":
            return dict(task)
        if task.get("status") == "running":
            return None
        task["status"] = "queued"
        task["queue_index"] = _next_queue_index(tasks)
        task["updated_at"] = datetime.now().isoformat()
        tasks[task_id] = task
        _save_unlocked(tasks)
        return dict(task)


def create_image_set(image_set: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        image_sets = _load_image_sets_unlocked()
        now = datetime.now().isoformat()
        image_set_id = str(image_set["image_set_id"])
        image_set.setdefault("mode", "upload")
        image_set.setdefault("created_at", now)
        image_set.setdefault("updated_at", now)
        image_set.setdefault("file_count", 0)
        image_sets[image_set_id] = image_set
        _save_image_sets_unlocked(image_sets)
        return dict(image_set)


def get_image_set(image_set_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        image_sets = _load_image_sets_unlocked()
        item = image_sets.get(image_set_id)
    return dict(item) if item else None


def list_image_sets() -> List[Dict[str, Any]]:
    with _LOCK:
        image_sets = _load_image_sets_unlocked()
        items = [dict(v) for v in image_sets.values()]
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


def update_image_set(image_set_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _LOCK:
        image_sets = _load_image_sets_unlocked()
        item = image_sets.get(image_set_id)
        if not item:
            return None
        item.update(updates)
        item["updated_at"] = datetime.now().isoformat()
        image_sets[image_set_id] = item
        _save_image_sets_unlocked(image_sets)
        return dict(item)


def delete_image_set(image_set_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        image_sets = _load_image_sets_unlocked()
        item = image_sets.pop(image_set_id, None)
        if item is None:
            return None
        _save_image_sets_unlocked(image_sets)
        return dict(item)

