#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临时脚本：扫描 MinIO event_data/S32/{101,105,107,201}/ 并导入 taglens_event.event_records。

参考：
- scripts/import_event_tree_to_db.py（目录解析 / 字段组装）
- scripts/import_jwzhzx_videos_to_event_records.py（MinIO 扫描入库）
- generate_jwzhzx_video_covers.py（ffmpeg 抽首帧写 image_big.jpg）

目录示例：
  event_data/S32/101/202606/3513145734067130368_18_16_08_22_000/S32_3513145734067130368.mp4

用法：
  # dry-run
  backend/venv/bin/python scripts/import_s32_to_event_records.py

  # 正式执行（默认 8 并发抽封面）
  backend/venv/bin/python scripts/import_s32_to_event_records.py --run

  # 只测 2 条
  backend/venv/bin/python scripts/import_s32_to_event_records.py --run --limit 2

  # 跳过封面（只写库）
  backend/venv/bin/python scripts/import_s32_to_event_records.py --run --skip-cover
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from core.event_database import get_event_db_connection  # noqa: E402
from core.minio_storage_client import get_storage_client  # noqa: E402

BUCKET = "bucket-taglens"
PROJECT_ID = "S32"
PROJECT_NAME = "S32申嘉湖"
EVENT_TYPES = ["101", "105", "107", "201"]
DEFAULT_WORKERS = 8
SEGMENT_RE = re.compile(r"_\d{3}\.mp4$", re.IGNORECASE)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}

EVENT_TYPE_NAMES = {
    "101": "异常停车",
    "105": "抛洒物",
    "107": "占道施工",
    "201": "交通拥堵",
}

INSERT_SQL = """
INSERT INTO event_records (
    event_id, project_id, project_name, camera_name, mvp_camera_id,
    event_type, start_time, video_url, mvp_ip, task_id, source_id, source_name,
    event_name, event_type_corrected, event_name_corrected, event_level,
    event_position, end_time, detect_time,
    vehicle_plate, vehicle_plate_color, vehicle_confidence, vehicle_type,
    vehicle_category, vehicle_color, vehicle_speed, lane_number,
    process_status, event_confidence, scene_match, scene_match_degree,
    analysis_server, management_server, debugging_info_json,
    image_paths, video_path, download_source, status, created_at,
    segment_count, segment_paths_json, questions_answers_list,
    accident_questions_answers_json
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s
)
"""

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def normalize_media_path(path: str) -> str:
    value = path.strip()
    if not value:
        return ""
    if value.startswith("bucket-taglens/event_data/"):
        return "/event_data/" + value[len("bucket-taglens/event_data/") :]
    if value.startswith("/bucket-taglens/event_data/"):
        return "/event_data/" + value[len("/bucket-taglens/event_data/") :]
    if value.startswith("event_data/"):
        return "/" + value
    if value.startswith("/event_data/"):
        return value
    return value


def db_path_to_object(db_path: str) -> str:
    return str(db_path).strip().lstrip("/")


def build_start_time(yyyymm: str, dd: str, hh: str, mm: str, ss: str) -> str:
    year = int(yyyymm[:4])
    month = int(yyyymm[4:6])
    day = int(dd)
    hour = int(hh)
    minute = int(mm)
    second = int(ss)
    return datetime(year, month, day, hour, minute, second).strftime(
        "%Y-%m-%d %H:%M:%S.000000"
    )


def parse_folder_meta(folder_prefix: str) -> Optional[Dict[str, str]]:
    """
    folder_prefix 例:
      event_data/S32/101/202606/3513145734067130368_18_16_08_22_000/
    """
    cleaned = folder_prefix.strip().strip("/")
    parts = cleaned.split("/")
    if len(parts) < 5 or parts[0] != "event_data" or parts[1] != PROJECT_ID:
        return None
    project_id, event_type, yyyymm, tail = parts[1], parts[2], parts[3], parts[4]
    if event_type not in EVENT_TYPES:
        return None
    tokens = tail.split("_")
    if len(tokens) < 6:
        return None
    event_id = tokens[0]
    dd, hh, mm, ss = tokens[1], tokens[2], tokens[3], tokens[4]
    camera_id = tokens[5]
    try:
        start_time = build_start_time(yyyymm, dd, hh, mm, ss)
    except Exception:
        start_time = ""
    return {
        "event_id": event_id,
        "project_id": project_id,
        "event_type": event_type,
        "yyyymm": yyyymm,
        "mvp_camera_id": camera_id,
        "start_time": start_time,
        "folder_prefix": cleaned + "/",
    }


def pick_main_and_segments(video_keys: List[str]) -> Tuple[Optional[str], List[str]]:
    mains = [k for k in video_keys if not SEGMENT_RE.search(k)]
    segs = sorted(k for k in video_keys if SEGMENT_RE.search(k))
    if mains:
        # 优先选文件名更短、不含多余后缀的主视频
        mains.sort(key=lambda k: (len(Path(k).name), k))
        return mains[0], segs
    if segs:
        return segs[0], segs[1:]
    return None, []


