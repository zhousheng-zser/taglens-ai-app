"""审核员任务分配：按时间段 + 六类工作量配额分配事件。

去重规则：
- 同一任务类别（如专项问答）全局只能分给一个审核员（数据库唯一约束 + 分配时跳过）。
- 同一事件若已分给某审核员（任意类别），不会再分给其他审核员。
- 同一审核员可在同一事件上承担多个类别任务（如样本 + 问答）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from core.event_database import (
    MULTI_CAR_ACCIDENT_EVENT_CODE,
    ABNORMAL_PARKING_EVENT_CODE,
    _get_special_qa_questions,
    _parse_accident_questions_answers_2d,
    _parse_json_string_list,
    _parse_questions_answers_2d,
    _parse_segment_text_list,
    get_event_db_connection,
)
from core.manage_database import get_manage_db_connection

EventKey = Tuple[str, str, str]

TASK_CATEGORIES: List[str] = [
    "status",
    "qa",
    "ai_description",
    "review_description",
    "english_description",
    "accident_qa",
]

WORKLOAD_COLUMNS: Dict[str, str] = {
    "status": "workload_status",
    "qa": "workload_qa",
    "ai_description": "workload_ai_description",
    "review_description": "workload_review_description",
    "english_description": "workload_english_description",
    "accident_qa": "workload_accident_qa",
}


def _event_needs_category(
    category: str,
    event_type_code: str,
    segment_count: int,
    segment_statuses: List[str],
    questions_answers_list: List[List[Dict[str, str]]],
    segment_descriptions: List[str],
    segment_review_descriptions: List[str],
    segment_descriptions_en: List[str],
    accident_questions_answers_list: List[List[Dict[str, str]]],
) -> bool:
    if segment_count <= 0:
        return False
    statuses = (segment_statuses or [])[:segment_count]
    if category == "status":
        return any(s not in {"正样本", "负样本"} for s in statuses)
    if category == "qa":
        if len(questions_answers_list) < segment_count:
            return True
        for segment_items in questions_answers_list[:segment_count]:
            if not segment_items:
                return True
            for qa in segment_items:
                if not str(qa.get("question", "")).strip() or not str(qa.get("answer", "")).strip():
                    return True
        return False
    if category == "ai_description":
        desc = (segment_descriptions or [])[:segment_count]
        return len(desc) < segment_count or not all(bool((t or "").strip()) for t in desc)
    if category == "review_description":
        desc = (segment_review_descriptions or [])[:segment_count]
        return len(desc) < segment_count or not all(bool((t or "").strip()) for t in desc)
    if category == "english_description":
        desc = (segment_descriptions_en or [])[:segment_count]
        return len(desc) < segment_count or not all(bool((t or "").strip()) for t in desc)
    if category == "accident_qa":
        code = str(event_type_code or "").strip()
        if code not in {MULTI_CAR_ACCIDENT_EVENT_CODE, ABNORMAL_PARKING_EVENT_CODE}:
            return False
        questions = _get_special_qa_questions(code)
        if not questions:
            return False
        positive_indexes = [i for i, s in enumerate(statuses) if s == "正样本"]
        if not positive_indexes:
            return False
        if len(accident_questions_answers_list) < segment_count:
            return True
        for idx in positive_indexes:
            segment_items = accident_questions_answers_list[idx] or []
            if len(segment_items) < len(questions):
                return True
            for question, qa in zip(questions, segment_items):
                if str(qa.get("question", "")).strip() != question:
                    return True
                if not str(qa.get("answer", "")).strip():
                    return True
        return False
    return False


def _iter_candidate_rows(
    start_time: str,
    end_time: str,
    category: str,
    batch_size: int = 5000,
):
    """按类别分批拉取候选事件；专项问答在 SQL 层预筛类型与正样本，避免只扫前 N 条漏分配。"""
    offset = 0
    extra_sql = ""
    extra_params: List[Any] = []
    if category == "accident_qa":
        extra_sql = (
            " AND event_type_corrected IN (%s, %s)"
            " AND segment_statuses_json LIKE %s"
        )
        extra_params = [
            MULTI_CAR_ACCIDENT_EVENT_CODE,
            ABNORMAL_PARKING_EVENT_CODE,
            "%正样本%",
        ]

    while True:
        with get_event_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT
                    event_id,
                    project_id,
                    event_type_corrected,
                    start_time,
                    segment_count,
                    segment_statuses_json,
                    questions_answers_list,
                    segment_descriptions_json,
                    segment_review_descriptions_json,
                    segment_descriptions_en_json,
                    accident_questions_answers_json
                FROM event_records
                WHERE start_time >= %s AND start_time <= %s
                {extra_sql}
                ORDER BY start_time ASC, event_id ASC
                LIMIT %s OFFSET %s
                """,
                (start_time, end_time, *extra_params, batch_size, offset),
            )
            rows = list(cursor.fetchall())
        if not rows:
            break
        yield rows
        offset += len(rows)
        if len(rows) < batch_size:
            break


