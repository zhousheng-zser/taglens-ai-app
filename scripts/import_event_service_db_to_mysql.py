#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临时脚本：将 data/db_tmp/event_service.db（SQLite）中的 event_records
导入 MySQL taglens_event.event_records。

导入前校验：
  1. MinIO 中 video_path 对应的视频对象必须存在（不存在则跳过）
  2. image_paths 中的图片逐个校验，只保留 MinIO 里真实存在的
  3. MySQL 中不存在 (event_id, project_id, event_type_corrected) 才插入
  4. 顺带扫描事件目录下 *_NNN.mp4 分段视频，补齐 segment_count / segment_paths_json

用法：
  # dry-run（只校验统计，不写库）
  backend/venv/bin/python scripts/import_event_service_db_to_mysql.py

  # 只测 2 条
  backend/venv/bin/python scripts/import_event_service_db_to_mysql.py --run --limit 2

  # 正式执行
  backend/venv/bin/python scripts/import_event_service_db_to_mysql.py --run --workers 16
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from core.event_database import get_event_db_connection  # noqa: E402
from core.minio_storage_client import get_storage_client  # noqa: E402

DEFAULT_SQLITE = Path(__file__).resolve().parent.parent / "data/db_tmp/event_service.db"
BUCKET = "bucket-taglens"
SEGMENT_RE = re.compile(r"_\d{3}\.mp4$", re.IGNORECASE)

SQLITE_COLUMNS = [
    "event_id", "project_id", "project_name", "camera_name", "mvp_camera_id",
    "event_type", "start_time", "video_url", "mvp_ip", "task_id", "source_id",
    "source_name", "event_name", "event_type_corrected", "event_name_corrected",
    "event_level", "event_position", "end_time", "detect_time", "vehicle_plate",
    "vehicle_plate_color", "vehicle_confidence", "vehicle_type", "vehicle_category",
    "vehicle_color", "vehicle_speed", "lane_number", "process_status",
    "event_confidence", "scene_match", "scene_match_degree", "analysis_server",
    "management_server", "debugging_info_json", "image_paths", "video_path",
    "download_source", "status", "created_at",
]

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
    value = str(path or "").strip()
    if not value:
        return ""
    if value.startswith("bucket-taglens/event_data/"):
        return "/event_data/" + value[len("bucket-taglens/event_data/"):]
    if value.startswith("/bucket-taglens/event_data/"):
        return "/event_data/" + value[len("/bucket-taglens/event_data/"):]
    if value.startswith("event_data/"):
        return "/" + value
    return value


def db_path_to_object(db_path: str) -> str:
    return str(db_path or "").strip().lstrip("/")