def list_event_folders(limit: int = 0) -> List[str]:
    client = get_storage_client(skip_bucket_check=True)
    minio = client.client
    folders: List[str] = []
    for event_type in EVENT_TYPES:
        type_prefix = f"event_data/{PROJECT_ID}/{event_type}/"
        type_count = 0
        months = list(minio.list_objects(BUCKET, prefix=type_prefix, recursive=False))
        for month in months:
            if not month.is_dir:
                continue
            for event_dir in minio.list_objects(BUCKET, prefix=month.object_name, recursive=False):
                if event_dir.is_dir:
                    folders.append(event_dir.object_name)
                else:
                    parent = str(Path(event_dir.object_name).parent).replace("\\", "/") + "/"
                    if parent not in folders:
                        folders.append(parent)
                type_count += 1
                if limit and len(folders) >= limit:
                    log(f"事件类型 {event_type}: 已达 --limit {limit}，停止扫描")
                    return folders
        log(f"事件类型 {event_type}: 扫描到 {type_count} 个目录")
    return folders


def collect_folder_media(folder_prefix: str) -> Dict[str, List[str]]:
    client = get_storage_client(skip_bucket_check=True)
    images: List[str] = []
    videos: List[str] = []
    for obj in client.client.list_objects(BUCKET, prefix=folder_prefix, recursive=True):
        if obj.is_dir:
            continue
        suffix = Path(obj.object_name).suffix.lower()
        if suffix in IMAGE_EXTS:
            images.append(obj.object_name)
        elif suffix in VIDEO_EXTS:
            videos.append(obj.object_name)
    return {"images": sorted(images), "videos": sorted(videos)}


def extract_first_frame(presigned_url: str, output_path: str) -> bool:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", presigned_url, "-frames:v", "1", "-q:v", "2", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0


def ensure_cover(video_object: str, folder_prefix: str, dry_run: bool) -> Tuple[str, str]:
    """
    确保目录下有 image_big.jpg。
    返回 (image_db_path, status) status: ok/exists/fail/dry-run/skip
    """
    image_object = folder_prefix.rstrip("/") + "/image_big.jpg"
    image_db_path = normalize_media_path(image_object)
    client = get_storage_client(skip_bucket_check=True)
    if client.file_exists(image_object):
        return image_db_path, "exists"
    if dry_run:
        return image_db_path, "dry-run"
    url = client.client.presigned_get_object(
        client.bucket, video_object, expires=timedelta(hours=1),
    )
    with tempfile.TemporaryDirectory(prefix="s32_cover_") as td:
        jpg_path = os.path.join(td, "image_big.jpg")
        if not extract_first_frame(url, jpg_path):
            return image_db_path, "fail"
        client.upload_file(jpg_path, image_object, content_type="image/jpeg")
    return image_db_path, "ok"


