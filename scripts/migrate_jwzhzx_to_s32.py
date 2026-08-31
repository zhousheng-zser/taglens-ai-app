#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
临时脚本：将 MinIO bucket-taglens 中
  event_data/JWZHZX/{101,105,107,201}/…
的所有文件移动到
  event_data/S32/{101,105,107,201}/…

同时将文件名前缀 JWZHZX_ 改为 S32_，例如：
  JWZHZX_3513145734067130368.mp4 -> S32_3513145734067130368.mp4

每迁移完一个事件文件夹，立即更新 taglens_event.event_records 中匹配的路径。

用法：
  # 先跑 dry-run（默认）只输出不操作
  python scripts/migrate_jwzhzx_to_s32.py

  # 正式执行（默认 8 并发）
  python scripts/migrate_jwzhzx_to_s32.py --run

  # 只修复已迁移到 S32 但文件名仍是 JWZHZX_ 的对象
  python scripts/migrate_jwzhzx_to_s32.py --run --rename-only

  # 指定并发数
  python scripts/migrate_jwzhzx_to_s32.py --run --workers 16
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------- 设置 import 路径 ----------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

import pymysql
import pymysql.cursors
from minio import Minio
from minio.commonconfig import CopySource
from core.minio_storage_client import (
    MINIO_ACCESS_KEY,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)

# ---------- 常量 ----------
BUCKET = "bucket-taglens"
SRC_PROJECT = "JWZHZX"
DST_PROJECT = "S32"
DST_PROJECT_NAME = "S32申嘉湖"
EVENT_TYPES = ["101", "105", "107", "201"]  # 不包含 999
DEFAULT_WORKERS = 8

MYSQL_CFG: Dict = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_EVENT_DATABASE", "taglens_event"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

_print_lock = threading.Lock()
_stats_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def get_minio_client() -> Minio:
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def rename_basename(name: str) -> str:
    if name.startswith(f"{SRC_PROJECT}_"):
        return f"{DST_PROJECT}_{name[len(SRC_PROJECT) + 1:]}"
    return name


def transform_object_key(src_key: str) -> str:
    dst_key = src_key.replace(
        f"event_data/{SRC_PROJECT}/", f"event_data/{DST_PROJECT}/", 1
    )
    dirname, basename = os.path.split(dst_key)
    new_basename = rename_basename(basename)
    return f"{dirname}/{new_basename}" if dirname else new_basename


def transform_path_value(value: Optional[str]) -> str:
    if not value:
        return value or ""
    updated = value.replace(f"/{SRC_PROJECT}/", f"/{DST_PROJECT}/")
    dirname, basename = os.path.split(updated)
    new_basename = rename_basename(basename)
    return f"{dirname}/{new_basename}" if dirname else new_basename


def transform_json_paths(value: Optional[str]) -> str:
    if not value:
        return value or ""
    text = value.strip()
    if not text:
        return value
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return transform_path_value(value)
    if isinstance(parsed, list):
        return json.dumps(
            [transform_path_value(item) if isinstance(item, str) else item for item in parsed],
            ensure_ascii=False,
        )
    if isinstance(parsed, dict):
        return json.dumps(
            {
                key: transform_path_value(item) if isinstance(item, str) else item
                for key, item in parsed.items()
            },
            ensure_ascii=False,
        )
    return value


def src_to_dst_prefix(src_prefix: str) -> str:
    return src_prefix.replace(
        f"event_data/{SRC_PROJECT}/", f"event_data/{DST_PROJECT}/", 1
    )


def list_event_folders(client: Minio, project: str, event_type: str) -> List[str]:
    """返回 event_data/<project>/<type>/ 下的所有事件文件夹前缀。"""
    prefix = f"event_data/{project}/{event_type}/"
    months = list(client.list_objects(BUCKET, prefix=prefix, recursive=False))
    result: List[str] = []
    for month in months:
        if month.is_dir:
            event_dirs = list(
                client.list_objects(BUCKET, prefix=month.object_name, recursive=False)
            )
            for event_dir in event_dirs:
                result.append(event_dir.object_name)
        else:
            result.append(month.object_name)
    return result


