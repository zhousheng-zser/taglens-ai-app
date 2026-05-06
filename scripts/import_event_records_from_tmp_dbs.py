from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Iterable


DEFAULT_TARGET_DB = Path("/opt/Traffic-LLM/zser/taglens-ai-app/data/event.db")
DEFAULT_SOURCE_DBS = [
    Path("/opt/Traffic-LLM/zser/taglens-ai-app/data/db_tmp/event_service.db"),
    Path("/opt/Traffic-LLM/zser/taglens-ai-app/data/db_tmp/event_service2.db"),
]
TABLE_NAME = "event_records"


def quote_ident(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def get_table_columns(conn: sqlite3.Connection, table_name: str, db_name: str = "main") -> list[str]:
    cursor = conn.execute(f"PRAGMA {quote_ident(db_name)}.table_info({quote_ident(table_name)})")
    rows = cursor.fetchall()
    return [str(row[1]) for row in rows]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "将多个 SQLite 源库的 event_records 表导入目标库，"
            "按目标表字段对齐：目标有则导入，源缺失补 NULL，源多余忽略。"
        )
    )
    parser.add_argument(
        "--target-db",
        type=Path,
        default=DEFAULT_TARGET_DB,
        help=f"目标数据库路径（默认: {DEFAULT_TARGET_DB}）",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        nargs="+",
        default=DEFAULT_SOURCE_DBS,
        help="源数据库路径列表（可传多个）",
    )
    parser.add_argument(
        "--table",
        default=TABLE_NAME,
        help=f"要导入的表名（默认: {TABLE_NAME}）",
    )
    parser.add_argument(
        "--mode",
        choices=["ignore", "abort"],
        default="ignore",
        help="主键/唯一键冲突时处理方式：ignore=跳过冲突行，abort=报错终止（默认: ignore）",
    )
    return parser.parse_args()


def validate_paths(target_db: Path, sources: Iterable[Path]) -> None:
    if not target_db.exists():
        raise FileNotFoundError(f"目标数据库不存在: {target_db}")
    for src in sources:
        if not src.exists():
            raise FileNotFoundError(f"源数据库不存在: {src}")


def import_one_source(
    conn: sqlite3.Connection,
    source_db: Path,
    table_name: str,
    target_columns: list[str],
    mode: str,
) -> int:
    before = conn.total_changes
    attach_name = "srcdb"

    conn.execute(f"ATTACH DATABASE ? AS {quote_ident(attach_name)}", (str(source_db),))
    try:
        source_columns = get_table_columns(conn, table_name, attach_name)
        if not source_columns:
            raise RuntimeError(f"源库缺少表 {table_name}: {source_db}")

        insert_columns = ", ".join(quote_ident(col) for col in target_columns)
        select_exprs = []
        source_set = set(source_columns)
        for col in target_columns:
            if col in source_set:
                select_exprs.append(f"{quote_ident(attach_name)}.{quote_ident(table_name)}.{quote_ident(col)}")
            else:
                select_exprs.append(f"NULL AS {quote_ident(col)}")

        select_sql = ", ".join(select_exprs)
        conflict_clause = "OR IGNORE " if mode == "ignore" else ""
        sql = (
            f"INSERT {conflict_clause}INTO {quote_ident(table_name)} ({insert_columns}) "
            f"SELECT {select_sql} FROM {quote_ident(attach_name)}.{quote_ident(table_name)}"
        )
        conn.execute(sql)
        conn.commit()
    finally:
        conn.execute(f"DETACH DATABASE {quote_ident(attach_name)}")

    return conn.total_changes - before


def main() -> None:
    args = parse_args()
    validate_paths(args.target_db, args.sources)

    conn = sqlite3.connect(str(args.target_db))
    try:
        target_columns = get_table_columns(conn, args.table, "main")
        if not target_columns:
            raise RuntimeError(f"目标库缺少表 {args.table}: {args.target_db}")

        print(f"目标库: {args.target_db}")
        print(f"目标表: {args.table}")
        print(f"目标字段数: {len(target_columns)}")
        print("-" * 60)

        total_inserted = 0
        for source_db in args.sources:
            inserted = import_one_source(
                conn=conn,
                source_db=source_db,
                table_name=args.table,
                target_columns=target_columns,
                mode=args.mode,
            )
            total_inserted += inserted
            print(f"源库导入完成: {source_db}")
            print(f"本次新增行数: {inserted}")
            print("-" * 60)

        print(f"全部完成，总新增行数: {total_inserted}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