def read_sqlite_rows(db_path: Path, status_filter: str) -> Tuple[List[Dict], int]:
    """尽量多读；遇到坏页（database disk image is malformed）时停止并返回已读部分。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cols = ", ".join(SQLITE_COLUMNS)
    cur.execute(f"SELECT {cols} FROM event_records")
    rows: List[Dict] = []
    skipped_status = 0
    corrupt = False
    while True:
        try:
            row = cur.fetchone()
        except sqlite3.DatabaseError as exc:
            log(f"[警告] SQLite 读到坏页，提前结束: {exc}（已读 {len(rows)} 条可用）")
            corrupt = True
            break
        if row is None:
            break
        d = {k: row[k] for k in SQLITE_COLUMNS}
        if status_filter != "all" and str(d.get("status") or "") != status_filter:
            skipped_status += 1
            continue
        rows.append(d)
    conn.close()
    if corrupt:
        log("[警告] 该文件已损坏，建议重新上传完整的 event_service.db 后重跑本脚本")
    return rows, skipped_status


def load_existing_keys(project_ids: Set[str]) -> Set[Tuple[str, str, str]]:
    if not project_ids:
        return set()
    keys: Set[Tuple[str, str, str]] = set()
    with get_event_db_connection() as conn:
        cur = conn.cursor()
        placeholders = ", ".join(["%s"] * len(project_ids))
        cur.execute(
            f"""
            SELECT event_id, project_id, event_type_corrected
            FROM event_records
            WHERE project_id IN ({placeholders})
            """,
            tuple(project_ids),
        )
        for r in cur.fetchall():
            keys.add((str(r["event_id"]), str(r["project_id"]), str(r["event_type_corrected"] or "")))
    return keys


def verify_and_enrich(row: Dict) -> Tuple[str, Optional[Dict], Optional[str]]:
    """
    校验 MinIO 媒体并补充分段信息。
    返回 (status, enriched_row_or_none, error)
    status: prepared / skip_no_video_path / skip_video_missing
    """
    client = get_storage_client(skip_bucket_check=True)

    video_db_path = normalize_media_path(row.get("video_path") or "")
    if not video_db_path:
        return "skip_no_video_path", None, "video_path 为空"
    video_object = db_path_to_object(video_db_path)

    folder_prefix = video_object.rsplit("/", 1)[0] + "/"
    objects = {
        obj.object_name
        for obj in client.client.list_objects(BUCKET, prefix=folder_prefix, recursive=True)
        if not obj.is_dir
    }

    if video_object not in objects:
        return "skip_video_missing", None, f"MinIO 缺视频: {video_object}"

    # 只保留 MinIO 中真实存在的图片
    image_db_paths: List[str] = []
    missing_images: List[str] = []
    for raw in str(row.get("image_paths") or "").split(","):
        p = normalize_media_path(raw)
        if not p:
            continue
        if db_path_to_object(p) in objects:
            image_db_paths.append(p)
        else:
            missing_images.append(p)

    # 目录内分段视频 *_NNN.mp4（排除主视频自身）
    segment_objects = sorted(
        o for o in objects
        if SEGMENT_RE.search(o) and o != video_object
    )
    segment_db_paths = [normalize_media_path(o) for o in segment_objects]

    enriched = dict(row)
    enriched["video_path"] = video_db_path
    enriched["image_paths"] = ",".join(image_db_paths)
    enriched["segment_count"] = len(segment_db_paths)
    enriched["segment_paths_json"] = json.dumps(segment_db_paths, ensure_ascii=False)
    enriched["missing_images"] = len(missing_images)
    return "prepared", enriched, None


def make_row(item: Dict) -> tuple:
    return tuple(
        [item.get(col) for col in SQLITE_COLUMNS]
        + [
            item.get("segment_count", 0),
            item.get("segment_paths_json", "[]"),
            "[]",
            "[]",
        ]
    )


def insert_rows(items: List[Dict], dry_run: bool) -> Tuple[int, int]:
    """逐条提交，避免整批事务因死锁全部回滚；死锁最多重试 3 次。"""
    if not items or dry_run:
        return len(items), 0
    inserted = failed = skipped_dup = 0
    with get_event_db_connection() as conn:
        cur = conn.cursor()
        for item in items:
            row = make_row(item)
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
                    # 主键冲突：视为已存在，跳过
                    if "1062" in msg or "Duplicate entry" in msg:
                        status = "dup"
                        break
                    # 死锁：短暂等待后重试
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
                    log(
                        f"  [DB FAIL] {item.get('event_id')}/"
                        f"{item.get('event_type_corrected')}: {last_exc}"
                    )
    if skipped_dup:
        log(f"写入时主键冲突跳过: {skipped_dup}")
    return inserted, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 event_service.db 到 MySQL event_records")
    parser.add_argument("--db", type=Path, default=DEFAULT_SQLITE, help="SQLite 源库路径")
    parser.add_argument("--run", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条新记录")
    parser.add_argument("--workers", type=int, default=8, help="MinIO 校验并发数")
    parser.add_argument(
        "--status", default="completed",
        help="只导入该 status 的记录（默认 completed，传 all 表示不过滤）",
    )
    parser.add_argument("--verbose", action="store_true", help="打印每条跳过原因")
    args = parser.parse_args()

    dry_run = not args.run
    log("=== DRY-RUN 模式（不写库） ===" if dry_run else "=== 正式执行模式 ===")
    log(f"源库: {args.db}")

    if not args.db.exists():
        log(f"[错误] 源库不存在: {args.db}")
        sys.exit(1)

    t0 = time.time()
    log("\n--- 读取 SQLite ---")
    rows, skipped_status = read_sqlite_rows(args.db, args.status)
    log(f"符合 status={args.status} 的记录: {len(rows)}（按 status 过滤掉 {skipped_status}）")

    project_ids = {str(r.get("project_id") or "") for r in rows if r.get("project_id")}
    log(f"涉及项目: {sorted(project_ids)}")

    existing = load_existing_keys(project_ids)
    log(f"MySQL 中这些项目已有记录: {len(existing)}")

    new_rows: List[Dict] = []
    skip_exists = 0
    skip_bad_key = 0
    seen: Set[Tuple[str, str, str]] = set()
    for r in rows:
        key = (
            str(r.get("event_id") or ""),
            str(r.get("project_id") or ""),
            str(r.get("event_type_corrected") or ""),
        )
        if not key[0] or not key[1] or not key[2]:
            skip_bad_key += 1
            continue
        if key in existing or key in seen:
            skip_exists += 1
            continue
        seen.add(key)
        new_rows.append(r)
    log(f"MySQL 中不存在的新记录: {len(new_rows)}（已存在/重复跳过 {skip_exists}，主键字段缺失 {skip_bad_key}）")

    if args.limit:
        new_rows = new_rows[: args.limit]
        log(f"--limit {args.limit}: 只处理前 {len(new_rows)} 条")

    log("\n--- 校验 MinIO 媒体 ---")
    prepared: List[Dict] = []
    stats = {"prepared": 0, "skip_no_video_path": 0, "skip_video_missing": 0, "error": 0}
    missing_image_total = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(verify_and_enrich, r): r for r in new_rows}
        done = 0
        for future in as_completed(futures):
            src = futures[future]
            done += 1
            try:
                status, item, err = future.result()
            except Exception as exc:
                status, item, err = "error", None, str(exc)
            stats[status] = stats.get(status, 0) + 1
            if status == "prepared" and item:
                prepared.append(item)
                missing_image_total += item.get("missing_images", 0)
            elif args.verbose:
                log(f"  [SKIP] {src.get('event_id')}: {err}")
            if done % 200 == 0 or done == len(new_rows):
                log(f"进度 {done}/{len(new_rows)} | 可入库 {len(prepared)}")

    log("\n--- 写入 MySQL event_records ---")
    inserted, failed = insert_rows(prepared, dry_run)

    elapsed = time.time() - t0
    log(
        f"\n=== 完成 ===\n"
        f"SQLite 记录 {len(rows)} | 新记录 {len(new_rows)} | 可入库 {len(prepared)}\n"
        f"写入 {'(dry-run) ' if dry_run else ''}{inserted} | DB失败 {failed}\n"
        f"跳过: 已存在 {skip_exists} | 视频路径为空 {stats['skip_no_video_path']} | "
        f"MinIO缺视频 {stats['skip_video_missing']} | 校验异常 {stats.get('error', 0)}\n"
        f"图片缺失(条目内已剔除): {missing_image_total} 张\n"
        f"耗时 {elapsed:.1f}s"
    )
    if prepared:
        sample = prepared[0]
        log(
            "示例: "
            + json.dumps(
                {
                    "event_id": sample.get("event_id"),
                    "project_id": sample.get("project_id"),
                    "event_type_corrected": sample.get("event_type_corrected"),
                    "start_time": sample.get("start_time"),
                    "video_path": sample.get("video_path"),
                    "image_paths": sample.get("image_paths"),
                    "segment_count": sample.get("segment_count"),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
