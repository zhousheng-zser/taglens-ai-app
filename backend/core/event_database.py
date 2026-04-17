# -*- coding: utf-8 -*-
"""
事件数据库模块 - 使用 SQLite 存储事件检索数据
"""
import json
import os
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EVENT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "event.db"
BACKUP_DIR = EVENT_DB_PATH.parent / "backup"
BACKUP_KEEP_DAYS = int(os.getenv("DB_BACKUP_KEEP_DAYS", "7"))
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "192.168.1.117:9000")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "bucket-taglens")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
_event_backup_checked = False
_event_dict_cache: Dict[str, List[Dict[str, str]]] = {
    "projectOptions": [],
    "eventTypeOptions": [],
}

STANDARD_PROJECT_OPTIONS: List[Tuple[str, str]] = [
    ("SPSQ-7602", "松浦三桥"),
    ("GYPK-8950", "高逸路-平可行"),
    ("NXCJ-8955", "南翔-长江智能"),
    ("LC3Z-8958", "两场三站"),
    ("PKLH", "平可行林海公路市管公路事件平台"),
    ("DKSG", "电科市管公路"),
    ("PKGX", "平可行干线公路&平可行快速路"),
    ("REID-8966", "REID客流项目"),
    ("GYDK-8972", "高逸路-电科"),
    ("YXL-8972", "逸仙路"),
    ("S4HJ-8974", "S4沪金流量"),
    ("S6HX-8978", "S6沪翔高速"),
    ("YDL-8983", "银都路"),
    ("CJSG", "长江智能市管公路"),
    ("BHTD-8994", "北横通道"),
    ("BHDJ-8996", "北横电警卡口"),
    ("G60-9001", "G60事件"),
    ("YJAB-9022", "沿江AB段交调"),
    ("CXDT-9034", "长兴岛停车"),
    ("S2HL-9046", "S2沪芦"),
    ("HQLK-9047", "虹桥客流"),
    ("TJLD-9048", "同济路交调"),
    ("KSL3-W9054", "快速路三期"),
    ("MPDT-9058", "闵浦电梯"),
    ("JDHD-9061", "嘉定海致"),
    ("S26-9063", "S26项目"),
    ("HYGL-9065", "沪宜公路"),
    ("G60FW-9079", "G60服务区"),
    ("JXDL-9088", "锦绣东路"),
    ("WSWW-9089", "外四外五"),
    ("WHJM-9096", "外环嘉闵"),
]

STANDARD_EVENT_TYPE_OPTIONS: List[Tuple[str, str]] = [
    ("101", "异常停车"),
    ("102", "单车事故"),
    ("103", "多车事故"),
    ("104", "行人闯入"),
    ("105", "抛洒物"),
    ("106", "二轮车闯入"),
    ("107", "占道施工"),
    ("201", "交通拥堵"),
    ("999", "其它"),
]


def _backup_event_db_if_needed() -> None:
    """按天备份事件数据库，并清理过期备份。"""
    global _event_backup_checked
    if _event_backup_checked:
        return
    _event_backup_checked = True

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        backup_path = BACKUP_DIR / f"event.{today}.db"

        if EVENT_DB_PATH.exists() and not backup_path.exists():
            shutil.copy2(EVENT_DB_PATH, backup_path)
            print(f"已创建事件数据库备份: {backup_path}")

        now_ts = time.time()
        keep_seconds = BACKUP_KEEP_DAYS * 24 * 60 * 60
        for path in BACKUP_DIR.glob("event.*.db"):
            try:
                if now_ts - path.stat().st_mtime > keep_seconds:
                    path.unlink()
                    print(f"已删除过期事件数据库备份: {path.name}")
            except Exception as exc:
                print(f"删除过期事件数据库备份失败: {path} err={exc}")
    except Exception as exc:
        print(f"事件数据库备份检查失败(忽略): {exc}")


def get_event_db_path() -> Path:
    """获取事件数据库文件路径，确保目录存在并完成首次备份。"""
    EVENT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _backup_event_db_if_needed()
    return EVENT_DB_PATH