def list_objects_under(client: Minio, prefix: str) -> List[str]:
    return [
        obj.object_name
        for obj in client.list_objects(BUCKET, prefix=prefix, recursive=True)
        if not obj.is_dir
    ]


def copy_and_delete(client: Minio, src_key: str, dst_key: str) -> None:
    if src_key == dst_key:
        return
    client.copy_object(BUCKET, dst_key, CopySource(BUCKET, src_key))
    client.remove_object(BUCKET, src_key)


def move_folder(client: Minio, src_prefix: str, dry_run: bool) -> Tuple[int, int, int]:
    """从 JWZHZX 移动到 S32 并重命名。返回 (moved, renamed, failed)。"""
    moved = 0
    renamed = 0
    failed = 0
    objects = list_objects_under(client, src_prefix)
    for src_key in objects:
        dst_key = transform_object_key(src_key)
        if dry_run:
            moved += 1
            if os.path.basename(src_key) != os.path.basename(dst_key):
                renamed += 1
            continue
        try:
            copy_and_delete(client, src_key, dst_key)
            moved += 1
            if os.path.basename(src_key) != os.path.basename(dst_key):
                renamed += 1
        except Exception as exc:
            log(f"  [ERROR] move {src_key} -> {dst_key}: {exc}")
            failed += 1
    return moved, renamed, failed


def rename_folder_in_s32(client: Minio, dst_prefix: str, dry_run: bool) -> Tuple[int, int, int]:
    """S32 目录内把 JWZHZX_ 文件名改为 S32_。返回 (moved, renamed, failed)。"""
    moved = 0
    renamed = 0
    failed = 0
    objects = list_objects_under(client, dst_prefix)
    for src_key in objects:
        basename = os.path.basename(src_key)
        if not basename.startswith(f"{SRC_PROJECT}_"):
            continue
        dst_key = transform_object_key(
            src_key.replace(f"event_data/{DST_PROJECT}/", f"event_data/{SRC_PROJECT}/", 1)
        )
        if dry_run:
            renamed += 1
            continue
        try:
            copy_and_delete(client, src_key, dst_key)
            renamed += 1
            moved += 1
        except Exception as exc:
            log(f"  [ERROR] rename {src_key} -> {dst_key}: {exc}")
            failed += 1
    return moved, renamed, failed


