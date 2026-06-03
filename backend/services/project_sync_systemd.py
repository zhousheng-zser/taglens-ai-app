# -*- coding: utf-8 -*-
"""通过 systemd 启停 sync_task_01~04，与 taglens.target 解耦。"""

import os
import subprocess
from datetime import datetime
from typing import Optional, Tuple

SCRIPT_TO_UNIT = {
    "sync_task_01.py": "taglens-sync-01.service",
    "sync_task_02.py": "taglens-sync-02.service",
    "sync_task_03.py": "taglens-sync-03.service",
    "sync_task_04.py": "taglens-sync-04.service",
}

# 03/04 使用 cycle_state.json；UI 启停应重新随机打包时间，仅 on-failure 重启才续跑
SCRIPT_TO_RUNTIME_REL = {
    "sync_task_03.py": "runtime/sync_task_03",
    "sync_task_04.py": "runtime/sync_task_04",
}


def script_basename(script_path: str) -> str:
    return os.path.basename(script_path.strip())


def unit_for_script(script_path: str) -> Optional[str]:
    return SCRIPT_TO_UNIT.get(script_basename(script_path))


def is_managed_sync_script(script_path: str) -> bool:
    return unit_for_script(script_path) is not None


def runtime_dir_for_script(project_root: str, script_path: str) -> Optional[str]:
    rel = SCRIPT_TO_RUNTIME_REL.get(script_basename(script_path))
    if not rel:
        return None
    return os.path.join(project_root, rel)


def clear_cycle_state_for_script(project_root: str, script_path: str) -> bool:
    runtime_dir = runtime_dir_for_script(project_root, script_path)
    if not runtime_dir:
        return False
    state_path = os.path.join(runtime_dir, "cycle_state.json")
    if os.path.isfile(state_path):
        os.remove(state_path)
        return True
    return False


def log_file_for_script(project_root: str, script_path: str) -> str:
    log_dir = os.path.join(project_root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, f"{script_basename(script_path)}.log")


def _run_systemctl(*args: str) -> Tuple[bool, str]:
    cmd = ["systemctl", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        msg = out or err or f"exit {result.returncode}"
        return result.returncode == 0, msg
    except Exception as e:
        return False, str(e)


def append_log_start_header(project_root: str, script_path: str) -> None:
    log_file = log_file_for_script(project_root, script_path)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 30}\n")
        f.write(f"[{datetime.now()}] 启动同步单元: {unit_for_script(script_path)}\n")


def start_script(project_root: str, script_path: str) -> Tuple[bool, str]:
    unit = unit_for_script(script_path)
    if not unit:
        return False, "非受管 sync 脚本"
    running, _ = is_running(script_path)
    if running:
        return False, "该脚本正在运行中"
    cleared = clear_cycle_state_for_script(project_root, script_path)
    append_log_start_header(project_root, script_path)
    if cleared:
        log_file = log_file_for_script(project_root, script_path)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("[启动] 已清除 cycle_state，将重新随机远端打包时间\n")
    ok, msg = _run_systemctl("start", unit)
    if ok:
        return True, f"已启动 {unit}"
    return False, f"启动失败: {msg}"


def stop_script(project_root: str, script_path: str) -> Tuple[bool, str]:
    unit = unit_for_script(script_path)
    if not unit:
        return False, "非受管 sync 脚本"
    log_file = log_file_for_script(project_root, script_path)
    if os.path.exists(log_file):
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(
                f"\n[{datetime.now().strftime('%H:%M:%S')}] "
                f"用户请求停止 (systemctl stop {unit})\n"
            )
    clear_cycle_state_for_script(project_root, script_path)
    ok, msg = _run_systemctl("stop", unit)
    if ok:
        return True, f"已停止 {unit}"
    return True, f"停止完成: {msg}"


def is_running(script_path: str) -> Tuple[bool, str]:
    unit = unit_for_script(script_path)
    basename = script_basename(script_path)
    if unit:
        ok, _ = _run_systemctl("is-active", "--quiet", unit)
        if ok:
            return True, "systemd:active"
        # 受管 sync 以 systemd 为准；单元已停时不做 pgrep，避免误判「仍在运行」
        return False, "systemd:inactive"
    try:
        subprocess.check_output(
            ["pgrep", "-f", f"scripts/{basename}"],
            stderr=subprocess.DEVNULL,
        )
        return True, "pgrep"
    except subprocess.CalledProcessError:
        pass
    return False, "idle"


def read_log_tail(project_root: str, script_path: str, lines: int = 300) -> list:
    log_file = log_file_for_script(project_root, script_path)
    if not os.path.exists(log_file):
        return ["等待日志生成..."]
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        return [ln.rstrip("\n") for ln in all_lines[-lines:]]
    except Exception as e:
        return [f"读取日志错误: {e}"]
