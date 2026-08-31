#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临时脚本：扫描 MinIO event_data/OTHER/ 并导入 taglens_event.event_records。

参考 JWZHZX（交委指挥中心）的字段逻辑：
  - project_id=OTHER, project_name=其它
  - event_name/event_name_corrected 取 event_type_dict 名称
  - debugging_info_json="无事件调试信息", download_source="skipped", status="completed"
  - 分段字段按分段数量填充（描述空串 / 状态"待定" / 问答空列表）

目录示例：
  event_data/OTHER/102/202303/1638806404330463242_23_15_34_26_13/OTHER_1638806404330463242.mp4
  - mvp_camera_id: 文件夹名最后一段（如 13）
  - mvp_ip: 同目录 .config 文件 DETECT_CHANNEL_LIST[0].input_video_param.mvp_addr

用法：
  # dry-run
  backend/venv/bin/python scripts/import_other_to_event_records.py

  # 只测 2 条
  backend/venv/bin/python scripts/import_other_to_event_records.py --run --limit 2

  # 正式执行
  backend/venv/bin/python scripts/import_other_to_event_records.py --run --workers 16
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
from typing import Dict, List, Optional, Set, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from core.event_database import get_event_db_connection  # noqa: E402
from core.minio_storage_client import get_storage_client  # noqa: E402

BUCKET = "bucket-taglens"
PROJECT_ID = "OTHER"
PROJECT_NAME = "其它"
DEFAULT_WORKERS = 8
SEGMENT_RE = re.compile(r"_\d{3}\.mp4$", re.IGNORECASE)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}