def update_db_for_folder(src_prefix: str, dry_run: bool) -> int:
    """按事件文件夹前缀更新 event_records 中匹配的路径。"""
    src_db_prefix = "/" + src_prefix.rstrip("/")
    dst_db_prefix = "/" + src_to_dst_prefix(src_prefix).rstrip("/")
    like_src = f"{src_db_prefix}%"
    like_dst_old_name = f"%/{SRC_PROJECT}_%"
    conn = pymysql.connect(**MYSQL_CFG)
    updated = 0
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT event_id, project_id, event_type_corrected,
                   video_path, segment_paths_json, image_paths
            FROM event_records
            WHERE video_path LIKE %s
               OR segment_paths_json LIKE %s
               OR image_paths LIKE %s
               OR video_path LIKE %s
               OR segment_paths_json LIKE %s
               OR image_paths LIKE %s
            """,
            (
                like_src,
                f"%{src_db_prefix}%",
                f"%{src_db_prefix}%",
                f"{dst_db_prefix}%",
                f"%{dst_db_prefix}%",
                f"%{dst_db_prefix}%",
            ),
        )
        rows = cur.fetchall()
        if not rows:
            return 0

        for row in rows:
            new_video = transform_path_value(row["video_path"])
            new_seg = transform_json_paths(row["segment_paths_json"])
            new_img = transform_json_paths(row["image_paths"])
            new_project_id = (
                DST_PROJECT if row["project_id"] == SRC_PROJECT else row["project_id"]
            )

            if dry_run:
                updated += 1
                continue

            cur.execute(
                """
                UPDATE event_records
                SET video_path = %s,
                    segment_paths_json = %s,
                    image_paths = %s,
                    project_id = %s,
                    project_name = %s
                WHERE event_id = %s
                  AND project_id = %s
                  AND event_type_corrected = %s
                """,
                (
                    new_video,
                    new_seg,
                    new_img,
                    new_project_id,
                    DST_PROJECT_NAME,
                    row["event_id"],
                    row["project_id"],
                    row["event_type_corrected"],
                ),
            )
            updated += cur.rowcount
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return updated


def update_manage_db_paths(dry_run: bool) -> int:
    """更新 taglens_manage 中的 event_task_assignments / event_review_records 项目引用。"""
    manage_cfg = dict(MYSQL_CFG)
    manage_cfg["database"] = os.getenv("MYSQL_MANAGE_DATABASE", "taglens_manage")
    conn = pymysql.connect(**manage_cfg)
    total = 0
    try:
        cur = conn.cursor()
        for table in ["event_task_assignments", "event_review_records"]:
            type_ph = ",".join(["%s"] * len(EVENT_TYPES))
            cur.execute(
                f"SELECT COUNT(*) c FROM {table} "
                f"WHERE project_id = %s AND event_type_code IN ({type_ph})",
                [SRC_PROJECT] + EVENT_TYPES,
            )
            cnt = cur.fetchone()["c"]
            if cnt == 0:
                continue
            if dry_run:
                log(f"  [dry-run manage] {table}: {cnt} 条 project_id JWZHZX -> S32")
                total += cnt
                continue
            cur.execute(
                f"UPDATE {table} SET project_id = %s "
                f"WHERE project_id = %s AND event_type_code IN ({type_ph})",
                [DST_PROJECT, SRC_PROJECT] + EVENT_TYPES,
            )
            total += cur.rowcount
            log(f"  [manage] {table}: 更新 {cur.rowcount} 条")
        conn.commit()
    finally:
        conn.close()
    return total


def process_one_folder(
    index: int,
    src_prefix: str,
    dry_run: bool,
    verbose: bool,
    rename_only: bool,
) -> Tuple[int, int, int, int, float]:
    """单个事件文件夹：移动/重命名 + DB 更新。"""
    name = src_prefix.rstrip("/").split("/")[-1]
    dst_prefix = src_to_dst_prefix(src_prefix)
    t0 = time.time()
    client = get_minio_client()

    moved = 0
    renamed = 0
    failed = 0

    if not rename_only:
        src_objects = list_objects_under(client, src_prefix)
        if src_objects:
            moved, renamed, failed = move_folder(client, src_prefix, dry_run)
        else:
            moved, renamed, failed = rename_folder_in_s32(client, dst_prefix, dry_run)
    else:
        moved, renamed, failed = rename_folder_in_s32(client, dst_prefix, dry_run)

    db_updated = 0
    if failed == 0 and (moved > 0 or renamed > 0):
        db_updated = update_db_for_folder(src_prefix, dry_run)
    elapsed = time.time() - t0

    if verbose or failed > 0 or db_updated > 0 or renamed > 0:
        log(
            f"  [{index}] {name} | 文件 {moved}, 重命名 {renamed}, 失败 {failed}, "
            f"DB {db_updated}, 耗时 {elapsed:.1f}s"
        )
    return moved, renamed, failed, db_updated, elapsed


def collect_all_folders(
    client: Minio, limit: int, rename_only: bool
) -> List[str]:
    folders: List[str] = []
    seen: set[str] = set()

    for event_type in EVENT_TYPES:
        if not rename_only:
            src_folders = list_event_folders(client, SRC_PROJECT, event_type)
            log(f"事件类型 {event_type}: JWZHZX 剩余 {len(src_folders)} 个事件文件夹")
            for folder in src_folders:
                if folder not in seen:
                    seen.add(folder)
                    folders.append(folder)
                    if limit and len(folders) >= limit:
                        return folders

        dst_folders = list_event_folders(client, DST_PROJECT, event_type)
        need_rename = 0
        for dst_folder in dst_folders:
            src_folder = dst_folder.replace(
                f"event_data/{DST_PROJECT}/", f"event_data/{SRC_PROJECT}/", 1
            )
            objects = list_objects_under(client, dst_folder)
            if not any(os.path.basename(key).startswith(f"{SRC_PROJECT}_") for key in objects):
                continue
            need_rename += 1
            if src_folder not in seen:
                seen.add(src_folder)
                folders.append(src_folder)
                if limit and len(folders) >= limit:
                    return folders
        log(f"事件类型 {event_type}: S32 待重命名 {need_rename} 个事件文件夹")

    return folders


def main() -> None:
    parser = argparse.ArgumentParser(
        description="迁移 MinIO JWZHZX/{101,105,107,201} -> S32 并更新 DB"
    )
    parser.add_argument("--run", action="store_true", help="真正执行（默认 dry-run）")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="只迁移前 N 个事件文件夹（0=不限制）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"并发线程数（默认 {DEFAULT_WORKERS}）",
    )
    parser.add_argument(
        "--rename-only",
        action="store_true",
        help="只处理已迁移到 S32 但文件名仍是 JWZHZX_ 的对象",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="打印每个事件文件夹的处理结果",
    )
    args = parser.parse_args()

    dry_run = not args.run
    limit = args.limit
    workers = max(1, args.workers)
    rename_only = args.rename_only
    verbose = args.verbose or bool(limit and limit <= 20)

    if dry_run:
        log("=== DRY-RUN 模式（不做任何修改，仅输出计划） ===")
    else:
        log("=== 正式执行模式 ===")
    log(f"并发 workers={workers}")
    if rename_only:
        log("模式: 仅重命名 S32 中 JWZHZX_ 文件")

    client = get_minio_client()
    t_start = time.time()
    log("\n--- 扫描事件文件夹 ---")
    folders = collect_all_folders(client, limit, rename_only)
    log(f"待处理总数: {len(folders)}")

    total_moved = 0
    total_renamed = 0
    total_failed = 0
    total_db_updated = 0
    done = 0

    log("\n--- 开始并发处理 ---")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                process_one_folder,
                idx + 1,
                folder,
                dry_run,
                verbose,
                rename_only,
            ): folder
            for idx, folder in enumerate(folders)
        }
        for future in as_completed(futures):
            moved, renamed, failed, db_updated, _ = future.result()
            with _stats_lock:
                total_moved += moved
                total_renamed += renamed
                total_failed += failed
                total_db_updated += db_updated
                done += 1
                if done % 100 == 0 or done == len(folders):
                    elapsed = time.time() - t_start
                    log(
                        f"进度 {done}/{len(folders)} | "
                        f"文件 {total_moved}, 重命名 {total_renamed}, 失败 {total_failed}, "
                        f"DB {total_db_updated} | 已耗时 {elapsed:.0f}s"
                    )

    elapsed = time.time() - t_start
    log(
        f"\n=== MinIO 汇总：处理 {total_moved} 个文件，重命名 {total_renamed} 个，"
        f"失败 {total_failed}，DB 更新 {total_db_updated} 条，总耗时 {elapsed:.1f}s ==="
    )

    log("\n--- 更新 manage DB ---")
    manage_updated = update_manage_db_paths(dry_run)
    log(f"manage DB 更新 {manage_updated} 条")

    log("\n全部完成 ✓")


if __name__ == "__main__":
    main()