def _fetch_candidate_rows(start_time: str, end_time: str, scan_limit: int = 20000) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for batch in _iter_candidate_rows(start_time, end_time, category="", batch_size=scan_limit):
        rows.extend(batch)
        if len(rows) >= scan_limit:
            return rows[:scan_limit]
    return rows


def get_assigned_categories_map_for_user(
    user_id: int,
    keys: List[EventKey],
) -> Dict[EventKey, List[str]]:
    if not keys:
        return {}
    result: Dict[EventKey, List[str]] = {}
    clauses: List[str] = []
    params: List[Any] = [user_id]
    for event_id, project_id, event_type_code in keys:
        clauses.append("(event_id = %s AND project_id = %s AND event_type_code = %s)")
        params.extend([event_id, project_id, event_type_code])
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT event_id, project_id, event_type_code, task_category
            FROM event_task_assignments
            WHERE user_id = %s AND ({' OR '.join(clauses)})
            """,
            params,
        )
        for row in cursor.fetchall():
            key: EventKey = (
                str(row["event_id"]),
                str(row["project_id"]),
                str(row["event_type_code"]),
            )
            result.setdefault(key, []).append(str(row["task_category"]))
    for key, categories in result.items():
        result[key] = sorted(set(categories))
    return result


def get_reviewer_editable_categories(
    user_id: int,
    role: str,
    event_id: str,
    project_id: str,
    event_type_code: str,
) -> Optional[Set[str]]:
    if role == "admin":
        return None
    key: EventKey = (str(event_id), str(project_id), str(event_type_code))
    categories = get_assigned_categories_map_for_user(user_id, [key]).get(key)
    if categories:
        return set(categories)
    return None


def get_assigned_keys_for_category(category: str) -> Set[EventKey]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_id, project_id, event_type_code
            FROM event_task_assignments
            WHERE task_category = %s
            """,
            (category,),
        )
        return {
            (str(row["event_id"]), str(row["project_id"]), str(row["event_type_code"]))
            for row in cursor.fetchall()
        }


def get_event_keys_assigned_to_other_users(user_id: int) -> Set[EventKey]:
    """其他审核员已分配的事件（任意任务类别），避免同一事件分给多人。"""
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT event_id, project_id, event_type_code
            FROM event_task_assignments
            WHERE user_id != %s
            """,
            (user_id,),
        )
        return {
            (str(row["event_id"]), str(row["project_id"]), str(row["event_type_code"]))
            for row in cursor.fetchall()
        }


def get_user_assigned_keys(user_id: int, time_range_id: int) -> Set[EventKey]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_id, project_id, event_type_code
            FROM event_task_assignments
            WHERE user_id = %s AND time_range_id = %s
            """,
            (user_id, time_range_id),
        )
        return {
            (str(row["event_id"]), str(row["project_id"]), str(row["event_type_code"]))
            for row in cursor.fetchall()
        }


def get_user_assigned_keys_for_category(
    user_id: int,
    time_range_id: int,
    category: str,
) -> Set[EventKey]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_id, project_id, event_type_code
            FROM event_task_assignments
            WHERE user_id = %s AND time_range_id = %s AND task_category = %s
            """,
            (user_id, time_range_id, category),
        )
        return {
            (str(row["event_id"]), str(row["project_id"]), str(row["event_type_code"]))
            for row in cursor.fetchall()
        }


def get_assigned_counts_by_range(time_range_id: int) -> Dict[str, int]:
    counts = {cat: 0 for cat in TASK_CATEGORIES}
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT task_category, COUNT(*) AS cnt
            FROM event_task_assignments
            WHERE time_range_id = %s
            GROUP BY task_category
            """,
            (time_range_id,),
        )
        for row in cursor.fetchall():
            cat = str(row["task_category"])
            if cat in counts:
                counts[cat] = int(row["cnt"] or 0)
    return counts


def time_range_has_workload(time_range: Dict[str, Any]) -> bool:
    pairs = [
        ("workloadStatus", "workload_status"),
        ("workloadQa", "workload_qa"),
        ("workloadAiDescription", "workload_ai_description"),
        ("workloadReviewDescription", "workload_review_description"),
        ("workloadEnglishDescription", "workload_english_description"),
        ("workloadAccidentQa", "workload_accident_qa"),
    ]
    for camel, snake in pairs:
        if int(time_range.get(camel) or time_range.get(snake) or 0) > 0:
            return True
    return False


