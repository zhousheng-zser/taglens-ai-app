"""事件分段描述补齐：持久化记录已确认损坏的视频，避免重复 ffmpeg 检测。"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

_REGISTRY_LOCK = threading.Lock()
_KNOWN_PATHS: Optional[Set[str]] = None

DAMAGED_VIDEOS_FILE = (
    Path(__file__).resolve().parent.parent.parent / "data" / "segment_damaged_videos.txt"
)


def _normalize_path(media_path: str) -> str:
    return (media_path or "").strip()


def _parse_line(line: str) -> Optional[str]:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    for part in raw.split("\t"):
        p = part.strip()
        if p.startswith("/"):
            return p
    return None


def _load_paths_from_file() -> Set[str]:
    paths: Set[str] = set()
    if DAMAGED_VIDEOS_FILE.is_file():
        text = DAMAGED_VIDEOS_FILE.read_text(encoding="utf-8")
        for line in text.splitlines():
            path = _parse_line(line)
            if path:
                paths.add(path)
    return paths


def reload_cache() -> int:
    """从 data/segment_damaged_videos.txt 加载路径集合，返回条数。"""
    global _KNOWN_PATHS
    paths = _load_paths_from_file()
    with _REGISTRY_LOCK:
        _KNOWN_PATHS = paths
    return len(paths)


def count_known() -> int:
    global _KNOWN_PATHS
    with _REGISTRY_LOCK:
        if _KNOWN_PATHS is None:
            _KNOWN_PATHS = _load_paths_from_file()
        return len(_KNOWN_PATHS)


def get_known_paths() -> Set[str]:
    """返回当前已知的损坏视频路径集合（只读副本）。"""
    global _KNOWN_PATHS
    with _REGISTRY_LOCK:
        if _KNOWN_PATHS is None:
            _KNOWN_PATHS = _load_paths_from_file()
        return set(_KNOWN_PATHS)


def is_known_damaged(media_path: str) -> bool:
    global _KNOWN_PATHS
    path = _normalize_path(media_path)
    if not path:
        return False
    with _REGISTRY_LOCK:
        if _KNOWN_PATHS is None:
            _KNOWN_PATHS = _load_paths_from_file()
        return path in _KNOWN_PATHS


def record_damaged(media_path: str, reason: str = "") -> bool:
    """
    追加记录损坏视频路径。已存在则不再写入。
    返回 True 表示本次为新记录。
    """
    global _KNOWN_PATHS
    path = _normalize_path(media_path)
    if not path:
        return False

    with _REGISTRY_LOCK:
        if _KNOWN_PATHS is None:
            _KNOWN_PATHS = _load_paths_from_file()
        if path in _KNOWN_PATHS:
            return False

        DAMAGED_VIDEOS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat(timespec="seconds")
        reason_text = (reason or "").replace("\t", " ").replace("\n", " ").strip()
        line = f"{ts}\t{path}\t{reason_text}\n" if reason_text else f"{ts}\t{path}\n"
        with open(DAMAGED_VIDEOS_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
        _KNOWN_PATHS.add(path)
        return True