def load_existing_keys() -> set[Tuple[str, str, str]]:
    with get_event_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT event_id, project_id, event_type_corrected
            FROM event_records
            WHERE project_id = %s
            """,
            (PROJECT_ID,),
        )
        return {
            (str(r["event_id"]), str(r["project_id"]), str(r["event_type_corrected"]))
            for r in cur.fetchall()
        }


def make_row(item: Dict, created_at: str) -> tuple:
    event_name = EVENT_TYPE_NAMES.get(item["event_type"], item["event_type"])
    return (
        item["event_id"],
        PROJECT_ID,
        PROJECT_NAME,
        "",
        item["mvp_camera_id"],
        "",
        item["start_time"],
        "",
        "",
        "",
        "",
        "",
        event_name,
        item["event_type"],
        event_name,
        "1",
        "",
        "",
        item["start_time"],
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "无事件调试信息",
        item.get("image_paths", ""),
        item["video_path"],
        "skipped",
        "completed",
        created_at,
        item.get("segment_count", 0),
        item.get("segment_paths_json", "[]"),
        "[]",
        "[]",
    )


def process_one(
    folder_prefix: str,
    dry_run: bool,
    skip_cover: bool,
    existing: set[Tuple[str, str, str]],
) -> Tuple[str, str, Optional[Dict], Optional[str]]:
    """
    返回 (status, folder, item_or_none, error)
    status: prepared / skip_exists / skip_no_video / fail
    """
    meta = parse_folder_meta(folder_prefix)
    if not meta:
        return "fail", folder_prefix, None, "目录结构无法解析"

    key = (meta["event_id"], PROJECT_ID, meta["event_type"])
    if key in existing:
        return "skip_exists", folder_prefix, None, None

    media = collect_folder_media(folder_prefix)
    main_video, segments = pick_main_and_segments(media["videos"])
    if not main_video:
        return "skip_no_video", folder_prefix, None, "目录无视频"

    image_paths = ""
    # 已有 image_big.jpg 优先
    existing_cover = next(
        (p for p in media["images"] if p.endswith("/image_big.jpg")),
        None,
    )
    if existing_cover:
        image_paths = normalize_media_path(existing_cover)
        cover_status = "exists"
    elif skip_cover:
        cover_status = "skip"
    else:
        image_paths, cover_status = ensure_cover(main_video, folder_prefix, dry_run)
        if cover_status == "fail":
            return "fail", folder_prefix, None, "封面抽帧失败"

    segment_db_paths = [normalize_media_path(s) for s in segments]
    item = {
        **meta,
        "video_path": normalize_media_path(main_video),
        "image_paths": image_paths,
        "segment_count": len(segment_db_paths),
        "segment_paths_json": json.dumps(segment_db_paths, ensure_ascii=False),
        "cover_status": cover_status,
    }
    return "prepared", folder_prefix, item, None


def insert_rows(items: List[Dict], created_at: str, dry_run: bool) -> Tuple[int, int]:
    if not items:
        return 0, 0
    if dry_run:
        return len(items), 0
    inserted = failed = 0
    with get_event_db_connection() as conn:
        cur = conn.cursor()
        for item in items:
            try:
                cur.execute(INSERT_SQL, make_row(item, created_at))
                inserted += 1
            except Exception as exc:
                failed += 1
                if failed <= 10:
                    log(f"  [DB FAIL] {item['event_id']}/{item['event_type']}: {exc}")
    return inserted, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 S32 MinIO 事件到 event_records")
    parser.add_argument("--run", action="store_true", help="真正执行（默认 dry-run）")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个事件目录")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="封面抽帧并发数")
    parser.add_argument("--skip-cover", action="store_true", help="不生成封面")
    parser.add_argument("--verbose", action="store_true", help="打印每条处理结果")
    args = parser.parse_args()

    dry_run = not args.run
    workers = max(1, args.workers)
    verbose = args.verbose or bool(args.limit and args.limit <= 20)

    if dry_run:
        log("=== DRY-RUN 模式（不写 MinIO/DB） ===")
    else:
        log("=== 正式执行模式 ===")
    log(f"workers={workers}, skip_cover={args.skip_cover}")

    t0 = time.time()
    log("\n--- 扫描 MinIO ---")
    folders = list_event_folders(limit=args.limit)
    log(f"待处理目录: {len(folders)}")

    existing = load_existing_keys()
    log(f"DB 已有 S32 记录: {len(existing)}")

    prepared: List[Dict] = []
    stats = {
        "prepared": 0,
        "skip_exists": 0,
        "skip_no_video": 0,
        "fail": 0,
        "cover_ok": 0,
        "cover_exists": 0,
        "cover_fail": 0,
    }

    log("\n--- 解析目录 / 抽封面 ---")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(process_one, folder, dry_run, args.skip_cover, existing): folder
            for folder in folders
        }
        done = 0
        for future in as_completed(futures):
            status, folder, item, err = future.result()
            done += 1
            stats[status] = stats.get(status, 0) + 1
            if status == "prepared" and item:
                prepared.append(item)
                cs = item.get("cover_status")
                if cs == "ok":
                    stats["cover_ok"] += 1
                elif cs == "exists":
                    stats["cover_exists"] += 1
                elif cs == "fail":
                    stats["cover_fail"] += 1
                if verbose:
                    log(
                        f"  [{done}] {item['event_type']}/{item['event_id']} "
                        f"cover={cs} video={item['video_path']}"
                    )
            elif status == "fail" and verbose:
                log(f"  [{done}] FAIL {folder}: {err}")
            if done % 100 == 0 or done == len(folders):
                log(
                    f"进度 {done}/{len(folders)} | 可入库 {len(prepared)} | "
                    f"已存在跳过 {stats['skip_exists']} | 失败 {stats['fail']}"
                )

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.000000")
    log("\n--- 写入 event_records ---")
    inserted, failed = insert_rows(prepared, created_at, dry_run)

    elapsed = time.time() - t0
    log(
        f"\n=== 完成 ===\n"
        f"扫描 {len(folders)} | 可入库 {len(prepared)} | "
        f"写入 {'(dry-run) ' if dry_run else ''}{inserted} | DB失败 {failed}\n"
        f"已存在跳过 {stats['skip_exists']} | 无视频 {stats['skip_no_video']} | "
        f"处理失败 {stats['fail']}\n"
        f"封面: 新生成 {stats['cover_ok']} | 已有 {stats['cover_exists']} | "
        f"失败 {stats['cover_fail']}\n"
        f"耗时 {elapsed:.1f}s"
    )
    if prepared:
        sample = prepared[0]
        log(
            "示例: "
            + json.dumps(
                {
                    "event_id": sample["event_id"],
                    "event_type": sample["event_type"],
                    "mvp_camera_id": sample["mvp_camera_id"],
                    "start_time": sample["start_time"],
                    "video_path": sample["video_path"],
                    "image_paths": sample["image_paths"],
                    "segment_count": sample["segment_count"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
