"""
将 event_data_tree.txt 逐行解析并导入到 event.db 的 event_records 表。

输入文件每行示例：
{"folder": "/event_data/WHJM-9096/101/202512/1995..._01_05_16_49_13/", "images": [...], "videos": [...]}
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple


DEFAULT_INPUT = Path("/opt/Traffic-LLM/zser/taglens-ai-app/event_data_tree.txt")
DEFAULT_DB = Path("/opt/Traffic-LLM/zser/taglens-ai-app/data/event.db")
DEFAULT_BATCH_SIZE = 1000


INSERT_SQL = """
INSERT INTO event_records (
    event_id,
    project_id,
    project_name,
    camera_name,
    mvp_camera_id,
    event_type,
    start_time,
    video_url,
    mvp_ip,
    task_id,
    source_id,
    source_name,
    event_name,
    event_type_corrected,
    event_name_corrected,
    event_level,
    event_position,
    end_time,
    detect_time,
    vehicle_plate,
    vehicle_plate_color,
    vehicle_confidence,
    vehicle_type,
    vehicle_category,
    vehicle_color,
    vehicle_speed,
    lane_number,
    process_status,
    event_confidence,
    scene_match,
    scene_match_degree,
    analysis_server,
    management_server,
    debugging_info_json,
    image_paths,
    video_path,
    download_source,
    status,
    created_at
) VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
)
"""


@dataclass
class Counters:
    total_lines: int = 0
    parsed_ok: int = 0
    inserted: int = 0
    duplicate_skipped: int = 0
    failed: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入 event_data_tree.txt 到 event_records")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="输入文件路径")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="批量提交大小")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 行（0 表示不限制）")
    return parser.parse_args()


def load_project_dict(conn: sqlite3.Connection) -> Dict[str, str]:
    cursor = conn.cursor()
    cursor.execute("SELECT project_id, project_name FROM event_project_dict")
    return {row[0]: row[1] for row in cursor.fetchall()}


def load_event_type_dict(conn: sqlite3.Connection) -> Dict[str, str]:
    cursor = conn.cursor()
    cursor.execute("SELECT event_type_code, event_type_name FROM event_type_dict")
    return {row[0]: row[1] for row in cursor.fetchall()}


def split_tail(folder: str) -> Tuple[str, str, str, str, str, str, str]:
    cleaned = folder.strip().strip("/")
    tail = cleaned.split("/")[-1]
    event_id, dd, hh, mm, ss, camera_id = tail.split("_")
    return event_id, dd, hh, mm, ss, camera_id, tail


def parse_folder_parts(folder: str) -> Tuple[str, str, str]:
    cleaned = folder.strip().strip("/")
    parts = cleaned.split("/")
    if len(parts) == 5 and parts[0] == "event_data":
        return parts[1], parts[2], parts[3]
    if len(parts) == 6 and parts[0] == "bucket-taglens" and parts[1] == "event_data":
        return parts[2], parts[3], parts[4]
    raise ValueError(f"folder 结构不符合预期: {folder}")


def build_start_time(yyyymm: str, dd: str, hh: str, mm: str, ss: str) -> str:
    year = int(yyyymm[:4])
    month = int(yyyymm[4:6])
    day = int(dd)
    hour = int(hh)
    minute = int(mm)
    second = int(ss)
    dt = datetime(year, month, day, hour, minute, second)
    return dt.strftime("%Y-%m-%d %H:%M:%S.000000")


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


def make_row(
    record: dict,
    project_dict: Dict[str, str],
    event_type_dict: Dict[str, str],
    created_at: str,
) -> Tuple[str, ...]:
    folder = record.get("folder", "")
    images = record.get("images", [])
    videos = record.get("videos", [])

    if not isinstance(folder, str):
        raise ValueError("folder 必须是字符串")
    if not isinstance(images, list) or not isinstance(videos, list):
        raise ValueError("images/videos 必须是数组")

    project_id, event_type_code, yyyymm = parse_folder_parts(folder)
    event_id, dd, hh, mm, ss, camera_id, _ = split_tail(folder)

    start_time = build_start_time(yyyymm, dd, hh, mm, ss)
    project_name = project_dict.get(project_id, "")
    event_name = event_type_dict.get(event_type_code, "")
    normalized_images = [
        normalize_media_path(str(x)) for x in images if isinstance(x, str) and str(x).strip()
    ]
    image_paths = ",".join(normalized_images)
    video_path = ""
    if videos and isinstance(videos[0], str):
        video_path = normalize_media_path(videos[0])

    return (
        event_id,  # event_id
        project_id,  # project_id
        project_name,  # project_name
        "",  # camera_name
        camera_id,  # mvp_camera_id
        "",  # event_type
        start_time,  # start_time
        "",  # video_url
        "",  # mvp_ip
        "",  # task_id
        "",  # source_id
        "",  # source_name
        event_name,  # event_name
        event_type_code,  # event_type_corrected
        event_name,  # event_name_corrected
        "1",  # event_level
        "",  # event_position
        "",  # end_time
        start_time,  # detect_time
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
        "无事件调试信息",  # debugging_info_json
        image_paths,  # image_paths
        video_path,  # video_path
        "skipped",  # download_source
        "completed",  # status
        created_at,  # created_at
    )


def batched_insert(
    conn: sqlite3.Connection,
    rows: List[Tuple[str, ...]],
) -> Tuple[int, int]:
    inserted = 0
    failed = 0
    if not rows:
        return inserted, failed
    cursor = conn.cursor()
    try:
        cursor.executemany(INSERT_SQL, rows)
        conn.commit()
        inserted = len(rows)
    except sqlite3.IntegrityError:
        conn.rollback()
        for row in rows:
            try:
                cursor.execute(INSERT_SQL, row)
                inserted += 1
            except sqlite3.IntegrityError:
                failed += 1
        conn.commit()
    return inserted, failed


def load_existing_keys(conn: sqlite3.Connection) -> set[Tuple[str, str, str]]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT event_id, project_id, event_type_corrected
        FROM event_records
        """
    )
    rows = cursor.fetchall()
    return {
        (str(row[0]), str(row[1]), str(row[2] or ""))
        for row in rows
    }


