# -*- coding: utf-8 -*-
"""管理数据库：用户、任务分配、审核记录与会话签名（MySQL taglens_manage）。"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import calendar
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pymysql
import pymysql.cursors
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PASSWORD_ITERATIONS = 200_000
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "3edcVFR$"
SESSION_COOKIE_NAME = "taglens_session"
SESSION_MAX_AGE_SECONDS = int(os.getenv("MANAGE_SESSION_MAX_AGE", str(7 * 24 * 60 * 60)))
SESSION_SECRET = os.getenv("MANAGE_SESSION_SECRET", "taglens-manage-default-secret-change-me")


def _mysql_connect_kwargs() -> Dict[str, Any]:
    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_MANAGE_DATABASE", "taglens_manage"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
    }


@contextmanager
def get_manage_db_connection():
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


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _ensure_column(cursor, table: str, column: str, definition: str) -> None:
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    if int(cursor.fetchone()["cnt"] or 0) == 0:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_manage_database() -> None:
    """创建 MySQL 表结构，并初始化默认管理员。"""
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                password_hash TEXT NOT NULL,
                role ENUM('admin', 'reviewer') NOT NULL,
                display_name VARCHAR(255) NULL,
                is_active TINYINT NOT NULL DEFAULT 1,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                UNIQUE KEY uk_users_username (username),
                KEY idx_users_username (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_time_ranges (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                range_name VARCHAR(255) NOT NULL,
                start_time VARCHAR(64) NOT NULL,
                end_time VARCHAR(64) NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                KEY idx_user_time_ranges_user_id (user_id),
                CONSTRAINT fk_user_time_ranges_user
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        _ensure_column(cursor, "user_time_ranges", "workload_status", "INT NOT NULL DEFAULT 0")
        _ensure_column(cursor, "user_time_ranges", "workload_qa", "INT NOT NULL DEFAULT 0")
        _ensure_column(cursor, "user_time_ranges", "workload_ai_description", "INT NOT NULL DEFAULT 0")
        _ensure_column(cursor, "user_time_ranges", "workload_review_description", "INT NOT NULL DEFAULT 0")
        _ensure_column(cursor, "user_time_ranges", "workload_english_description", "INT NOT NULL DEFAULT 0")
        _ensure_column(cursor, "user_time_ranges", "workload_accident_qa", "INT NOT NULL DEFAULT 0")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS event_task_assignments (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                time_range_id INT NOT NULL,
                task_category VARCHAR(32) NOT NULL,
                event_id VARCHAR(255) NOT NULL,
                project_id VARCHAR(255) NOT NULL,
                event_type_code VARCHAR(64) NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                UNIQUE KEY uk_event_task_category (event_id, project_id, event_type_code, task_category),
                KEY idx_eta_user_range (user_id, time_range_id),
                KEY idx_eta_range_category (time_range_id, task_category),
                CONSTRAINT fk_eta_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_eta_time_range FOREIGN KEY (time_range_id) REFERENCES user_time_ranges(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_workload_daily_snapshots (
                stat_date VARCHAR(10) NOT NULL PRIMARY KEY,
                start_time VARCHAR(64) NOT NULL,
                end_time VARCHAR(64) NOT NULL,
                computed_at VARCHAR(64) NOT NULL,
                pending_status INT NOT NULL DEFAULT 0,
                pending_qa INT NOT NULL DEFAULT 0,
                pending_ai_description INT NOT NULL DEFAULT 0,
                pending_review_description INT NOT NULL DEFAULT 0,
                pending_english_description INT NOT NULL DEFAULT 0,
                pending_accident_qa INT NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS event_review_records (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                event_id VARCHAR(255) NOT NULL,
                project_id VARCHAR(255) NOT NULL,
                event_type_code VARCHAR(64) NOT NULL,
                reviewer_id INT NOT NULL,
                reviewer_username VARCHAR(255) NOT NULL,
                reviewer_display_name VARCHAR(255) NULL,
                review_time VARCHAR(64) NOT NULL,
                status_review_done TINYINT NOT NULL DEFAULT 0,
                qa_review_done TINYINT NOT NULL DEFAULT 0,
                description_review_done TINYINT NOT NULL DEFAULT 0,
                ai_description_done TINYINT NOT NULL DEFAULT 0,
                review_description_done TINYINT NOT NULL DEFAULT 0,
                english_description_done TINYINT NOT NULL DEFAULT 0,
                created_at VARCHAR(64) NOT NULL,
                updated_at VARCHAR(64) NOT NULL,
                UNIQUE KEY uk_event_review_key (event_id, project_id, event_type_code),
                KEY idx_event_review_records_event_key (event_id, project_id, event_type_code),
                KEY idx_event_review_records_reviewer (reviewer_id),
                CONSTRAINT fk_event_review_reviewer
                    FOREIGN KEY (reviewer_id) REFERENCES users(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )

        _ensure_column(cursor, "event_review_records", "ai_description_done", "TINYINT NOT NULL DEFAULT 0")
        _ensure_column(cursor, "event_review_records", "review_description_done", "TINYINT NOT NULL DEFAULT 0")
        _ensure_column(cursor, "event_review_records", "english_description_done", "TINYINT NOT NULL DEFAULT 0")
        _ensure_column(cursor, "event_review_records", "accident_qa_done", "TINYINT NOT NULL DEFAULT 0")
        cursor.execute(
            """
            UPDATE event_review_records
            SET ai_description_done = 1
            WHERE description_review_done = 1 AND ai_description_done = 0
            """
        )

        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'")
        admin_count = int(cursor.fetchone()["cnt"] or 0)
        if admin_count == 0:
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO users (username, password_hash, role, display_name, is_active, created_at, updated_at)
                VALUES (%s, %s, 'admin', '系统管理员', 1, %s, %s)
                """,
                (DEFAULT_ADMIN_USERNAME, hash_password(DEFAULT_ADMIN_PASSWORD), now, now),
            )
            print(f"已创建默认管理员账号: {DEFAULT_ADMIN_USERNAME}")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS project_sync_import_batches (
                id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                project_id VARCHAR(128) NOT NULL,
                batch_key VARCHAR(128) NULL,
                total_count INT NOT NULL DEFAULT 0,
                dedup_count INT NOT NULL DEFAULT 0,
                imported_count INT NOT NULL DEFAULT 0,
                failed_count INT NOT NULL DEFAULT 0,
                completed_at VARCHAR(64) NOT NULL,
                created_at VARCHAR(64) NOT NULL,
                KEY idx_psib_project_completed (project_id, completed_at),
                KEY idx_psib_project_id (project_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )


def insert_project_sync_import_batch(
    *,
    project_id: str,
    batch_key: Optional[str],
    total_count: int,
    dedup_count: int,
    imported_count: int,
    failed_count: int,
    completed_at: Optional[str] = None,
) -> int:
    now = datetime.now().isoformat()
    completed = completed_at or now
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO project_sync_import_batches (
                project_id, batch_key, total_count, dedup_count,
                imported_count, failed_count, completed_at, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                project_id,
                batch_key,
                int(total_count),
                int(dedup_count),
                int(imported_count),
                int(failed_count),
                completed,
                now,
            ),
        )
        return int(cursor.lastrowid)


