# -*- coding: utf-8 -*-
"""标签搜索结果图片批量导出：经 HTTP bucket-taglens 地址下载并打包 zip。"""
from __future__ import annotations

import re
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from services.search_progress import SearchCancellation, SearchCancelledError, SearchProgress

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOWNLOAD_DIR = PROJECT_ROOT / "data" / "download"
STAGING_DIR = DOWNLOAD_DIR / "_staging"
ZIP_NAME_PATTERN = re.compile(r"^search_images_[\w\-]+\.zip$")

# 直拉 MinIO HTTP（与前端 bucket-taglens 代理目标一致，不经 MinIO SDK）
BUCKET_TAGLENS_HTTP_ORIGIN = "http://192.168.1.117:9000"

ZIP_IMAGE_DIR = "images"

MAX_DOWNLOAD_WORKERS = 8
DOWNLOAD_TIMEOUT_SEC = 120

_HTTP_SESSION = requests.Session()
_HTTP_SESSION.trust_env = False  # 忽略 HTTP_PROXY，避免内网地址 503


def encode_file_path_for_url(file_path: str) -> str:
    normalized = (file_path or "").lstrip("/")
    if not normalized:
        return ""
    return "/".join(quote(part, safe="") for part in normalized.split("/"))


def build_bucket_taglens_url(file_path: str) -> str:
    encoded = encode_file_path_for_url(file_path)
    return f"{BUCKET_TAGLENS_HTTP_ORIGIN}/bucket-taglens/{encoded}"


def _safe_local_name(uuid: str, file_path: str) -> str:
    base = Path(file_path).name or "image.jpg"
    safe_uuid = re.sub(r"[^\w\-]", "_", uuid or "unknown")
    return f"{safe_uuid}_{base}"


def _download_one(file_path: str, uuid: str, dest: Path) -> Tuple[str, bool, str]:
    url = build_bucket_taglens_url(file_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _HTTP_SESSION.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SEC) as resp:
            if resp.status_code != 200:
                return file_path, False, f"HTTP {resp.status_code}"
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        fh.write(chunk)
        if dest.stat().st_size <= 0:
            dest.unlink(missing_ok=True)
            return file_path, False, "空文件"
        return file_path, True, ""
    except Exception as exc:
        dest.unlink(missing_ok=True)
        return file_path, False, str(exc)


def cleanup_non_zip_files_in_download_dir() -> int:
    """删除 download 目录下除 .zip 外的文件/子目录（保留历史压缩包）。"""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    removed = 0
    for entry in DOWNLOAD_DIR.iterdir():
        if entry.name == "_staging":
            if entry.exists():
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
            continue
        if entry.is_file() and entry.suffix.lower() == ".zip":
            continue
        if entry.is_file():
            entry.unlink(missing_ok=True)
            removed += 1
        elif entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    for entry in STAGING_DIR.iterdir():
        if entry.is_file():
            entry.unlink(missing_ok=True)
            removed += 1
        elif entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def resolve_export_zip_path(filename: str) -> Optional[Path]:
    if not ZIP_NAME_PATTERN.match(filename or ""):
        return None
    path = (DOWNLOAD_DIR / filename).resolve()
    if DOWNLOAD_DIR.resolve() not in path.parents:
        return None
    if not path.is_file():
        return None
    return path


def export_search_images_zip(
    items: List[Dict[str, Any]],
    progress: Optional[SearchProgress] = None,
) -> Dict[str, Any]:
    """
    items: 每项含 filePath、uuid（可选 fileName）
    返回 zip 文件名与统计信息。
    """
    prog = progress or SearchProgress()
    prog.check_cancelled()

    if not items:
        raise ValueError("没有可导出的图片")

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    # 按 filePath 去重，保留首条
    seen_paths: set[str] = set()
    unique_items: List[Dict[str, Any]] = []
    for item in items:
        fp = (item.get("filePath") or item.get("file_path") or "").strip()
        if not fp or fp in seen_paths:
            continue
        seen_paths.add(fp)
        unique_items.append(item)

    total = len(unique_items)
    prog.report("download", 5, f"准备下载 {total} 张图片…")

    staging_files: List[Path] = []
    ok_count = 0
    fail_count = 0
    errors: List[str] = []

    def _report_download(done: int) -> None:
        pct = 5 + min(80, (done / max(total, 1)) * 80)
        prog.report("download", pct, f"正在下载图片（{done}/{total}）…")

    with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
        futures = {}
        for item in unique_items:
            prog.check_cancelled()
            file_path = (item.get("filePath") or item.get("file_path") or "").strip()
            uuid = str(item.get("uuid") or item.get("id") or "")
            local_name = _safe_local_name(uuid, file_path)
            dest = STAGING_DIR / local_name
            futures[pool.submit(_download_one, file_path, uuid, dest)] = (file_path, dest)

        done = 0
        for future in as_completed(futures):
            prog.check_cancelled()
            file_path, dest = futures[future]
            _, ok, err = future.result()
            done += 1
            if ok:
                ok_count += 1
                staging_files.append(dest)
            else:
                fail_count += 1
                if len(errors) < 20:
                    errors.append(f"{file_path}: {err}")
            if done % 10 == 0 or done == total:
                _report_download(done)

    if ok_count == 0:
        sample = "; ".join(errors[:3])
        raise RuntimeError(
            f"所有图片下载失败，请检查 filePath 与 bucket-taglens 是否可用。示例: {sample}"
        )

    prog.report("zip", 88, f"正在打包 {ok_count} 张图片…")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"search_images_{timestamp}.zip"
    zip_path = DOWNLOAD_DIR / zip_name

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        used_names: set[str] = set()
        for local_path in staging_files:
            prog.check_cancelled()
            entry_name = local_path.name
            if entry_name in used_names:
                stem = local_path.stem
                suffix = local_path.suffix
                idx = 2
                while entry_name in used_names:
                    entry_name = f"{stem}_{idx}{suffix}"
                    idx += 1
            used_names.add(entry_name)
            zf.write(local_path, arcname=f"{ZIP_IMAGE_DIR}/{entry_name}")

    prog.report("cleanup", 95, "正在清理临时文件…")
    removed = cleanup_non_zip_files_in_download_dir()

    prog.report("done", 100, f"导出完成：{ok_count} 张图片已打包")
    return {
        "fileName": zip_name,
        "zipPath": str(zip_path),
        "total": total,
        "downloaded": ok_count,
        "failed": fail_count,
        "removedTempFiles": removed,
        "errors": errors,
    }