@contextmanager
def get_event_db_connection():
    """获取事件数据库连接。"""
    db_path = get_event_db_path()
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_event_database() -> None:
    """初始化事件数据库所需索引，并触发备份。"""
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS event_project_dict (
                project_id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS event_type_dict (
                event_type_code TEXT PRIMARY KEY,
                event_type_name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_records_event_id
            ON event_records(event_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_records_project_id
            ON event_records(project_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_records_event_type_corrected
            ON event_records(event_type_corrected)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_records_start_time
            ON event_records(start_time)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_records_source_name
            ON event_records(source_name)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_project_dict_sort
            ON event_project_dict(sort_order)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_type_dict_sort
            ON event_type_dict(sort_order)
            """
        )
        try:
            cursor.execute("ALTER TABLE event_records ADD COLUMN segment_count INTEGER DEFAULT 0")
            print("已添加 segment_count 字段到 event_records 表")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE event_records ADD COLUMN segment_paths_json TEXT DEFAULT '[]'")
            print("已添加 segment_paths_json 字段到 event_records 表")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE event_records ADD COLUMN segment_descriptions_json TEXT DEFAULT '[]'")
            print("已添加 segment_descriptions_json 字段到 event_records 表")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE event_records ADD COLUMN segment_statuses_json TEXT DEFAULT '[]'")
            print("已添加 segment_statuses_json 字段到 event_records 表")
        except Exception:
            pass
        cursor.execute(
            """
            UPDATE event_records
            SET segment_count = 0
            WHERE segment_count IS NULL
            """
        )
        cursor.execute(
            """
            UPDATE event_records
            SET segment_paths_json = '[]'
            WHERE segment_paths_json IS NULL OR TRIM(segment_paths_json) = ''
            """
        )
        cursor.execute(
            """
            UPDATE event_records
            SET segment_descriptions_json = '[]'
            WHERE segment_descriptions_json IS NULL OR TRIM(segment_descriptions_json) = ''
            """
        )
        cursor.execute(
            """
            UPDATE event_records
            SET segment_statuses_json = '[]'
            WHERE segment_statuses_json IS NULL OR TRIM(segment_statuses_json) = ''
            """
        )

        now = datetime.now().isoformat()
        for index, (project_id, project_name) in enumerate(STANDARD_PROJECT_OPTIONS, start=1):
            cursor.execute(
                """
                INSERT INTO event_project_dict (project_id, project_name, sort_order, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    project_name = excluded.project_name,
                    sort_order = excluded.sort_order,
                    updated_at = excluded.updated_at
                """,
                (project_id, project_name, index, now),
            )

        for index, (event_type_code, event_type_name) in enumerate(STANDARD_EVENT_TYPE_OPTIONS, start=1):
            cursor.execute(
                """
                INSERT INTO event_type_dict (event_type_code, event_type_name, sort_order, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(event_type_code) DO UPDATE SET
                    event_type_name = excluded.event_type_name,
                    sort_order = excluded.sort_order,
                    updated_at = excluded.updated_at
                """,
                (event_type_code, event_type_name, index, now),
            )

    refresh_event_dict_cache()


def refresh_event_dict_cache() -> Dict[str, List[Dict[str, str]]]:
    """从字典表加载到内存缓存，供高频读取。"""
    global _event_dict_cache
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT project_id, project_name
            FROM event_project_dict
            ORDER BY sort_order ASC, project_id ASC
            """
        )
        project_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT event_type_code, event_type_name
            FROM event_type_dict
            ORDER BY sort_order ASC, event_type_code ASC
            """
        )
        event_type_rows = cursor.fetchall()

    _event_dict_cache = {
        "projectOptions": [
            {"code": row["project_id"], "name": row["project_name"]}
            for row in project_rows
        ],
        "eventTypeOptions": [
            {"code": row["event_type_code"], "name": row["event_type_name"]}
            for row in event_type_rows
        ],
    }
    return _event_dict_cache


def get_event_dict_cache() -> Dict[str, List[Dict[str, str]]]:
    """获取事件字典缓存；为空时懒加载。"""
    if not _event_dict_cache["projectOptions"] or not _event_dict_cache["eventTypeOptions"]:
        return refresh_event_dict_cache()
    return _event_dict_cache


def get_project_name_by_id(project_id: Optional[str]) -> Optional[str]:
    if not project_id:
        return None
    cache = get_event_dict_cache()
    for item in cache["projectOptions"]:
        if item["code"] == project_id:
            return item["name"]
    return None


def get_event_type_name_by_code(event_type_code: Optional[str]) -> Optional[str]:
    if not event_type_code:
        return None
    cache = get_event_dict_cache()
    for item in cache["eventTypeOptions"]:
        if item["code"] == event_type_code:
            return item["name"]
    return None


def _normalize_video_object_path(video_path: Optional[str]) -> Optional[str]:
    if not video_path:
        return None
    normalized = str(video_path).strip()
    if not normalized:
        return None
    if normalized.startswith("/mnt/"):
        normalized = normalized[len("/mnt/"):]
    return normalized.lstrip("/")


def _build_video_url(video_path: Optional[str]) -> Optional[str]:
    object_path = _normalize_video_object_path(video_path)
    if not object_path:
        return None
    scheme = "https" if MINIO_SECURE else "http"
    return f"{scheme}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_path}"


def _build_image_big_url(image_paths: Optional[str]) -> Optional[str]:
    if not image_paths:
        return None
    parts = [segment.strip() for segment in str(image_paths).split(",") if segment.strip()]
    if not parts:
        return None
    image_big_path = next((item for item in parts if item.endswith("/image_big.jpg")), None)
    if not image_big_path:
        return None
    object_path = _normalize_video_object_path(image_big_path)
    if not object_path:
        return None
    scheme = "https" if MINIO_SECURE else "http"
    return f"{scheme}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_path}"


def _parse_json_string_list(raw_value: Optional[str]) -> List[str]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return []
    except Exception:
        return []


def search_events(
    project_ids: Optional[List[str]] = None,
    event_type_codes: Optional[List[str]] = None,
    source_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Dict[str, Any]], int]:
    """查询事件记录并返回分页结果。"""
    project_ids = [item.strip() for item in (project_ids or []) if item and item.strip()]
    event_type_codes = [item.strip() for item in (event_type_codes or []) if item and item.strip()]
    page = max(page, 1)
    page_size = max(page_size, 1)

    where_conditions: List[str] = []
    params: List[Any] = []

    if project_ids:
        placeholders = ",".join("?" for _ in project_ids)
        where_conditions.append(f"project_id IN ({placeholders})")
        params.extend(project_ids)

    if event_type_codes:
        placeholders = ",".join("?" for _ in event_type_codes)
        where_conditions.append(f"event_type_corrected IN ({placeholders})")
        params.extend(event_type_codes)

    if source_name and source_name.strip():
        where_conditions.append("source_name LIKE ?")
        params.append(f"%{source_name.strip()}%")

    if start_date:
        where_conditions.append("start_time >= ?")
        params.append(start_date)

    if end_date:
        where_conditions.append("start_time <= ?")
        params.append(end_date)

    where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
    offset = (page - 1) * page_size

    with get_event_db_connection() as conn:
        cursor = conn.cursor()

        count_sql = f"""
            SELECT COUNT(*)
            FROM event_records
            WHERE {where_clause}
        """
        cursor.execute(count_sql, params)
        total_count = int(cursor.fetchone()[0] or 0)

        search_sql = f"""
            SELECT
                event_id,
                project_id,
                project_name,
                event_type_corrected,
                event_name_corrected,
                event_name,
                source_name,
                start_time,
                image_paths,
                video_path,
                segment_count,
                segment_paths_json,
                segment_descriptions_json,
                segment_statuses_json,
                created_at
            FROM event_records
            WHERE {where_clause}
            ORDER BY start_time DESC, event_id DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(search_sql, [*params, page_size, offset])
        rows = cursor.fetchall()

    results: List[Dict[str, Any]] = []
    for row in rows:
        normalized_video_path = _normalize_video_object_path(row["video_path"])
        segment_paths = _parse_json_string_list(row["segment_paths_json"])
        segment_descriptions = _parse_json_string_list(row["segment_descriptions_json"])
        segment_statuses = _parse_json_string_list(row["segment_statuses_json"])
        normalized_segment_paths = [
            _normalize_video_object_path(item) for item in segment_paths if _normalize_video_object_path(item)
        ]
        segment_urls = [_build_video_url(item) for item in normalized_segment_paths]
        project_name = get_project_name_by_id(row["project_id"]) or row["project_name"] or row["project_id"]
        event_type_name = (
            get_event_type_name_by_code(row["event_type_corrected"])
            or row["event_name_corrected"]
            or row["event_name"]
            or row["event_type_corrected"]
        )
        results.append(
            {
                "eventId": str(row["event_id"]),
                "uuid": str(row["event_id"]),
                "projectId": row["project_id"],
                "projectName": project_name,
                "eventTypeCode": row["event_type_corrected"],
                "eventTypeName": event_type_name,
                "sourceName": row["source_name"] or "",
                "startTime": row["start_time"] or row["created_at"] or "",
                "videoPath": normalized_video_path,
                "videoUrl": _build_video_url(row["video_path"]),
                "segmentCount": int(row["segment_count"] or 0),
                "segmentPaths": normalized_segment_paths,
                "segmentUrls": segment_urls,
                "segmentDescriptions": segment_descriptions,
                "segmentStatuses": segment_statuses,
                "imageBigUrl": _build_image_big_url(row["image_paths"]),
                "fileName": Path(normalized_video_path).name if normalized_video_path else None,
            }
        )

    return results, total_count


def get_pending_event_videos_for_segmentation(
    limit: int,
    event_type_codes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    safe_limit = max(int(limit or 0), 1)
    normalized_codes = [item.strip() for item in (event_type_codes or []) if item and item.strip()]
    where_sql = """
        video_path IS NOT NULL
        AND TRIM(video_path) <> ''
        AND IFNULL(segment_count, 0) <= 0
    """
    params: List[Any] = []
    if normalized_codes:
        placeholders = ",".join("?" for _ in normalized_codes)
        where_sql += f" AND event_type_corrected IN ({placeholders})"
        params.extend(normalized_codes)
    params.append(safe_limit)
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                event_id,
                project_id,
                event_type_corrected,
                video_path,
                start_time,
                segment_count
            FROM event_records
            WHERE {where_sql}
            ORDER BY start_time DESC, event_id DESC
            LIMIT ?
            """,
            params,
        )
        rows = cursor.fetchall()
    return [
        {
            "event_id": str(row["event_id"]),
            "project_id": row["project_id"],
            "event_type_corrected": row["event_type_corrected"],
            "video_path": row["video_path"],
            "start_time": row["start_time"],
            "segment_count": int(row["segment_count"] or 0),
        }
        for row in rows
    ]


def update_event_segmentation_result(
    event_id: str,
    project_id: str,
    event_type_corrected: str,
    segment_paths: List[str],
    segment_descriptions: List[str],
    segment_statuses: List[str],
) -> None:
    if len(segment_paths) != len(segment_descriptions) or len(segment_paths) != len(segment_statuses):
        raise ValueError("分块字段长度不一致")
    payload_paths = json.dumps(segment_paths, ensure_ascii=False)
    payload_descriptions = json.dumps(segment_descriptions, ensure_ascii=False)
    payload_statuses = json.dumps(segment_statuses, ensure_ascii=False)
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE event_records
            SET
                segment_count = ?,
                segment_paths_json = ?,
                segment_descriptions_json = ?,
                segment_statuses_json = ?
            WHERE event_id = ? AND project_id = ? AND event_type_corrected = ?
            """,
            (
                len(segment_paths),
                payload_paths,
                payload_descriptions,
                payload_statuses,
                event_id,
                project_id,
                event_type_corrected,
            ),
        )


def update_event_segment_annotations(
    event_id: str,
    project_id: str,
    event_type_corrected: str,
    segment_descriptions: List[str],
    segment_statuses: List[str],
) -> None:
    if len(segment_descriptions) != len(segment_statuses):
        raise ValueError("分段描述和分段状态长度不一致")

    payload_descriptions = json.dumps(segment_descriptions, ensure_ascii=False)
    payload_statuses = json.dumps(segment_statuses, ensure_ascii=False)
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE event_records
            SET
                segment_descriptions_json = ?,
                segment_statuses_json = ?
            WHERE event_id = ? AND project_id = ? AND event_type_corrected = ?
            """,
            (
                payload_descriptions,
                payload_statuses,
                event_id,
                project_id,
                event_type_corrected,
            ),
        )


def get_event_record_media_paths(
    event_id: str,
    project_id: str,
    event_type_corrected: str,
) -> Dict[str, str]:
    """按主键获取事件记录关联媒体路径。"""
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT image_paths, video_path
            FROM event_records
            WHERE event_id = ? AND project_id = ? AND event_type_corrected = ?
            LIMIT 1
            """,
            (event_id, project_id, event_type_corrected),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("目标事件记录不存在")

        image_paths = str(row["image_paths"] or "").strip()
        video_path = str(row["video_path"] or "").strip()

        return {
            "image_paths": image_paths,
            "video_path": video_path,
        }


def delete_event_record(
    event_id: str,
    project_id: str,
    event_type_corrected: str,
) -> None:
    """按主键删除事件记录。"""
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM event_records
            WHERE event_id = ? AND project_id = ? AND event_type_corrected = ?
            """,
            (event_id, project_id, event_type_corrected),
        )
        if cursor.rowcount <= 0:
            raise ValueError("目标事件记录不存在")