def allocate_tasks_for_time_range(time_range_id: int) -> Dict[str, int]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, start_time, end_time,
                   workload_status, workload_qa, workload_ai_description,
                   workload_review_description, workload_english_description, workload_accident_qa
            FROM user_time_ranges
            WHERE id = %s
            """,
            (time_range_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("任务时间段不存在")

    workloads = {cat: int(row[WORKLOAD_COLUMNS[cat]] or 0) for cat in TASK_CATEGORIES}
    if not any(v > 0 for v in workloads.values()):
        return {cat: 0 for cat in TASK_CATEGORIES}

    cursor_execute_delete = time_range_id
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM event_task_assignments WHERE time_range_id = %s", (cursor_execute_delete,))

    allocated: Dict[str, int] = {cat: 0 for cat in TASK_CATEGORIES}
    now = datetime.now().isoformat()
    user_id = int(row["user_id"])
    blocked_by_other_users = get_event_keys_assigned_to_other_users(user_id)

    for category in TASK_CATEGORIES:
        quota = workloads[category]
        if quota <= 0:
            continue
        taken = get_assigned_keys_for_category(category)
        inserts: List[tuple] = []
        for batch in _iter_candidate_rows(row["start_time"], row["end_time"], category):
            for ev in batch:
                if allocated[category] >= quota:
                    break
                event_id = str(ev["event_id"])
                project_id = str(ev["project_id"])
                event_type_code = str(ev["event_type_corrected"] or "")
                key: EventKey = (event_id, project_id, event_type_code)
                if key in taken or key in blocked_by_other_users:
                    continue
                segment_count = int(ev["segment_count"] or 0)
                segment_statuses = _parse_json_string_list(ev["segment_statuses_json"])
                questions_answers_list = _parse_questions_answers_2d(
                    ev["questions_answers_list"],
                    segment_count=segment_count,
                    event_type_code=event_type_code,
                    event_id=event_id,
                )
                segment_descriptions = _parse_segment_text_list(ev["segment_descriptions_json"])
                segment_review_descriptions = _parse_segment_text_list(ev["segment_review_descriptions_json"])
                segment_descriptions_en = _parse_segment_text_list(ev["segment_descriptions_en_json"])
                accident_questions_answers_list = _parse_accident_questions_answers_2d(
                    ev.get("accident_questions_answers_json"),
                    segment_count=segment_count,
                    event_type_code=event_type_code,
                )
                if not _event_needs_category(
                    category,
                    event_type_code,
                    segment_count,
                    segment_statuses,
                    questions_answers_list,
                    segment_descriptions,
                    segment_review_descriptions,
                    segment_descriptions_en,
                    accident_questions_answers_list,
                ):
                    continue
                inserts.append((user_id, time_range_id, category, event_id, project_id, event_type_code, now))
                taken.add(key)
                allocated[category] += 1
            if allocated[category] >= quota:
                break

        if inserts:
            with get_manage_db_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    INSERT INTO event_task_assignments (
                        user_id, time_range_id, task_category,
                        event_id, project_id, event_type_code, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    inserts,
                )

    return allocated


PENDING_WORKLOAD_START_TIME = "2020-01-01 00:00:00"


def _parse_event_row_for_needs_check(ev: Dict[str, Any]) -> Tuple[EventKey, int, List[str], List[List[Dict[str, str]]], List[str], List[str], List[str], List[List[Dict[str, str]]]]:
    event_id = str(ev["event_id"])
    project_id = str(ev["project_id"])
    event_type_code = str(ev["event_type_corrected"] or "")
    key: EventKey = (event_id, project_id, event_type_code)
    segment_count = int(ev["segment_count"] or 0)
    segment_statuses = _parse_json_string_list(ev["segment_statuses_json"])
    questions_answers_list = _parse_questions_answers_2d(
        ev["questions_answers_list"],
        segment_count=segment_count,
        event_type_code=event_type_code,
        event_id=event_id,
    )
    segment_descriptions = _parse_segment_text_list(ev["segment_descriptions_json"])
    segment_review_descriptions = _parse_segment_text_list(ev["segment_review_descriptions_json"])
    segment_descriptions_en = _parse_segment_text_list(ev["segment_descriptions_en_json"])
    accident_questions_answers_list = _parse_accident_questions_answers_2d(
        ev.get("accident_questions_answers_json"),
        segment_count=segment_count,
        event_type_code=event_type_code,
    )
    return (
        key,
        segment_count,
        segment_statuses,
        questions_answers_list,
        segment_descriptions,
        segment_review_descriptions,
        segment_descriptions_en,
        accident_questions_answers_list,
    )


def compute_pending_workload_counts(
    start_time: str = PENDING_WORKLOAD_START_TIME,
    end_time: Optional[str] = None,
) -> Tuple[Dict[str, int], str]:
    """全量扫描统计待分配工作量（耗时较长，应由每日快照调用）。"""
    if not end_time:
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    assigned_by_category = {cat: get_assigned_keys_for_category(cat) for cat in TASK_CATEGORIES}
    counts: Dict[str, int] = {cat: 0 for cat in TASK_CATEGORIES}

    for batch in _iter_candidate_rows(start_time, end_time, category=""):
        for ev in batch:
            (
                key,
                segment_count,
                segment_statuses,
                questions_answers_list,
                segment_descriptions,
                segment_review_descriptions,
                segment_descriptions_en,
                accident_questions_answers_list,
            ) = _parse_event_row_for_needs_check(ev)
            for category in TASK_CATEGORIES:
                if key in assigned_by_category[category]:
                    continue
                if _event_needs_category(
                    category,
                    key[2],
                    segment_count,
                    segment_statuses,
                    questions_answers_list,
                    segment_descriptions,
                    segment_review_descriptions,
                    segment_descriptions_en,
                    accident_questions_answers_list,
                ):
                    counts[category] += 1

    return counts, end_time
