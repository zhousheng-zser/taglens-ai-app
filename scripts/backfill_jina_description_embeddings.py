#!/usr/bin/env python3
"""
将 taglens_taglens.analysis_results.description 转为 Jina CLIP 向量，
写入 description_embeddings 表。

用法:
  python scripts/backfill_jina_description_embeddings.py              # 默认 100 条
  python scripts/backfill_jina_description_embeddings.py --limit 0  # 全量（慎用）
  python scripts/backfill_jina_description_embeddings.py --limit 500 --offset 100
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from core.database import get_db_connection, init_database
from services.jina_embedding_service import (
    JINA_MODEL_NAME,
    encode_description_to_vector,
    get_jina_model,
)


def fetch_pending(cursor, limit: int, offset: int) -> list[dict]:
    sql = """
        SELECT ar.image_id, ar.description
        FROM analysis_results ar
        LEFT JOIN description_embeddings de ON de.image_id = ar.image_id
        WHERE de.id IS NULL
          AND ar.description IS NOT NULL
          AND TRIM(ar.description) <> ''
        ORDER BY ar.image_id
    """
    params: list = []
    if limit > 0:
        sql += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])
    cursor.execute(sql, params)
    return list(cursor.fetchall())


def upsert_embedding(cursor, image_id: int, blob: bytes, dim: int, now: str) -> None:
    cursor.execute(
        """
        INSERT INTO description_embeddings (
            image_id, embedding, dim, model_name, created_at
        ) VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            embedding = VALUES(embedding),
            dim = VALUES(dim),
            model_name = VALUES(model_name),
            created_at = VALUES(created_at)
        """,
        (image_id, blob, dim, JINA_MODEL_NAME, now),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 description Jina 向量")
    parser.add_argument("--limit", type=int, default=100, help="本次处理条数，0 表示不限制")
    parser.add_argument("--offset", type=int, default=0, help="跳过前 N 条待处理记录")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    args = parser.parse_args()

    print("初始化数据库表结构...")
    init_database()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        rows = fetch_pending(cursor, args.limit, args.offset)

    total = len(rows)
    print(f"待处理: {total} 条 (limit={args.limit}, offset={args.offset})")
    if total == 0:
        print("没有需要处理的记录。")
        return 0

    if args.dry_run:
        for i, row in enumerate(rows[:5], 1):
            desc = (row["description"] or "")[:80]
            print(f"  [{i}] image_id={row['image_id']} desc={desc!r}...")
        if total > 5:
            print(f"  ... 共 {total} 条")
        return 0

    print("加载 Jina CLIP 模型...")
    get_jina_model()

    ok, fail = 0, 0
    t0 = time.time()

    for idx, row in enumerate(rows, 1):
        image_id = int(row["image_id"])
        description = (row["description"] or "").strip()
        now = datetime.now().isoformat()
        try:
            blob, dim = encode_description_to_vector(description)
            with get_db_connection() as conn:
                cursor = conn.cursor()
                upsert_embedding(cursor, image_id, blob, dim, now)
            ok += 1
            if idx % 10 == 0 or idx == total:
                elapsed = time.time() - t0
                print(f"  进度 {idx}/{total}  成功={ok} 失败={fail}  耗时={elapsed:.1f}s")
        except Exception as exc:
            fail += 1
            print(f"  [失败] image_id={image_id}: {exc}")

    elapsed = time.time() - t0
    print(f"\n完成: 成功 {ok}, 失败 {fail}, 总耗时 {elapsed:.1f}s")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