def import_file(
    input_path: Path,
    db_path: Path,
    batch_size: int,
    limit: int,
) -> Counters:
    counters = Counters()
    if batch_size <= 0:
        raise ValueError("batch_size 必须大于 0")
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")
    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    project_dict = load_project_dict(conn)
    event_type_dict = load_event_type_dict(conn)
    existing_keys = load_existing_keys(conn)

    pending_rows: List[Tuple[str, ...]] = []
    pending_keys: set[Tuple[str, str, str]] = set()

    with input_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if limit > 0 and counters.total_lines >= limit:
                break

            counters.total_lines += 1
            text = line.strip()
            if not text:
                counters.failed += 1
                continue

            try:
                obj = json.loads(text)
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                row = make_row(obj, project_dict, event_type_dict, created_at)
                dedup_key = (str(row[0]), str(row[1]), str(row[13]))
                if dedup_key in existing_keys or dedup_key in pending_keys:
                    counters.duplicate_skipped += 1
                    continue
                pending_rows.append(row)
                pending_keys.add(dedup_key)
                counters.parsed_ok += 1
            except Exception as exc:
                counters.failed += 1
                if counters.failed <= 10:
                    print(f"[WARN] 第{line_no}行解析失败: {exc}")
                continue

            if len(pending_rows) >= batch_size:
                inserted_now, failed_now = batched_insert(conn, pending_rows)
                counters.inserted += inserted_now
                counters.failed += failed_now
                for row in pending_rows:
                    dedup_key = (str(row[0]), str(row[1]), str(row[13]))
                    existing_keys.add(dedup_key)
                pending_rows = []
                pending_keys = set()

    if pending_rows:
        inserted_now, failed_now = batched_insert(conn, pending_rows)
        counters.inserted += inserted_now
        counters.failed += failed_now

    conn.close()
    return counters


def main() -> None:
    args = parse_args()
    stats = import_file(
        input_path=args.input,
        db_path=args.db,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    print("=" * 60)
    print(f"输入总行数: {stats.total_lines}")
    print(f"解析成功: {stats.parsed_ok}")
    print(f"插入成功: {stats.inserted}")
    print(f"重复跳过: {stats.duplicate_skipped}")
    print(f"解析失败: {stats.failed}")
    print("=" * 60)


if __name__ == "__main__":
    main()
