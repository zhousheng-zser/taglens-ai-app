# -*- coding: utf-8 -*-
"""
事件数据库模块 - 使用 MySQL taglens_event 存储事件检索数据
"""
import json
import os
import random
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BACKUP_DIR = Path(__file__).parent.parent.parent / "data" / "backup"
BACKUP_KEEP_DAYS = int(os.getenv("DB_BACKUP_KEEP_DAYS", "7"))
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "bucket-taglens")
_event_backup_checked = False
_event_dict_cache: Dict[str, Any] = {
    "projectOptions": [],
    "eventTypeOptions": [],
    "eventTypeQuestionsMap": {},
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


def _mysql_connect_kwargs() -> Dict[str, Any]:
    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_EVENT_DATABASE", "taglens_event"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
    }


def _in_clause(size: int) -> str:
    return ",".join(["%s"] * size)


def _ensure_column(cursor, table: str, column: str, definition: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    if int(cursor.fetchone()["cnt"]) == 0:
        cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")
        print(f"已添加 {column} 字段到 {table} 表")


def _backup_event_db_if_needed() -> None:
    """按天 mysqldump 备份 MySQL taglens_event，并清理过期 .sql 备份（保留原有 .db 文件）。"""
    global _event_backup_checked
    if _event_backup_checked:
        return
    _event_backup_checked = True

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        backup_path = BACKUP_DIR / f"event.{today}.sql"
        db_name = os.getenv("MYSQL_EVENT_DATABASE", "taglens_event")

        if not backup_path.exists():
            kwargs = _mysql_connect_kwargs()
            cmd = [
                "mysqldump",
                f"-h{kwargs['host']}",
                f"-P{kwargs['port']}",
                f"-u{kwargs['user']}",
                f"-p{kwargs['password']}",
                "--single-transaction",
                "--quick",
                "--set-gtid-purged=OFF",
                db_name,
            ]
            with open(backup_path, "w", encoding="utf-8") as outfile:
                subprocess.run(cmd, stdout=outfile, stderr=subprocess.PIPE, check=True)
            print(f"已创建事件数据库 MySQL 备份: {backup_path}")

        now_ts = time.time()
        keep_seconds = BACKUP_KEEP_DAYS * 24 * 60 * 60
        for path in list(BACKUP_DIR.glob("event.*.sql")) + list(BACKUP_DIR.glob("event.*.sql.gz")):
            try:
                if now_ts - path.stat().st_mtime > keep_seconds:
                    path.unlink()
                    print(f"已删除过期事件数据库备份: {path.name}")
            except Exception as exc:
                print(f"删除过期事件数据库备份失败: {path} err={exc}")
    except Exception as exc:
        print(f"事件数据库备份检查失败(忽略): {exc}")


@contextmanager
def get_event_db_connection():
    """获取事件 MySQL 数据库连接。"""
    _backup_event_db_if_needed()
    conn = pymysql.connect(
        **_mysql_connect_kwargs(),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_event_database() -> None:
    """初始化事件 MySQL 表结构、索引与字典数据，并触发备份。"""
    kwargs = _mysql_connect_kwargs()
    server_conn = pymysql.connect(
        host=kwargs["host"],
        port=kwargs["port"],
        user=kwargs["user"],
        password=kwargs["password"],
        charset=kwargs["charset"],
        autocommit=True,
    )
    try:
        with server_conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{kwargs['database']}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        server_conn.close()

    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS event_project_dict (
                project_id VARCHAR(100) NOT NULL PRIMARY KEY,
                project_name VARCHAR(200) NOT NULL,
                sort_order INT NOT NULL DEFAULT 0,
                updated_at VARCHAR(64) NOT NULL,
                KEY idx_event_project_dict_sort (sort_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS event_type_dict (
                event_type_code VARCHAR(50) NOT NULL PRIMARY KEY,
                event_type_name VARCHAR(200) NOT NULL,
                sort_order INT NOT NULL DEFAULT 0,
                updated_at VARCHAR(64) NOT NULL,
                questions_list LONGTEXT NULL,
                KEY idx_event_type_dict_sort (sort_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS event_records (
                event_id VARCHAR(100) NOT NULL,
                project_id VARCHAR(100) NOT NULL,
                project_name VARCHAR(200) NULL,
                camera_name VARCHAR(200) NULL,
                mvp_camera_id VARCHAR(100) NULL,
                event_type VARCHAR(50) NULL,
                start_time VARCHAR(64) NULL,
                video_url LONGTEXT NULL,
                mvp_ip VARCHAR(100) NULL,
                task_id VARCHAR(100) NULL,
                source_id VARCHAR(100) NULL,
                source_name VARCHAR(200) NULL,
                event_name VARCHAR(200) NULL,
                event_type_corrected VARCHAR(50) NOT NULL,
                event_name_corrected VARCHAR(200) NULL,
                event_level VARCHAR(10) NULL,
                event_position VARCHAR(100) NULL,
                end_time VARCHAR(64) NULL,
                detect_time VARCHAR(64) NULL,
                vehicle_plate VARCHAR(50) NULL,
                vehicle_plate_color VARCHAR(10) NULL,
                vehicle_confidence VARCHAR(10) NULL,
                vehicle_type VARCHAR(10) NULL,
                vehicle_category VARCHAR(10) NULL,
                vehicle_color VARCHAR(10) NULL,
                vehicle_speed VARCHAR(10) NULL,
                lane_number VARCHAR(10) NULL,
                process_status VARCHAR(10) NULL,
                event_confidence VARCHAR(10) NULL,
                scene_match VARCHAR(10) NULL,
                scene_match_degree VARCHAR(10) NULL,
                analysis_server VARCHAR(100) NULL,
                management_server VARCHAR(100) NULL,
                debugging_info_json LONGTEXT NULL,
                image_paths LONGTEXT NULL,
                video_path LONGTEXT NULL,
                download_source VARCHAR(50) NULL,
                status VARCHAR(20) NULL,
                created_at VARCHAR(64) NULL,
                segment_count INT NULL DEFAULT 0,
                segment_paths_json LONGTEXT NULL,
                segment_descriptions_json LONGTEXT NULL,
                segment_review_descriptions_json LONGTEXT NULL,
                segment_descriptions_en_json LONGTEXT NULL,
                segment_statuses_json LONGTEXT NULL,
                questions_answers_list LONGTEXT NULL,
                PRIMARY KEY (event_id, project_id, event_type_corrected),
                KEY idx_event_records_event_id (event_id),
                KEY idx_event_records_project_id (project_id),
                KEY idx_event_records_event_type_corrected (event_type_corrected),
                KEY idx_event_records_start_time (start_time),
                KEY idx_event_records_source_name (source_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )

        _ensure_column(cursor, "event_records", "segment_count", "INT NULL DEFAULT 0")
        _ensure_column(cursor, "event_records", "segment_paths_json", "LONGTEXT NULL")
        _ensure_column(cursor, "event_records", "segment_descriptions_json", "LONGTEXT NULL")
        _ensure_column(cursor, "event_records", "segment_review_descriptions_json", "LONGTEXT NULL")
        _ensure_column(cursor, "event_records", "segment_descriptions_en_json", "LONGTEXT NULL")
        _ensure_column(cursor, "event_records", "segment_statuses_json", "LONGTEXT NULL")
        _ensure_column(cursor, "event_type_dict", "questions_list", "LONGTEXT NULL")
        _ensure_column(cursor, "event_records", "questions_answers_list", "LONGTEXT NULL")

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
            SET segment_review_descriptions_json = '[]'
            WHERE segment_review_descriptions_json IS NULL OR TRIM(segment_review_descriptions_json) = ''
            """
        )
        cursor.execute(
            """
            UPDATE event_records
            SET segment_descriptions_en_json = '[]'
            WHERE segment_descriptions_en_json IS NULL OR TRIM(segment_descriptions_en_json) = ''
            """
        )
        cursor.execute(
            """
            UPDATE event_records
            SET segment_statuses_json = '[]'
            WHERE segment_statuses_json IS NULL OR TRIM(segment_statuses_json) = ''
            """
        )
        cursor.execute(
            """
            UPDATE event_type_dict
            SET questions_list = '[]'
            WHERE questions_list IS NULL OR TRIM(questions_list) = ''
            """
        )
        cursor.execute(
            """
            UPDATE event_records
            SET questions_answers_list = '[]'
            WHERE questions_answers_list IS NULL OR TRIM(questions_answers_list) = ''
            """
        )

        now = datetime.now().isoformat()
        for index, (project_id, project_name) in enumerate(STANDARD_PROJECT_OPTIONS, start=1):
            cursor.execute(
                """
                INSERT INTO event_project_dict (project_id, project_name, sort_order, updated_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    project_name = VALUES(project_name),
                    sort_order = VALUES(sort_order),
                    updated_at = VALUES(updated_at)
                """,
                (project_id, project_name, index, now),
            )

        for index, (event_type_code, event_type_name) in enumerate(STANDARD_EVENT_TYPE_OPTIONS, start=1):
            cursor.execute(
                """
                INSERT INTO event_type_dict (event_type_code, event_type_name, sort_order, updated_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    event_type_name = VALUES(event_type_name),
                    sort_order = VALUES(sort_order),
                    updated_at = VALUES(updated_at)
                """,
                (event_type_code, event_type_name, index, now),
            )

    refresh_event_dict_cache()


def refresh_event_dict_cache() -> Dict[str, Any]:
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
            SELECT event_type_code, event_type_name, IFNULL(questions_list, '[]') AS questions_list
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
        "eventTypeQuestionsMap": {
            row["event_type_code"]: _parse_json_string_list(row["questions_list"])
            for row in event_type_rows
        },
    }
    return _event_dict_cache


def get_event_dict_cache() -> Dict[str, Any]:
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


def get_event_type_questions_by_code(event_type_code: Optional[str]) -> List[str]:
    if not event_type_code:
        return []
    cache = get_event_dict_cache()
    questions_map = cache.get("eventTypeQuestionsMap", {})
    value = questions_map.get(event_type_code) if isinstance(questions_map, dict) else None
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def _build_default_questions_answers(
    segment_count: int,
    event_type_code: str,
    event_id: str,
) -> List[List[Dict[str, str]]]:
    template = get_event_type_questions_by_code(event_type_code)
    unique_template = list(dict.fromkeys([q.strip() for q in template if q and q.strip()]))
    if len(unique_template) < 2:
        unique_template = ["临时填充问题1?", "临时填充问题2?"]

    result: List[List[Dict[str, str]]] = []
    for _idx in range(max(segment_count, 0)):
        picked = random.sample(unique_template, 2)
        result.append([
            {"question": picked[0], "answer": ""},
            {"question": picked[1], "answer": ""},
        ])
    return result


def _parse_questions_answers_2d(
    raw_value: Optional[str],
    segment_count: int,
    event_type_code: str,
    event_id: str,
) -> List[List[Dict[str, str]]]:
    fallback = _build_default_questions_answers(segment_count, event_type_code, event_id)
    if not raw_value:
        return fallback
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return fallback
    if not isinstance(parsed, list):
        return fallback

    normalized: List[List[Dict[str, str]]] = []
    for seg in parsed:
        if not isinstance(seg, list):
            normalized.append([])
            continue
        pair_list: List[Dict[str, str]] = []
        for qa in seg:
            if not isinstance(qa, dict):
                continue
            q = str(qa.get("question", "")).strip()
            a = str(qa.get("answer", "")).strip()
            if not q:
                continue
            pair_list.append({"question": q, "answer": a})
            if len(pair_list) >= 2:
                break
        normalized.append(pair_list)

    target_len = max(segment_count, 0)
    if len(normalized) < target_len:
        normalized.extend([[] for _ in range(target_len - len(normalized))])
    elif len(normalized) > target_len:
        normalized = normalized[:target_len]

    for idx in range(target_len):
        if len(normalized[idx]) < 2:
            normalized[idx] = fallback[idx]
        elif len(normalized[idx]) > 2:
            normalized[idx] = normalized[idx][:2]
    return normalized


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
    return f"/{MINIO_BUCKET}/{object_path}"


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
    return f"/{MINIO_BUCKET}/{object_path}"


def _build_image_variant_urls(image_paths: Optional[str]) -> Dict[str, Optional[str]]:
    variants: Dict[str, Optional[str]] = {
        "big": None,
        "composite": None,
        "overlay": None,
    }
    if not image_paths:
        return variants
    parts = [segment.strip() for segment in str(image_paths).split(",") if segment.strip()]
    for item in parts:
        normalized = _normalize_video_object_path(item)
        if not normalized:
            continue
        if normalized.endswith("/image_big.jpg"):
            variants["big"] = _build_video_url(normalized)
        elif normalized.endswith("/image_composite.jpg"):
            variants["composite"] = _build_video_url(normalized)
        elif normalized.endswith("/image_overlay.jpg"):
            variants["overlay"] = _build_video_url(normalized)
    return variants


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


def _parse_segment_text_list(raw_value: Optional[str]) -> List[str]:
    """解析分段文本数组，保留空字符串以维持与分段索引一一对应。"""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, list):
            return [str(item) if item is not None else "" for item in parsed]
        return []
    except Exception:
        return []


def _pad_string_list(items: List[str], length: int, fill: str = "") -> List[str]:
    result = list(items[:length])
    while len(result) < length:
        result.append(fill)
    return result


def _classify_question_answer_status(
    questions_answers_list: List[List[Dict[str, str]]],
    segment_count: int,
) -> str:
    if segment_count <= 0 or not questions_answers_list:
        return "all_unanswered"

    normalized_segments = questions_answers_list[:segment_count]
    if len(normalized_segments) < segment_count:
        normalized_segments.extend([[] for _ in range(segment_count - len(normalized_segments))])

    total_questions = 0
    answered_questions = 0
    has_question_each_segment = True

    for segment in normalized_segments:
        question_count_this_segment = 0
        for qa in (segment or []):
            question = str((qa or {}).get("question", "")).strip()
            answer = str((qa or {}).get("answer", "")).strip()
            if not question:
                continue
            question_count_this_segment += 1
            total_questions += 1
            if answer:
                answered_questions += 1
        if question_count_this_segment == 0:
            has_question_each_segment = False

    if total_questions == 0 or answered_questions == 0:
        return "all_unanswered"

    if has_question_each_segment and answered_questions == total_questions:
        return "all_answered"

    return "partially_answered"


def _match_question_answer_status(
    questions_answers_list: List[List[Dict[str, str]]],
    segment_count: int,
    target_status: str,
) -> bool:
    if target_status == "all":
        return True
    return _classify_question_answer_status(
        questions_answers_list=questions_answers_list,
        segment_count=segment_count,
    ) == target_status


def _classify_description_status(
    segment_descriptions: List[str],
    segment_count: int,
) -> str:
    if segment_count <= 0:
        return "all_unedited"

    normalized_descriptions = segment_descriptions[:segment_count]
    if len(normalized_descriptions) < segment_count:
        normalized_descriptions.extend(["" for _ in range(segment_count - len(normalized_descriptions))])

    edited_count = sum(1 for item in normalized_descriptions if str(item or "").strip())
    if edited_count == 0:
        return "all_unedited"
    if edited_count == segment_count:
        return "all_edited"
    return "partially_edited"


def _match_description_status(
    segment_descriptions: List[str],
    segment_count: int,
    target_status: str,
) -> bool:
    if target_status == "all":
        return True
    return _classify_description_status(
        segment_descriptions=segment_descriptions,
        segment_count=segment_count,
    ) == target_status


def search_events(
    project_ids: Optional[List[str]] = None,
    event_type_codes: Optional[List[str]] = None,
    source_name: Optional[str] = None,
    processing_status: str = "all",
    question_answer_status: str = "all",
    description_status: str = "all",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Dict[str, Any]], int]:
    """查询事件记录并返回分页结果。"""
    refresh_event_dict_cache()

    project_ids = [item.strip() for item in (project_ids or []) if item and item.strip()]
    event_type_codes = [item.strip() for item in (event_type_codes or []) if item and item.strip()]
    page = max(page, 1)
    page_size = max(page_size, 1)

    where_conditions: List[str] = []
    params: List[Any] = []

    if project_ids:
        where_conditions.append(f"project_id IN ({_in_clause(len(project_ids))})")
        params.extend(project_ids)

    if event_type_codes:
        where_conditions.append(f"event_type_corrected IN ({_in_clause(len(event_type_codes))})")
        params.extend(event_type_codes)

    if source_name and source_name.strip():
        where_conditions.append("source_name LIKE %s")
        params.append(f"%{source_name.strip()}%")

    if processing_status == "processed":
        where_conditions.append(
            """
            IFNULL(segment_count, 0) > 0
            AND TRIM(IFNULL(segment_statuses_json, '')) <> ''
            AND segment_statuses_json <> '[]'
            AND segment_statuses_json NOT LIKE '%%待定%%'
            AND segment_statuses_json NOT LIKE '%%待标注%%'
            """
        )
    elif processing_status == "unprocessed":
        where_conditions.append(
            """
            (
                TRIM(IFNULL(segment_statuses_json, '')) <> ''
                AND segment_statuses_json <> '[]'
                AND (
                    segment_statuses_json LIKE '%%待定%%'
                    OR segment_statuses_json LIKE '%%待标注%%'
                )
            )
            """
        )

    if start_date:
        where_conditions.append("start_time >= %s")
        params.append(start_date)

    if end_date:
        where_conditions.append("start_time <= %s")
        params.append(end_date)

    where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
    offset = (page - 1) * page_size

    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        needs_python_filter = question_answer_status != "all" or description_status != "all"
        if not needs_python_filter:
            count_sql = f"""
                SELECT COUNT(*) AS cnt
                FROM event_records
                WHERE {where_clause}
            """
            cursor.execute(count_sql, params)
            total_count = int(cursor.fetchone()["cnt"] or 0)
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
                    segment_review_descriptions_json,
                    segment_descriptions_en_json,
                    segment_statuses_json,
                    questions_answers_list,
                    created_at
                FROM event_records
                WHERE {where_clause}
                ORDER BY start_time DESC, event_id DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(search_sql, [*params, page_size, offset])
            rows = cursor.fetchall()
        else:
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
                    segment_review_descriptions_json,
                    segment_descriptions_en_json,
                    segment_statuses_json,
                    questions_answers_list,
                    created_at
                FROM event_records
                WHERE {where_clause}
                ORDER BY start_time DESC, event_id DESC
            """
            cursor.execute(search_sql, params)
            rows = cursor.fetchall()

    raw_results: List[Dict[str, Any]] = []
    for row in rows:
        normalized_video_path = _normalize_video_object_path(row["video_path"])
        segment_paths = _parse_json_string_list(row["segment_paths_json"])
        segment_descriptions = _parse_segment_text_list(row["segment_descriptions_json"])
        segment_review_descriptions = _parse_segment_text_list(row["segment_review_descriptions_json"])
        segment_descriptions_en = _parse_segment_text_list(row["segment_descriptions_en_json"])
        segment_statuses = _parse_json_string_list(row["segment_statuses_json"])
        normalized_segment_paths = [
            _normalize_video_object_path(item) for item in segment_paths if _normalize_video_object_path(item)
        ]
        segment_urls = [_build_video_url(item) for item in normalized_segment_paths]
        image_variants = _build_image_variant_urls(row["image_paths"])
        segment_count = int(row["segment_count"] or 0)
        align_len = max(segment_count, len(normalized_segment_paths), len(segment_paths))
        segment_descriptions = _pad_string_list(segment_descriptions, align_len)
        segment_review_descriptions = _pad_string_list(segment_review_descriptions, align_len)
        segment_descriptions_en = _pad_string_list(segment_descriptions_en, align_len)
        segment_statuses = _pad_string_list(segment_statuses, align_len, "待定")
        questions_answers_list = _parse_questions_answers_2d(
            row["questions_answers_list"],
            segment_count=segment_count,
            event_type_code=row["event_type_corrected"] or "",
            event_id=str(row["event_id"]),
        )
        if not _match_question_answer_status(
            questions_answers_list=questions_answers_list,
            segment_count=segment_count,
            target_status=question_answer_status,
        ):
            continue
        if not _match_description_status(
            segment_descriptions=segment_descriptions,
            segment_count=segment_count,
            target_status=description_status,
        ):
            continue

        project_name = get_project_name_by_id(row["project_id"]) or row["project_name"] or row["project_id"]
        event_type_name = (
            get_event_type_name_by_code(row["event_type_corrected"])
            or row["event_name_corrected"]
            or row["event_name"]
            or row["event_type_corrected"]
        )
        raw_results.append(
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
                "segmentCount": segment_count,
                "segmentPaths": normalized_segment_paths,
                "segmentUrls": segment_urls,
                "segmentDescriptions": segment_descriptions,
                "segmentReviewDescriptions": segment_review_descriptions,
                "segmentDescriptionsEn": segment_descriptions_en,
                "segmentStatuses": segment_statuses,
                "questionsAnswersList": questions_answers_list,
                "eventTypeQuestions": get_event_type_questions_by_code(row["event_type_corrected"] or ""),
                "imageBigUrl": _build_image_big_url(row["image_paths"]),
                "imageCompositeUrl": image_variants["composite"],
                "imageOverlayUrl": image_variants["overlay"],
                "fileName": Path(normalized_video_path).name if normalized_video_path else None,
            }
        )

    if question_answer_status == "all" and description_status == "all":
        return raw_results, total_count

    total_count = len(raw_results)
    start_idx = offset
    end_idx = offset + page_size
    return raw_results[start_idx:end_idx], total_count


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
        where_sql += f" AND event_type_corrected IN ({_in_clause(len(normalized_codes))})"
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
            LIMIT %s
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


def _is_valid_segment_video_path(raw_path: str) -> bool:
    normalized = _normalize_video_object_path(raw_path)
    if not normalized:
        return False
    return normalized.lower().endswith(".mp4")


def get_pending_segments_for_ai_description(
    limit: int,
    event_type_codes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    safe_limit = max(int(limit or 0), 1)
    normalized_codes = [item.strip() for item in (event_type_codes or []) if item and item.strip()]
    where_sql = """
        segment_paths_json IS NOT NULL
        AND TRIM(segment_paths_json) <> ''
        AND TRIM(segment_paths_json) <> '[]'
    """
    params: List[Any] = []
    if normalized_codes:
        where_sql += f" AND event_type_corrected IN ({_in_clause(len(normalized_codes))})"
        params.extend(normalized_codes)

    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                event_id,
                project_id,
                event_type_corrected,
                start_time,
                image_paths,
                segment_paths_json,
                segment_descriptions_json,
                segment_statuses_json,
                questions_answers_list,
                segment_count
            FROM event_records
            WHERE {where_sql}
            ORDER BY start_time DESC, event_id DESC
            """,
            params,
        )
        rows = cursor.fetchall()

    pending: List[Dict[str, Any]] = []
    for row in rows:
        if len(pending) >= safe_limit:
            break

        segment_paths = _parse_json_string_list(row["segment_paths_json"])
        if not segment_paths:
            continue

        segment_count = int(row["segment_count"] or 0) or len(segment_paths)
        segment_descriptions = _parse_segment_text_list(row["segment_descriptions_json"])
        while len(segment_descriptions) < len(segment_paths):
            segment_descriptions.append("")

        overlay_url = _build_image_variant_urls(row["image_paths"]).get("overlay")
        event_id = str(row["event_id"])
        event_type = str(row["event_type_corrected"] or "")

        for idx, raw_path in enumerate(segment_paths):
            if len(pending) >= safe_limit:
                break
            if (segment_descriptions[idx] or "").strip():
                continue
            if not _is_valid_segment_video_path(raw_path):
                continue
            normalized_path = _normalize_video_object_path(raw_path)
            segment_media_path = _build_video_url(normalized_path)
            if not segment_media_path:
                continue

            pending.append(
                {
                    "event_id": event_id,
                    "project_id": row["project_id"],
                    "event_type_corrected": event_type,
                    "start_time": row["start_time"],
                    "segment_index": idx,
                    "segment_media_path": segment_media_path,
                    "overlay_media_path": overlay_url,
                }
            )

    return pending


def get_event_segment_annotation_snapshot(
    event_id: str,
    project_id: str,
    event_type_corrected: str,
) -> Optional[Dict[str, Any]]:
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                segment_paths_json,
                segment_descriptions_json,
                segment_review_descriptions_json,
                segment_descriptions_en_json,
                segment_statuses_json,
                questions_answers_list,
                segment_count
            FROM event_records
            WHERE event_id = %s AND project_id = %s AND event_type_corrected = %s
            """,
            (event_id, project_id, event_type_corrected),
        )
        row = cursor.fetchone()
    if not row:
        return None

    segment_paths = _parse_json_string_list(row["segment_paths_json"])
    if not segment_paths:
        return None

    segment_count = int(row["segment_count"] or 0) or len(segment_paths)
    segment_descriptions = _parse_segment_text_list(row["segment_descriptions_json"])
    segment_review_descriptions = _parse_segment_text_list(row["segment_review_descriptions_json"])
    segment_descriptions_en = _parse_segment_text_list(row["segment_descriptions_en_json"])
    segment_statuses = _parse_segment_text_list(row["segment_statuses_json"])
    questions_answers_list = _parse_questions_answers_2d(
        row["questions_answers_list"],
        segment_count=segment_count,
        event_type_code=event_type_corrected,
        event_id=event_id,
    )

    while len(segment_descriptions) < len(segment_paths):
        segment_descriptions.append("")
    while len(segment_review_descriptions) < len(segment_paths):
        segment_review_descriptions.append("")
    while len(segment_descriptions_en) < len(segment_paths):
        segment_descriptions_en.append("")
    while len(segment_statuses) < len(segment_paths):
        segment_statuses.append("待定")
    while len(questions_answers_list) < len(segment_paths):
        questions_answers_list.append([])

    return {
        "segment_paths": segment_paths,
        "segment_descriptions": segment_descriptions,
        "segment_review_descriptions": segment_review_descriptions,
        "segment_descriptions_en": segment_descriptions_en,
        "segment_statuses": segment_statuses,
        "questions_answers_list": questions_answers_list,
    }


def update_event_segment_description_at_index(
    event_id: str,
    project_id: str,
    event_type_corrected: str,
    segment_index: int,
    description: str,
) -> None:
    snapshot = get_event_segment_annotation_snapshot(event_id, project_id, event_type_corrected)
    if not snapshot:
        raise ValueError(f"事件记录不存在: event_id={event_id}")

    idx = int(segment_index)
    descriptions = list(snapshot["segment_descriptions"])
    review_descriptions = list(snapshot["segment_review_descriptions"])
    descriptions_en = list(snapshot["segment_descriptions_en"])
    statuses = list(snapshot["segment_statuses"])
    qa_list = list(snapshot["questions_answers_list"])

    if idx < 0 or idx >= len(descriptions):
        raise ValueError(f"分段下标越界: {idx}")

    descriptions[idx] = description
    update_event_segment_annotations(
        event_id=event_id,
        project_id=project_id,
        event_type_corrected=event_type_corrected,
        segment_descriptions=descriptions,
        segment_review_descriptions=review_descriptions,
        segment_descriptions_en=descriptions_en,
        segment_statuses=statuses,
        questions_answers_list=qa_list,
    )


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
    segment_review_descriptions = ["" for _ in segment_paths]
    segment_descriptions_en = ["" for _ in segment_paths]
    payload_paths = json.dumps(segment_paths, ensure_ascii=False)
    payload_descriptions = json.dumps(segment_descriptions, ensure_ascii=False)
    payload_review_descriptions = json.dumps(segment_review_descriptions, ensure_ascii=False)
    payload_descriptions_en = json.dumps(segment_descriptions_en, ensure_ascii=False)
    payload_statuses = json.dumps(segment_statuses, ensure_ascii=False)
    payload_questions_answers = json.dumps([[] for _ in range(len(segment_paths))], ensure_ascii=False)
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE event_records
            SET
                segment_count = %s,
                segment_paths_json = %s,
                segment_descriptions_json = %s,
                segment_review_descriptions_json = %s,
                segment_descriptions_en_json = %s,
                segment_statuses_json = %s,
                questions_answers_list = %s
            WHERE event_id = %s AND project_id = %s AND event_type_corrected = %s
            """,
            (
                len(segment_paths),
                payload_paths,
                payload_descriptions,
                payload_review_descriptions,
                payload_descriptions_en,
                payload_statuses,
                payload_questions_answers,
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
    segment_review_descriptions: List[str],
    segment_descriptions_en: List[str],
    segment_statuses: List[str],
    questions_answers_list: Optional[List[List[Dict[str, str]]]] = None,
) -> None:
    lengths = {
        len(segment_descriptions),
        len(segment_review_descriptions),
        len(segment_descriptions_en),
        len(segment_statuses),
    }
    if len(lengths) != 1:
        raise ValueError("三套分段描述与分段状态长度不一致")

    payload_descriptions = json.dumps(segment_descriptions, ensure_ascii=False)
    payload_review_descriptions = json.dumps(segment_review_descriptions, ensure_ascii=False)
    payload_descriptions_en = json.dumps(segment_descriptions_en, ensure_ascii=False)
    payload_statuses = json.dumps(segment_statuses, ensure_ascii=False)
    payload_questions_answers = json.dumps(
        questions_answers_list if questions_answers_list is not None else [],
        ensure_ascii=False,
    )
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE event_records
            SET
                segment_descriptions_json = %s,
                segment_review_descriptions_json = %s,
                segment_descriptions_en_json = %s,
                segment_statuses_json = %s,
                questions_answers_list = %s
            WHERE event_id = %s AND project_id = %s AND event_type_corrected = %s
            """,
            (
                payload_descriptions,
                payload_review_descriptions,
                payload_descriptions_en,
                payload_statuses,
                payload_questions_answers,
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
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT image_paths, video_path
            FROM event_records
            WHERE event_id = %s AND project_id = %s AND event_type_corrected = %s
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
    with get_event_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM event_records
            WHERE event_id = %s AND project_id = %s AND event_type_corrected = %s
            """,
            (event_id, project_id, event_type_corrected),
        )
        if cursor.rowcount <= 0:
            raise ValueError("目标事件记录不存在")
