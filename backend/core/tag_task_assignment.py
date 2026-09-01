"""标签审核员任务分配：按图片数量从未分配池抽取 uuid。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from core.database import get_db_connection
from core.manage_database import get_manage_db_connection

TAG_EXTRACTED_SQL = (
    "ar.description IS NOT NULL AND TRIM(ar.description) <> ''"
)


def _get_all_assigned_image_uuids() -> Set[str]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT image_uuid FROM tag_task_assignments")
        return {str(row["image_uuid"]) for row in cursor.fetchall()}


def get_tag_pending_workload_count() -> int:
    assigned = _get_all_assigned_image_uuids()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if assigned:
            placeholders = ",".join(["%s"] * len(assigned))
            cursor.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM images i
                INNER JOIN analysis_results ar ON ar.image_id = i.id
                WHERE {TAG_EXTRACTED_SQL}
                  AND i.uuid NOT IN ({placeholders})
                """,
                list(assigned),
            )
        else:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM images i
                INNER JOIN analysis_results ar ON ar.image_id = i.id
                WHERE {TAG_EXTRACTED_SQL}
                """
            )
        return int(cursor.fetchone()["cnt"] or 0)


def _fetch_candidate_images(quota: int, assigned: Set[str]) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if assigned:
            placeholders = ",".join(["%s"] * len(assigned))
            cursor.execute(
                f"""
                SELECT i.id, i.uuid
                FROM images i
                INNER JOIN analysis_results ar ON ar.image_id = i.id
                WHERE {TAG_EXTRACTED_SQL}
                  AND i.uuid NOT IN ({placeholders})
                ORDER BY i.id ASC
                LIMIT %s
                """,
                list(assigned) + [quota],
            )
        else:
            cursor.execute(
                f"""
                SELECT i.id, i.uuid
                FROM images i
                INNER JOIN analysis_results ar ON ar.image_id = i.id
                WHERE {TAG_EXTRACTED_SQL}
                ORDER BY i.id ASC
                LIMIT %s
                """,
                (quota,),
            )
        return cursor.fetchall()


def get_tag_assigned_counts_by_batch(batch_id: int) -> int:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM tag_task_assignments WHERE batch_id = %s",
            (batch_id,),
        )
        return int(cursor.fetchone()["cnt"] or 0)


def get_tag_assigned_uuids(user_id: int, batch_id: int) -> List[str]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT image_uuid
            FROM tag_task_assignments
            WHERE user_id = %s AND batch_id = %s
            ORDER BY id ASC
            """,
            (user_id, batch_id),
        )
        return [str(row["image_uuid"]) for row in cursor.fetchall()]


def is_tag_image_editable_by_user(user_id: int, image_uuid: str) -> bool:
    image_uuid = (image_uuid or "").strip()
    if not image_uuid:
        return False
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id FROM tag_task_assignments
            WHERE user_id = %s AND image_uuid = %s
            LIMIT 1
            """,
            (user_id, image_uuid),
        )
        return cursor.fetchone() is not None


def get_tag_batch_for_user(user_id: int, batch_id: int) -> Optional[Dict[str, Any]]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, range_name, workload_images, created_at
            FROM tag_user_task_batches
            WHERE id = %s AND user_id = %s
            """,
            (batch_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": int(row["id"]),
            "userId": int(row["user_id"]),
            "rangeName": row["range_name"],
            "workloadImages": int(row.get("workload_images") or 0),
            "createdAt": row["created_at"],
        }


def allocate_tag_images_for_batch(batch_id: int) -> Dict[str, Any]:
    with get_manage_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, user_id, workload_images
            FROM tag_user_task_batches
            WHERE id = %s
            """,
            (batch_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("标签任务批次不存在")

    quota = int(row["workload_images"] or 0)
    user_id = int(row["user_id"])
    if quota <= 0:
        return {"assignedImages": 0}

    assigned = _get_all_assigned_image_uuids()
    candidates = _fetch_candidate_images(quota, assigned)
    now = datetime.now().isoformat()
    warning: Optional[str] = None
    if len(candidates) < quota:
        warning = f"请求分配 {quota} 张，标签提取成功且未分配的仅剩 {len(candidates)} 张"

    if candidates:
        inserts = [
            (user_id, batch_id, str(item["uuid"]), int(item["id"]), now)
            for item in candidates
        ]
        with get_manage_db_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT INTO tag_task_assignments (
                    user_id, batch_id, image_uuid, image_id, created_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                inserts,
            )

    result: Dict[str, Any] = {"assignedImages": len(candidates)}
    if warning:
        result["warning"] = warning
    return result