def _completed_at_date_sql() -> str:
    return "SUBSTRING(b.completed_at, 1, 10)"


def _parse_date_anchor(anchor: str) -> date:
    return datetime.strptime(anchor[:10], "%Y-%m-%d").date()


def _parse_month_anchor(anchor: str) -> Tuple[int, int]:
    normalized = anchor.strip()[:7]
    year_str, month_str = normalized.split("-", 1)
    return int(year_str), int(month_str)


def _add_months(year: int, month: int, delta: int) -> Tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def _monday_of_week(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _yearweek_bucket_key(value: date) -> str:
    iso = value.isocalendar()
    return f"{iso.year}{iso.week:02d}"


def _yearweek_bucket_label(value: date) -> str:
    iso = value.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _month_bucket_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _empty_series_point(bucket_key: str, label: str) -> Dict[str, Any]:
    return {
        "bucketKey": bucket_key,
        "label": label,
        "totalCount": 0,
        "dedupCount": 0,
        "importedCount": 0,
        "failedCount": 0,
    }


def _build_expected_buckets(
    granularity: str,
    anchor: Optional[str],
    range_size: int,
) -> Tuple[List[Dict[str, str]], str, str, List[Any]]:
    """返回 (expected_buckets, filter_sql, range_label, filter_params)。"""
    date_col = f"STR_TO_DATE({_completed_at_date_sql()}, '%%Y-%%m-%%d')"

    if granularity == "day":
        if anchor:
            center = _parse_date_anchor(anchor)
            start = center - timedelta(days=15)
            end = center + timedelta(days=15)
            range_label = f"{start.isoformat()} ~ {end.isoformat()}（共 31 天）"
        else:
            range_size = max(1, min(range_size, 365))
            end = date.today()
            start = end - timedelta(days=range_size - 1)
            range_label = f"最近 {range_size} 天"
        buckets = []
        cursor_day = start
        while cursor_day <= end:
            buckets.append({
                "bucketKey": cursor_day.isoformat(),
                "label": cursor_day.strftime("%m-%d"),
            })
            cursor_day += timedelta(days=1)
        filter_sql = f"{date_col} BETWEEN %s AND %s"
        return buckets, filter_sql, range_label, [start.isoformat(), end.isoformat()]

    if granularity == "week":
        if anchor:
            if "-W" in anchor.upper():
                parts = anchor.upper().split("-W", 1)
                iso_year = int(parts[0])
                iso_week = int(parts[1][:2])
                center_monday = date.fromisocalendar(iso_year, iso_week, 1)
            else:
                center_monday = _monday_of_week(_parse_date_anchor(anchor))
            start = center_monday - timedelta(weeks=6)
            end = center_monday + timedelta(weeks=6, days=6)
            range_label = (
                f"{_yearweek_bucket_label(center_monday)} 前后各 6 周 "
                f"（{_yearweek_bucket_label(start)} ~ {_yearweek_bucket_label(end)}）"
            )
        else:
            range_size = max(1, min(range_size, 52))
            end = date.today()
            start = end - timedelta(weeks=range_size - 1)
            range_label = f"最近 {range_size} 周"
        buckets = []
        week_start = _monday_of_week(start)
        last_monday = _monday_of_week(end)
        while week_start <= last_monday:
            buckets.append({
                "bucketKey": _yearweek_bucket_key(week_start),
                "label": _yearweek_bucket_label(week_start),
            })
            week_start += timedelta(weeks=1)
        filter_sql = f"{date_col} BETWEEN %s AND %s"
        return buckets, filter_sql, range_label, [start.isoformat(), end.isoformat()]

    # month
    if anchor:
        center_year, center_month = _parse_month_anchor(anchor)
        start_year, start_month = _add_months(center_year, center_month, -6)
        end_year, end_month = _add_months(center_year, center_month, 6)
        start = date(start_year, start_month, 1)
        end_day = calendar.monthrange(end_year, end_month)[1]
        end = date(end_year, end_month, end_day)
        range_label = (
            f"{_month_bucket_key(center_year, center_month)} 前后各 6 月 "
            f"（{_month_bucket_key(start_year, start_month)} ~ {_month_bucket_key(end_year, end_month)}）"
        )
    else:
        range_size = max(1, min(range_size, 36))
        end = date.today()
        end_year, end_month = end.year, end.month
        start_year, start_month = _add_months(end_year, end_month, -(range_size - 1))
        start = date(start_year, start_month, 1)
        range_label = f"最近 {range_size} 月"
    buckets = []
    y, m = start.year, start.month
    end_key = _month_bucket_key(end.year, end.month)
    while True:
        key = _month_bucket_key(y, m)
        buckets.append({"bucketKey": key, "label": key})
        if key == end_key:
            break
        y, m = _add_months(y, m, 1)
    filter_sql = f"{date_col} BETWEEN %s AND %s"
    return buckets, filter_sql, range_label, [start.isoformat(), end.isoformat()]


def get_project_sync_import_stats(
    *,
    granularity: str = "day",
    range_size: int = 30,
    anchor: Optional[str] = None,
) -> Dict[str, Any]:
    """按项目聚合同步导入统计，支持 day/week/month；可选 anchor 锚点窗口。"""
    if granularity not in {"day", "week", "month"}:
        raise ValueError("granularity 须为 day、week 或 month")

    expected_buckets, filter_sql, range_label, filter_params = _build_expected_buckets(
        granularity,
        anchor,
        range_size,
    )

    if granularity == "day":
        group_sql = _completed_at_date_sql()
        label_sql = "DATE_FORMAT(STR_TO_DATE(SUBSTRING(b.completed_at, 1, 10), '%%Y-%%m-%%d'), '%%m-%%d')"
    elif granularity == "week":
        group_sql = "YEARWEEK(STR_TO_DATE(SUBSTRING(b.completed_at, 1, 10), '%%Y-%%m-%%d'), 1)"
        label_sql = (
            "CONCAT(YEAR(STR_TO_DATE(SUBSTRING(b.completed_at, 1, 10), '%%Y-%%m-%%d')), '-W', "
            "LPAD(WEEK(STR_TO_DATE(SUBSTRING(b.completed_at, 1, 10), '%%Y-%%m-%%d'), 1), 2, '0'))"
        )
    else:
        group_sql = "DATE_FORMAT(STR_TO_DATE(SUBSTRING(b.completed_at, 1, 10), '%%Y-%%m-%%d'), '%%Y-%%m')"
        label_sql = group_sql

    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                b.project_id,
                {group_sql} AS bucket_key,
                MIN({label_sql}) AS bucket_label,
                SUM(b.total_count) AS total_count,
                SUM(b.dedup_count) AS dedup_count,
                SUM(b.imported_count) AS imported_count,
                SUM(b.failed_count) AS failed_count
            FROM project_sync_import_batches b
            WHERE {filter_sql}
            GROUP BY b.project_id, bucket_key
            ORDER BY b.project_id ASC, bucket_key ASC
            """,
            tuple(filter_params),
        )
        rows = cursor.fetchall()

    by_project: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        pid = str(row["project_id"])
        if pid not in by_project:
            by_project[pid] = {}
        bucket_key = str(row["bucket_key"])
        by_project[pid][bucket_key] = {
            "bucketKey": bucket_key,
            "label": str(row["bucket_label"] or bucket_key),
            "totalCount": int(row["total_count"] or 0),
            "dedupCount": int(row["dedup_count"] or 0),
            "importedCount": int(row["imported_count"] or 0),
            "failedCount": int(row["failed_count"] or 0),
        }

    projects: List[Dict[str, Any]] = []
    for pid, bucket_map in by_project.items():
        series = []
        totals = {"totalCount": 0, "dedupCount": 0, "importedCount": 0, "failedCount": 0}
        for expected in expected_buckets:
            point = bucket_map.get(expected["bucketKey"])
            if point is None:
                point = _empty_series_point(expected["bucketKey"], expected["label"])
            else:
                point = {**point, "label": point.get("label") or expected["label"]}
            series.append(point)
            totals["totalCount"] += point["totalCount"]
            totals["dedupCount"] += point["dedupCount"]
            totals["importedCount"] += point["importedCount"]
            totals["failedCount"] += point["failedCount"]
        projects.append({
            "projectId": pid,
            "totalCount": totals["totalCount"],
            "dedupCount": totals["dedupCount"],
            "importedCount": totals["importedCount"],
            "failedCount": totals["failedCount"],
            "series": series,
        })

    return {
        "granularity": granularity,
        "rangeLabel": range_label,
        "anchor": anchor,
        "seriesTemplate": [
            _empty_series_point(item["bucketKey"], item["label"]) for item in expected_buckets
        ],
        "projects": projects,
    }


def _row_to_user(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "role": row["role"],
        "displayName": row["display_name"] or row["username"],
        "isActive": bool(row["is_active"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, password_hash, role, display_name, is_active, created_at, updated_at
            FROM users
            WHERE username = %s
            """,
            (username,),
        )
        row = cursor.fetchone()
        if not row or not bool(row["is_active"]):
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return _row_to_user(row)


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, role, display_name, is_active, created_at, updated_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        return _row_to_user(row) if row else None


