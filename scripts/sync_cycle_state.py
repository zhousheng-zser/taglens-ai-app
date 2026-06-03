#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""03/04 同步调度 cycle 状态持久化（支持 systemd on-failure 重启后续跑）。"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

_DATETIME_KEYS = ("remote_at", "download_at", "cooldown_until")


def cycle_state_path(runtime_dir: str) -> str:
    return os.path.join(runtime_dir, "cycle_state.json")


def _dt_to_iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _iso_to_dt(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return value


def serialize_cycle(cycle: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for key, val in cycle.items():
        if key in _DATETIME_KEYS:
            out[key] = _dt_to_iso(val)
        else:
            out[key] = val
    return out


def deserialize_cycle(data: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(data)
    for key in _DATETIME_KEYS:
        if key in out:
            out[key] = _iso_to_dt(out.get(key))
    for bool_key in ("remote_done", "download_done"):
        if bool_key in out:
            out[bool_key] = bool(out[bool_key])
    return out


def save_cycle_state(runtime_dir: str, cycle: Dict[str, Any]) -> None:
    os.makedirs(runtime_dir, exist_ok=True)
    path = cycle_state_path(runtime_dir)
    payload = serialize_cycle(cycle)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def clear_cycle_state(runtime_dir: str) -> bool:
    """删除持久化调度（用户 UI 停止/重新开始时调用，崩溃自动重启应保留 state）。"""
    path = cycle_state_path(runtime_dir)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def log_cycle_resume(cycle: Dict[str, Any]) -> None:
    """从文件恢复后打印当前计划，便于日志面板查看。"""
    print("📂 已从 cycle_state.json 恢复调度状态（进程崩溃/自动重启续跑）")
    remote_at = cycle.get("remote_at")
    download_at = cycle.get("download_at")
    cooldown_until = cycle.get("cooldown_until")
    if remote_at and isinstance(remote_at, datetime):
        print(
            f"📅 远端打包计划: {remote_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(remote_done={cycle.get('remote_done')})"
        )
    if download_at and isinstance(download_at, datetime):
        print(
            f"📥 下载计划: {download_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(download_done={cycle.get('download_done')})"
        )
    if cooldown_until and isinstance(cooldown_until, datetime):
        print(f"⏸ 冷却至: {cooldown_until.strftime('%Y-%m-%d %H:%M:%S')}")


def load_cycle_state(runtime_dir: str) -> Optional[Dict[str, Any]]:
    path = cycle_state_path(runtime_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return deserialize_cycle(data)
    except (json.JSONDecodeError, OSError, TypeError) as e:
        print(f"⚠️ 读取 cycle_state.json 失败，将重新调度: {e}")
        return None