EVENT_TYPE_NAMES = {
    "101": "异常停车",
    "102": "单车事故",
    "103": "多车事故",
    "104": "行人闯入",
    "105": "抛洒物",
    "106": "二轮车闯入",
    "107": "占道施工",
    "201": "交通拥堵",
    "999": "其它",
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
    segment_count, segment_paths_json, segment_descriptions_json,
    segment_statuses_json, questions_answers_list,
    segment_review_descriptions_json, segment_descriptions_en_json,
    accident_questions_answers_json
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s
)
"""

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def normalize_media_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    if value.startswith("event_data/"):
        return "/" + value
    return value


def build_start_time(yyyymm: str, dd: str, hh: str, mm: str, ss: str) -> str:
    return datetime(
        int(yyyymm[:4]), int(yyyymm[4:6]), int(dd), int(hh), int(mm), int(ss)
    ).strftime("%Y-%m-%d %H:%M:%S.000000")


def parse_folder_meta(folder_prefix: str) -> Optional[Dict[str, str]]:
    """
    folder_prefix 例:
      event_data/OTHER/102/202303/1638806404330463242_23_15_34_26_13/
    """
    cleaned = folder_prefix.strip().strip("/")
    parts = cleaned.split("/")
    if len(parts) < 5 or parts[0] != "event_data" or parts[1] != PROJECT_ID:
        return None
    event_type, yyyymm, tail = parts[2], parts[3], parts[4]
    tokens = tail.split("_")
    if len(tokens) < 5:
        return None
    event_id = tokens[0]
    dd, hh, mm, ss = tokens[1], tokens[2], tokens[3], tokens[4]
    # 文件夹名最后一段为相机号；个别目录缺少该段（只有 5 段）则留空
    camera_id = tokens[-1] if len(tokens) >= 6 else ""
    try:
        start_time = build_start_time(yyyymm, dd, hh, mm, ss)
    except Exception:
        start_time = ""
    return {
        "event_id": event_id,
        "event_type": event_type,
        "yyyymm": yyyymm,
        "mvp_camera_id": camera_id,
        "start_time": start_time,
        "folder_prefix": cleaned + "/",
    }


def parse_mvp_ip(config_bytes: bytes) -> str:
    try:
        data = json.loads(config_bytes.decode("utf-8", "replace"))
        channels = data.get("DETECT_CHANNEL_LIST") or []
        if channels:
            return str(
                (channels[0].get("input_video_param") or {}).get("mvp_addr") or ""
            )
    except Exception:
        pass
    return ""


def pick_main_and_segments(video_keys: List[str]) -> Tuple[Optional[str], List[str]]:
    mains = [k for k in video_keys if not SEGMENT_RE.search(k)]
    segs = sorted(k for k in video_keys if SEGMENT_RE.search(k))
    if mains:
        mains.sort(key=lambda k: (len(Path(k).name), k))
        return mains[0], segs
    if segs:
        return segs[0], segs[1:]
    return None, []


def list_event_folders(limit: int = 0) -> List[str]:
    client = get_storage_client(skip_bucket_check=True)
    minio = client.client
    folders: List[str] = []
    type_dirs = list(
        minio.list_objects(BUCKET, prefix=f"event_data/{PROJECT_ID}/", recursive=False)
    )
    for type_dir in type_dirs:
        if not type_dir.is_dir:
            continue
        type_count = 0
        for month in minio.list_objects(BUCKET, prefix=type_dir.object_name, recursive=False):
            if not month.is_dir:
                continue
            for event_dir in minio.list_objects(BUCKET, prefix=month.object_name, recursive=False):
                if event_dir.is_dir:
                    folders.append(event_dir.object_name)
                    type_count += 1
                if limit and len(folders) >= limit:
                    log(f"已达 --limit {limit}，停止扫描")
                    return folders
        log(f"事件类型目录 {type_dir.object_name}: {type_count} 个事件")
    return folders


def extract_first_frame(presigned_url: str, output_path: str) -> bool:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", presigned_url, "-frames:v", "1", "-q:v", "2", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return (
        result.returncode == 0
        and os.path.exists(output_path)
        and os.path.getsize(output_path) > 0
    )


def ensure_cover(video_object: str, folder_prefix: str, dry_run: bool) -> Tuple[str, str]:
    """目录无 image_big.jpg 时用 ffmpeg 抽首帧补一张。"""
    image_object = folder_prefix.rstrip("/") + "/image_big.jpg"
    image_db_path = normalize_media_path(image_object)
    client = get_storage_client(skip_bucket_check=True)
    if dry_run:
        return image_db_path, "dry-run"
    url = client.client.presigned_get_object(
        client.bucket, video_object, expires=timedelta(hours=1),
    )
    with tempfile.TemporaryDirectory(prefix="other_cover_") as td:
        jpg_path = os.path.join(td, "image_big.jpg")
        if not extract_first_frame(url, jpg_path):
            return image_db_path, "fail"
        client.upload_file(jpg_path, image_object, content_type="image/jpeg")
    return image_db_path, "ok"


def load_existing_keys() -> Set[Tuple[str, str, str]]:
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


def process_one(
    folder_prefix: str,
    dry_run: bool,
    existing: Set[Tuple[str, str, str]],
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

    client = get_storage_client(skip_bucket_check=True)
    images: List[str] = []
    videos: List[str] = []
    config_key: Optional[str] = None
    for obj in client.client.list_objects(BUCKET, prefix=folder_prefix, recursive=True):
        if obj.is_dir:
            continue
        suffix = Path(obj.object_name).suffix.lower()
        if suffix in IMAGE_EXTS:
            images.append(obj.object_name)
        elif suffix in VIDEO_EXTS:
            videos.append(obj.object_name)
        elif suffix == ".config":
            config_key = obj.object_name

    main_video, segments = pick_main_and_segments(sorted(videos))
    if not main_video:
        return "skip_no_video", folder_prefix, None, "目录无视频"

    # mvp_ip 从 .config 解析
    mvp_ip = ""
    if config_key:
        try:
            resp = client.client.get_object(BUCKET, config_key)
            mvp_ip = parse_mvp_ip(resp.read())
            resp.close()
        except Exception:
            mvp_ip = ""

    cover = next((p for p in sorted(images) if p.endswith("/image_big.jpg")), None)
    if cover:
        image_paths = normalize_media_path(cover)
        cover_status = "exists"
    else:
        image_paths, cover_status = ensure_cover(main_video, folder_prefix, dry_run)
        if cover_status == "fail":
            return "fail", folder_prefix, None, "封面抽帧失败"

    segment_db_paths = [normalize_media_path(s) for s in segments]
    item = {
        **meta,
        "mvp_ip": mvp_ip,
        "video_path": normalize_media_path(main_video),
        "image_paths": image_paths,
        "segment_count": len(segment_db_paths),
        "segment_paths_json": json.dumps(segment_db_paths, ensure_ascii=False),
        "cover_status": cover_status,
    }
    return "prepared", folder_prefix, item, None


def make_row(item: Dict, created_at: str) -> tuple:
    event_name = EVENT_TYPE_NAMES.get(item["event_type"], item["event_type"])
    n = int(item.get("segment_count", 0))
    return (
        item["event_id"],
        PROJECT_ID,
        PROJECT_NAME,
        "",  # camera_name
        item["mvp_camera_id"],
        "",  # event_type（原始，JWZHZX 逻辑为空）
        item["start_time"],
        "",  # video_url
        item.get("mvp_ip", ""),
        "",  # task_id
        "",  # source_id
        "",  # source_name
        event_name,
        item["event_type"],  # event_type_corrected
        event_name,
        "1",  # event_level
        "",  # event_position
        "",  # end_time
        "",  # detect_time
        "",  # vehicle_plate
        "",  # vehicle_plate_color
        "",  # vehicle_confidence
        "",  # vehicle_type
        "",  # vehicle_category
        "",  # vehicle_color
        "",  # vehicle_speed
        "",  # lane_number
        "",  # process_status
        "",  # event_confidence
        "",  # scene_match
        "",  # scene_match_degree
        "",  # analysis_server
        "",  # management_server
        "无事件调试信息",
        item.get("image_paths", ""),
        item["video_path"],
        "skipped",
        "completed",
        created_at,
        n,
        item.get("segment_paths_json", "[]"),
        json.dumps([""] * n, ensure_ascii=False),
        json.dumps(["待定"] * n, ensure_ascii=False),
        json.dumps([[] for _ in range(n)], ensure_ascii=False),
        json.dumps([""] * n, ensure_ascii=False),
        json.dumps([""] * n, ensure_ascii=False),
        "[]",
    )


def insert_rows(items: List[Dict], created_at: str, dry_run: bool) -> Tuple[int, int]:
    """逐条提交；主键冲突跳过，死锁重试。"""
    if not items or dry_run:
        return len(items), 0
    inserted = failed = skipped_dup = 0
    with get_event_db_connection() as conn:
        cur = conn.cursor()
        for item in items:
            row = make_row(item, created_at)
            status = "fail"
            last_exc: Optional[BaseException] = None
            for attempt in range(3):
                try:
                    cur.execute(INSERT_SQL, row)
                    conn.commit()
                    status = "ok"
                    break
                except Exception as exc:
                    last_exc = exc
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    msg = str(exc)
                    if "1062" in msg or "Duplicate entry" in msg:
                        status = "dup"
                        break
                    if "1213" in msg or "Deadlock" in msg:
                        time.sleep(0.2 * (attempt + 1))
                        continue
                    break
            if status == "ok":
                inserted += 1
            elif status == "dup":
                skipped_dup += 1
            else:
                failed += 1
                if failed <= 10:
                    log(f"  [DB FAIL] {item['event_id']}/{item['event_type']}: {last_exc}")
    if skipped_dup:
        log(f"写入时主键冲突跳过: {skipped_dup}")
    return inserted, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 OTHER MinIO 事件到 event_records")
    parser.add_argument("--run", action="store_true", help="真正执行（默认 dry-run）")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个事件目录")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="并发数")
    parser.add_argument("--verbose", action="store_true", help="打印每条处理结果")
    args = parser.parse_args()

    dry_run = not args.run
    workers = max(1, args.workers)
    verbose = args.verbose or bool(args.limit and args.limit <= 20)

    log("=== DRY-RUN 模式（不写 MinIO/DB） ===" if dry_run else "=== 正式执行模式 ===")
    log(f"workers={workers}")

    t0 = time.time()
    log("\n--- 扫描 MinIO ---")
    folders = list_event_folders(limit=args.limit)
    log(f"待处理目录: {len(folders)}")

    existing = load_existing_keys()
    log(f"DB 已有 OTHER 记录: {len(existing)}")

    prepared: List[Dict] = []
    stats = {
        "prepared": 0, "skip_exists": 0, "skip_no_video": 0, "fail": 0,
        "cover_exists": 0, "cover_ok": 0, "no_mvp_ip": 0,
    }

    log("\n--- 解析目录 / 读取 config ---")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(process_one, folder, dry_run, existing): folder
            for folder in folders
        }
        done = 0
        for future in as_completed(futures):
            status, folder, item, err = future.result()
            done += 1
            stats[status] = stats.get(status, 0) + 1
            if status == "prepared" and item:
                prepared.append(item)
                if item.get("cover_status") == "exists":
                    stats["cover_exists"] += 1
                elif item.get("cover_status") == "ok":
                    stats["cover_ok"] += 1
                if not item.get("mvp_ip"):
                    stats["no_mvp_ip"] += 1
                if verbose:
                    log(
                        f"  [{done}] {item['event_type']}/{item['event_id']} "
                        f"camera={item['mvp_camera_id']} ip={item.get('mvp_ip') or '-'} "
                        f"segs={item['segment_count']} cover={item['cover_status']}"
                    )
            elif status == "fail" and verbose:
                log(f"  [{done}] FAIL {folder}: {err}")
            if done % 50 == 0 or done == len(folders):
                log(
                    f"进度 {done}/{len(folders)} | 可入库 {len(prepared)} | "
                    f"已存在跳过 {stats['skip_exists']} | 失败 {stats['fail']}"
                )

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    log("\n--- 写入 event_records ---")
    inserted, failed = insert_rows(prepared, created_at, dry_run)

    elapsed = time.time() - t0
    log(
        f"\n=== 完成 ===\n"
        f"扫描 {len(folders)} | 可入库 {len(prepared)} | "
        f"写入 {'(dry-run) ' if dry_run else ''}{inserted} | DB失败 {failed}\n"
        f"已存在跳过 {stats['skip_exists']} | 无视频 {stats['skip_no_video']} | "
        f"处理失败 {stats['fail']}\n"
        f"封面: 已有 {stats['cover_exists']} | 新生成 {stats['cover_ok']} | "
        f"缺 mvp_ip: {stats['no_mvp_ip']}\n"
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
                    "mvp_ip": sample.get("mvp_ip"),
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