def list_users() -> List[Dict[str, Any]]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, username, role, display_name, is_active, created_at, updated_at
            FROM users
            ORDER BY id ASC
            """
        )
        return [_row_to_user(row) for row in cursor.fetchall()]


def create_user(username: str, password: str, role: str, display_name: Optional[str]) -> Dict[str, Any]:
    if role not in {"admin", "reviewer"}:
        raise ValueError("角色必须是 admin 或 reviewer")
    now = datetime.now().isoformat()
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, role, display_name, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 1, %s, %s)
            """,
            (username, hash_password(password), role, display_name or username, now, now),
        )
        user_id = int(cursor.lastrowid)
    user = get_user_by_id(user_id)
    if not user:
        raise RuntimeError("用户创建后读取失败")
    return user


def delete_user(user_id: int) -> bool:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username, role FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        if row["username"] == DEFAULT_ADMIN_USERNAME and row["role"] == "admin":
            raise ValueError("不能删除默认管理员")
        cursor.execute("DELETE FROM event_review_records WHERE reviewer_id = %s", (user_id,))
        cursor.execute("DELETE FROM user_time_ranges WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return cursor.rowcount > 0


def _time_range_row_to_dict(row: Dict[str, Any], assigned_counts: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    result = {
        "id": int(row["id"]),
        "userId": int(row["user_id"]),
        "rangeName": row["range_name"],
        "startTime": row["start_time"],
        "endTime": row["end_time"],
        "createdAt": row["created_at"],
        "workloadStatus": int(row.get("workload_status") or 0),
        "workloadQa": int(row.get("workload_qa") or 0),
        "workloadAiDescription": int(row.get("workload_ai_description") or 0),
        "workloadReviewDescription": int(row.get("workload_review_description") or 0),
        "workloadEnglishDescription": int(row.get("workload_english_description") or 0),
        "workloadAccidentQa": int(row.get("workload_accident_qa") or 0),
    }
    if assigned_counts is not None:
        result["assignedStatus"] = assigned_counts.get("status", 0)
        result["assignedQa"] = assigned_counts.get("qa", 0)
        result["assignedAiDescription"] = assigned_counts.get("ai_description", 0)
        result["assignedReviewDescription"] = assigned_counts.get("review_description", 0)
        result["assignedEnglishDescription"] = assigned_counts.get("english_description", 0)
        result["assignedAccidentQa"] = assigned_counts.get("accident_qa", 0)
    return result


def list_user_time_ranges(user_id: int) -> List[Dict[str, Any]]:
    from core.task_assignment import get_assigned_counts_by_range

    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, range_name, start_time, end_time, created_at,
                   workload_status, workload_qa, workload_ai_description,
                   workload_review_description, workload_english_description, workload_accident_qa
            FROM user_time_ranges
            WHERE user_id = %s
            ORDER BY start_time ASC, id ASC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
    return [
        _time_range_row_to_dict(row, get_assigned_counts_by_range(int(row["id"])))
        for row in rows
    ]


def create_time_range(
    user_id: int,
    range_name: str,
    start_time: str,
    end_time: str,
    workload_status: int = 0,
    workload_qa: int = 0,
    workload_ai_description: int = 0,
    workload_review_description: int = 0,
    workload_english_description: int = 0,
    workload_accident_qa: int = 0,
) -> Dict[str, Any]:
    from core.task_assignment import allocate_tasks_for_time_range, get_assigned_counts_by_range

    now = datetime.now().isoformat()
    workloads = {
        "workload_status": max(0, int(workload_status)),
        "workload_qa": max(0, int(workload_qa)),
        "workload_ai_description": max(0, int(workload_ai_description)),
        "workload_review_description": max(0, int(workload_review_description)),
        "workload_english_description": max(0, int(workload_english_description)),
        "workload_accident_qa": max(0, int(workload_accident_qa)),
    }
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise ValueError("用户不存在")
        cursor.execute(
            """
            INSERT INTO user_time_ranges (
                user_id, range_name, start_time, end_time, created_at,
                workload_status, workload_qa, workload_ai_description,
                workload_review_description, workload_english_description, workload_accident_qa
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                range_name,
                start_time,
                end_time,
                now,
                workloads["workload_status"],
                workloads["workload_qa"],
                workloads["workload_ai_description"],
                workloads["workload_review_description"],
                workloads["workload_english_description"],
                workloads["workload_accident_qa"],
            ),
        )
        range_id = int(cursor.lastrowid)
    try:
        allocate_tasks_for_time_range(range_id)
    except Exception as exc:
        delete_time_range(range_id)
        raise ValueError(f"任务分配失败: {exc}") from exc
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, range_name, start_time, end_time, created_at,
                   workload_status, workload_qa, workload_ai_description,
                   workload_review_description, workload_english_description, workload_accident_qa
            FROM user_time_ranges WHERE id = %s
            """,
            (range_id,),
        )
        row = cursor.fetchone()
    return _time_range_row_to_dict(row, get_assigned_counts_by_range(range_id))


def _pending_workload_snapshot_to_api(row: Dict[str, Any], from_cache: bool) -> Dict[str, Any]:
    return {
        "statDate": str(row["stat_date"]),
        "startTime": str(row["start_time"]),
        "endTime": str(row["end_time"]),
        "computedAt": str(row["computed_at"]),
        "pendingStatus": int(row["pending_status"] or 0),
        "pendingQa": int(row["pending_qa"] or 0),
        "pendingAiDescription": int(row["pending_ai_description"] or 0),
        "pendingReviewDescription": int(row["pending_review_description"] or 0),
        "pendingEnglishDescription": int(row["pending_english_description"] or 0),
        "pendingAccidentQa": int(row["pending_accident_qa"] or 0),
        "fromCache": from_cache,
    }


def _get_pending_workload_snapshot_row(stat_date: str) -> Optional[Dict[str, Any]]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT stat_date, start_time, end_time, computed_at,
                   pending_status, pending_qa, pending_ai_description,
                   pending_review_description, pending_english_description, pending_accident_qa
            FROM pending_workload_daily_snapshots
            WHERE stat_date = %s
            LIMIT 1
            """,
            (stat_date,),
        )
        return cursor.fetchone()


def _upsert_pending_workload_snapshot(
    stat_date: str,
    start_time: str,
    end_time: str,
    computed_at: str,
    counts: Dict[str, int],
) -> Dict[str, Any]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO pending_workload_daily_snapshots (
                stat_date, start_time, end_time, computed_at,
                pending_status, pending_qa, pending_ai_description,
                pending_review_description, pending_english_description, pending_accident_qa
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                start_time = VALUES(start_time),
                end_time = VALUES(end_time),
                computed_at = VALUES(computed_at),
                pending_status = VALUES(pending_status),
                pending_qa = VALUES(pending_qa),
                pending_ai_description = VALUES(pending_ai_description),
                pending_review_description = VALUES(pending_review_description),
                pending_english_description = VALUES(pending_english_description),
                pending_accident_qa = VALUES(pending_accident_qa)
            """,
            (
                stat_date,
                start_time,
                end_time,
                computed_at,
                int(counts.get("status", 0)),
                int(counts.get("qa", 0)),
                int(counts.get("ai_description", 0)),
                int(counts.get("review_description", 0)),
                int(counts.get("english_description", 0)),
                int(counts.get("accident_qa", 0)),
            ),
        )
    row = _get_pending_workload_snapshot_row(stat_date)
    if not row:
        raise RuntimeError("待分配工作量快照写入失败")
    return row


def get_pending_workload_daily() -> Dict[str, Any]:
    """每日最多全量统计一次；当日已有快照则直接读库。"""
    from core.task_assignment import PENDING_WORKLOAD_START_TIME, compute_pending_workload_counts

    stat_date = datetime.now().strftime("%Y-%m-%d")
    cached = _get_pending_workload_snapshot_row(stat_date)
    if cached is not None:
        return _pending_workload_snapshot_to_api(cached, from_cache=True)

    counts, end_time = compute_pending_workload_counts()
    computed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = _upsert_pending_workload_snapshot(
        stat_date=stat_date,
        start_time=PENDING_WORKLOAD_START_TIME,
        end_time=end_time,
        computed_at=computed_at,
        counts=counts,
    )
    return _pending_workload_snapshot_to_api(saved, from_cache=False)


def delete_time_range(range_id: int) -> bool:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_time_ranges WHERE id = %s", (range_id,))
        return cursor.rowcount > 0


def create_session_token(user_id: int) -> str:
    payload = {
        "user_id": int(user_id),
        "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload_b64, signature = token.split(".", 1)
        expected = hmac.new(SESSION_SECRET.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        user = get_user_by_id(int(payload["user_id"]))
        if not user or not user["isActive"]:
            return None
        return user
    except Exception:
        return None


def upsert_event_review_record(
    event_id: str,
    project_id: str,
    event_type_code: str,
    reviewer: Dict[str, Any],
    status_review_done: bool,
    qa_review_done: bool,
    ai_description_done: bool,
    review_description_done: bool,
    english_description_done: bool,
    accident_qa_done: bool = True,
) -> Dict[str, Any]:
    now = datetime.now().isoformat()
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO event_review_records (
                event_id, project_id, event_type_code,
                reviewer_id, reviewer_username, reviewer_display_name, review_time,
                status_review_done, qa_review_done, description_review_done,
                ai_description_done, review_description_done, english_description_done,
                accident_qa_done,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                reviewer_id = VALUES(reviewer_id),
                reviewer_username = VALUES(reviewer_username),
                reviewer_display_name = VALUES(reviewer_display_name),
                review_time = VALUES(review_time),
                status_review_done = VALUES(status_review_done),
                qa_review_done = VALUES(qa_review_done),
                ai_description_done = VALUES(ai_description_done),
                review_description_done = VALUES(review_description_done),
                english_description_done = VALUES(english_description_done),
                accident_qa_done = VALUES(accident_qa_done),
                updated_at = VALUES(updated_at)
            """,
            (
                event_id,
                project_id,
                event_type_code,
                int(reviewer["id"]),
                reviewer["username"],
                reviewer.get("displayName") or reviewer["username"],
                now,
                1 if status_review_done else 0,
                1 if qa_review_done else 0,
                1 if ai_description_done else 0,
                1 if ai_description_done else 0,
                1 if review_description_done else 0,
                1 if english_description_done else 0,
                1 if accident_qa_done else 0,
                now,
                now,
            ),
        )
    return get_event_review_record(event_id, project_id, event_type_code) or {}


def get_event_review_record(event_id: str, project_id: str, event_type_code: str) -> Optional[Dict[str, Any]]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT *
            FROM event_review_records
            WHERE event_id = %s AND project_id = %s AND event_type_code = %s
            """,
            (event_id, project_id, event_type_code),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "reviewerId": int(row["reviewer_id"]),
            "reviewerUsername": row["reviewer_username"],
            "reviewerDisplayName": row["reviewer_display_name"] or row["reviewer_username"],
            "reviewTime": row["review_time"],
            "statusReviewDone": bool(row["status_review_done"]),
            "qaReviewDone": bool(row["qa_review_done"]),
            "descriptionReviewDone": bool(row.get("description_review_done")),
            "aiDescriptionDone": bool(row.get("ai_description_done")),
            "reviewDescriptionDone": bool(row.get("review_description_done")),
            "englishDescriptionDone": bool(row.get("english_description_done")),
            "accidentQaReviewDone": bool(row.get("accident_qa_done")),
        }


def get_event_review_records_for_keys(keys: List[tuple[str, str, str]]) -> Dict[tuple[str, str, str], Dict[str, Any]]:
    if not keys:
        return {}
    result: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        for event_id, project_id, event_type_code in keys:
            cursor.execute(
                """
                SELECT *
                FROM event_review_records
                WHERE event_id = %s AND project_id = %s AND event_type_code = %s
                """,
                (event_id, project_id, event_type_code),
            )
            row = cursor.fetchone()
            if row:
                result[(event_id, project_id, event_type_code)] = {
                    "reviewerId": int(row["reviewer_id"]),
                    "reviewerUsername": row["reviewer_username"],
                    "reviewerDisplayName": row["reviewer_display_name"] or row["reviewer_username"],
                    "reviewTime": row["review_time"],
                    "statusReviewDone": bool(row["status_review_done"]),
                    "qaReviewDone": bool(row["qa_review_done"]),
                    "descriptionReviewDone": bool(row.get("description_review_done")),
                    "aiDescriptionDone": bool(row.get("ai_description_done")),
                    "reviewDescriptionDone": bool(row.get("review_description_done")),
                    "englishDescriptionDone": bool(row.get("english_description_done")),
                    "accidentQaReviewDone": bool(row.get("accident_qa_done")),
                }
    return result


def get_review_stats() -> List[Dict[str, Any]]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                u.id AS user_id,
                u.username,
                u.display_name,
                COUNT(r.id) AS reviewed_events,
                SUM(CASE WHEN r.status_review_done = 1 THEN 1 ELSE 0 END) AS status_done,
                SUM(CASE WHEN r.qa_review_done = 1 THEN 1 ELSE 0 END) AS qa_done,
                SUM(CASE WHEN r.ai_description_done = 1 THEN 1 ELSE 0 END) AS ai_description_done,
                SUM(CASE WHEN r.review_description_done = 1 THEN 1 ELSE 0 END) AS review_description_done,
                SUM(CASE WHEN r.english_description_done = 1 THEN 1 ELSE 0 END) AS english_description_done,
                SUM(CASE WHEN r.accident_qa_done = 1 THEN 1 ELSE 0 END) AS accident_qa_done
            FROM users u
            LEFT JOIN event_review_records r ON r.reviewer_id = u.id
            WHERE u.role = 'reviewer'
            GROUP BY u.id, u.username, u.display_name
            ORDER BY u.id ASC
            """
        )
        return [
            {
                "userId": int(row["user_id"]),
                "username": row["username"],
                "displayName": row["display_name"] or row["username"],
                "reviewedEvents": int(row["reviewed_events"] or 0),
                "statusDone": int(row["status_done"] or 0),
                "qaDone": int(row["qa_done"] or 0),
                "aiDescriptionDone": int(row["ai_description_done"] or 0),
                "reviewDescriptionDone": int(row["review_description_done"] or 0),
                "englishDescriptionDone": int(row["english_description_done"] or 0),
                "accidentQaDone": int(row["accident_qa_done"] or 0),
            }
            for row in cursor.fetchall()
        ]


def _review_time_date_key_sql() -> str:
    """ISO8601 review_time → YYYYMMDD，与 SQLite strftime('%Y%m%d', ...) 对齐。"""
    return "REPLACE(SUBSTRING(r.review_time, 1, 10), '-', '')"


def get_review_stats_timeseries(
    *,
    month: Optional[str] = None,
    date_key: Optional[str] = None,
    date_hour: Optional[str] = None,
    filter_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """按时间粒度返回审核记录曲线数据，与 reid_tmp 中按月/按日/按小时维度对齐。

    - month: YYYYMM → X 轴为当月每一天
    - date_key: YYYYMMDD → X 轴为当天 24 小时
    - date_hour: YYYYMMDDHH → X 轴为该小时内 60 分钟

    review_time 存 ISO8601 字符串，按字符串截取分组（与原先 SQLite strftime 行为一致）。
    """
    modes = [month, date_key, date_hour]
    if sum(1 for m in modes if m) != 1:
        raise ValueError("必须且仅能指定 month、date、date_hour 之一")

    date_key_sql = _review_time_date_key_sql()

    if month:
        if len(month) != 6 or not month.isdigit():
            raise ValueError("month 须为 YYYYMM")
        year, mon = int(month[:4]), int(month[4:6])
        if mon < 1 or mon > 12:
            raise ValueError("月份无效")
        _, dim = calendar.monthrange(year, mon)
        sorted_labels = [f"{month}{str(d).zfill(2)}" for d in range(1, dim + 1)]
        labels = [f"{d:02d}日" for d in range(1, dim + 1)]
        group_sql = date_key_sql
        filter_sql = f"SUBSTRING({date_key_sql}, 1, 6) = %s"
        filter_param = month
        granularity = "month"
        chart_title = "每日审核事件数统计（按月）"
    elif date_key:
        if len(date_key) != 8 or not date_key.isdigit():
            raise ValueError("date 须为 YYYYMMDD")
        sorted_labels = [f"{date_key}{str(h).zfill(2)}" for h in range(24)]
        labels = [f"{h:02d}时" for h in range(24)]
        group_sql = f"CONCAT({date_key_sql}, SUBSTRING(r.review_time, 12, 2))"
        filter_sql = f"{date_key_sql} = %s"
        filter_param = date_key
        granularity = "day"
        chart_title = "每小时审核事件数统计（按日）"
    else:
        assert date_hour is not None
        if len(date_hour) != 10 or not date_hour.isdigit():
            raise ValueError("date_hour 须为 YYYYMMDDHH")
        sorted_labels = [f"{date_hour}{str(m).zfill(2)}" for m in range(60)]
        labels = [f"{m:02d}分" for m in range(60)]
        group_sql = (
            f"CONCAT({date_key_sql}, SUBSTRING(r.review_time, 12, 2), SUBSTRING(r.review_time, 15, 2))"
        )
        filter_sql = f"CONCAT({date_key_sql}, SUBSTRING(r.review_time, 12, 2)) = %s"
        filter_param = date_hour
        granularity = "hour"
        chart_title = "每分钟审核事件数统计（按小时）"

    datasets: List[Dict[str, Any]] = []

    with get_manage_db_connection() as conn:
        cursor = conn.cursor()

        def total_events_where(role_reviewer_only: bool) -> int:
            parts = [filter_sql]
            params: List[Any] = [filter_param]
            if role_reviewer_only:
                parts.append("u.role = 'reviewer'")
            if filter_user_id is not None:
                parts.append("r.reviewer_id = %s")
                params.append(filter_user_id)
            where = " AND ".join(parts)
            cursor.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM event_review_records r
                INNER JOIN users u ON u.id = r.reviewer_id
                WHERE {where}
                """,
                params,
            )
            row = cursor.fetchone()
            return int(row["c"] if row else 0)

        if filter_user_id is not None:
            cursor.execute(
                "SELECT id, username, display_name, role FROM users WHERE id = %s",
                (filter_user_id,),
            )
            urow = cursor.fetchone()
            if not urow:
                raise ValueError("用户不存在")
            display = (urow["display_name"] or urow["username"] or "").strip() or str(filter_user_id)

            parts = [filter_sql, "r.reviewer_id = %s"]
            params: List[Any] = [filter_param, filter_user_id]
            where = " AND ".join(parts)
            cursor.execute(
                f"""
                SELECT {group_sql} AS time_label,
                       SUM(CASE WHEN r.status_review_done = 1 THEN 1 ELSE 0 END) AS st,
                       SUM(CASE WHEN r.qa_review_done = 1 THEN 1 ELSE 0 END) AS qa,
                       SUM(CASE WHEN r.ai_description_done = 1 THEN 1 ELSE 0 END) AS ai_dsc,
                       SUM(CASE WHEN r.review_description_done = 1 THEN 1 ELSE 0 END) AS rev_dsc,
                       SUM(CASE WHEN r.english_description_done = 1 THEN 1 ELSE 0 END) AS en_dsc,
                       SUM(CASE WHEN r.accident_qa_done = 1 THEN 1 ELSE 0 END) AS acc_qa
                FROM event_review_records r
                WHERE {where}
                GROUP BY time_label
                ORDER BY time_label
                """,
                params,
            )
            rows = cursor.fetchall()
            by_label = {str(row["time_label"]): row for row in rows if row["time_label"] is not None}

            def metric_at(tl: str, col: str) -> int:
                row_bucket = by_label.get(tl)
                if row_bucket is None:
                    return 0
                return int(row_bucket[col] or 0)

            datasets = [
                {
                    "label": f"{display} (样本标记)",
                    "data": [metric_at(tl, "st") for tl in sorted_labels],
                },
                {
                    "label": f"{display} (问答)",
                    "data": [metric_at(tl, "qa") for tl in sorted_labels],
                },
                {
                    "label": f"{display} (AI描述)",
                    "data": [metric_at(tl, "ai_dsc") for tl in sorted_labels],
                },
                {
                    "label": f"{display} (审核描述)",
                    "data": [metric_at(tl, "rev_dsc") for tl in sorted_labels],
                },
                {
                    "label": f"{display} (英文描述)",
                    "data": [metric_at(tl, "en_dsc") for tl in sorted_labels],
                },
                {
                    "label": f"{display} (专项问答)",
                    "data": [metric_at(tl, "acc_qa") for tl in sorted_labels],
                },
            ]
            total_review_events = total_events_where(role_reviewer_only=False)
            participant_count = 1
        else:
            parts = [filter_sql, "u.role = 'reviewer'"]
            params: List[Any] = [filter_param]
            where_rev = " AND ".join(parts)
            cursor.execute(
                f"""
                SELECT r.reviewer_id, {group_sql} AS time_label, COUNT(*) AS cnt
                FROM event_review_records r
                INNER JOIN users u ON u.id = r.reviewer_id
                WHERE {where_rev}
                GROUP BY r.reviewer_id, time_label
                ORDER BY r.reviewer_id, time_label
                """,
                params,
            )
            raw = cursor.fetchall()
            by_user: Dict[int, Dict[str, int]] = {}
            for row in raw:
                uid = int(row["reviewer_id"])
                tl = str(row["time_label"])
                by_user.setdefault(uid, {})[tl] = int(row["cnt"])

            cursor.execute("SELECT id, username, display_name FROM users WHERE role = 'reviewer' ORDER BY id ASC")
            users_rows = cursor.fetchall()
            id_to_name = {
                int(r["id"]): (r["display_name"] or r["username"] or str(r["id"])).strip()
                for r in users_rows
            }
            for uid, counts in sorted(by_user.items(), key=lambda x: x[0]):
                name = id_to_name.get(uid, str(uid))
                datasets.append(
                    {
                        "label": f"{name} (审核事件数)",
                        "data": [counts.get(tl, 0) for tl in sorted_labels],
                    }
                )
            total_review_events = total_events_where(role_reviewer_only=True)
            participant_count = len(by_user)

        time_range_label = (
            f"{labels[0]} ~ {labels[-1]}" if labels else "无数据"
        )

    return {
        "labels": labels,
        "sortedLabels": sorted_labels,
        "datasets": datasets,
        "granularity": granularity,
        "chartTitle": chart_title,
        "totalReviewEvents": total_review_events,
        "participantCount": participant_count,
        "timeRangeLabel": time_range_label,
    }
