#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据同目录下的 uuid_vei_ubi_short_id.txt（事件 ID + MySQL 相机短编号），
结合项目根 data/business_structure_map.json，回填 SQLite images 表：

  camera_id, sz_name, sz_tag_ref_json

写入格式与 scripts/backfill_camera_metadata_ocr.py 中 update_image_metadata 一致：
  - sz_tag_ref_json 为 JSON 数组字符串，元素来自映射表 szTagRef1/2/3（非空项）。

按 file_path 中文件名解析事件 ID：{uuid}_{事件id}.jpg，与 export_empty_sz_uuids_by_path.py 一致。
默认只处理 file_path 包含「视频质量诊断」的图片，且默认仅更新 sz_name 为空的记录。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def extract_vqd_event_id_from_file_path(file_path: str) -> Optional[str]:
    stem = Path(file_path).stem
    if "_" not in stem:
        return None
    _h, _s, tail = stem.rpartition("_")
    if not tail or not tail.isdigit():
        return None
    return tail


def load_tsv_event_to_short(path: Path) -> Dict[str, str]:
    """事件 ID -> 相机短编号（字符串）；跳过空短编号。"""
    out: Dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if i == 0 and "vei_ubi_vqd_event_id" in line and "\t" in line:
            continue
        if "\t" not in line:
            continue
        eid, sid = line.split("\t", 1)
        eid, sid = eid.strip(), sid.strip()
        if not eid or not sid:
            continue
        out[eid] = sid
    return out


def map_entry_to_fields(entry: dict) -> Optional[Tuple[str, List[str]]]:
    """与 BusinessStructureMatcher._load 一致：sz_name + tag 列表。"""
    sz_name = str(entry.get("sz_name") or "").strip()
    if not sz_name:
        return None
    tag_refs = [
        str(entry.get(key)).strip()
        for key in ("szTagRef1", "szTagRef2", "szTagRef3")
        if str(entry.get(key) or "").strip()
    ]
    return sz_name, tag_refs


def load_business_map(path: Path) -> Dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def update_image_row(
    cur: sqlite3.Cursor,
    image_id: int,
    camera_id: str,
    sz_name: str,
    sz_tag_refs: List[str],
    updated_at: str,
) -> None:
    cur.execute(
        """
        UPDATE images
        SET camera_id = ?, sz_name = ?, sz_tag_ref_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            camera_id,
            sz_name,
            json.dumps(sz_tag_refs, ensure_ascii=False),
            updated_at,
            image_id,
        ),
    )


def main() -> None:
    root = project_root()
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="从 VQD TSV + 业务映射回填 images 相机元数据")
    parser.add_argument(
        "--tsv",
        type=Path,
        default=here / "uuid_vei_ubi_short_id.txt",
        help="事件ID与相机短编号 TSV（默认同脚本目录）",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=root / "data" / "taglens.db",
        help="SQLite 数据库",
    )
    parser.add_argument(
        "--map",
        type=Path,
        default=root / "data" / "business_structure_map.json",
        help="业务结构映射 JSON",
    )
    parser.add_argument(
        "--path-substring",
        default="视频质量诊断",
        help="只处理 file_path 包含该子串的记录（空字符串表示不限制）",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="即使已有 sz_name 也更新（默认仅 sz_name 为空时更新）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计不写库",
    )
    args = parser.parse_args()

    if not args.tsv.is_file():
        raise SystemExit(f"找不到 TSV: {args.tsv}")
    if not args.db.is_file():
        raise SystemExit(f"找不到数据库: {args.db}")
    if not args.map.is_file():
        raise SystemExit(f"找不到映射文件: {args.map}")

    event_to_short = load_tsv_event_to_short(args.tsv)
    biz = load_business_map(args.map)

    conn = sqlite3.connect(str(args.db))
    try:
        cur = conn.cursor()
        sub = (args.path_substring or "").strip()
        if sub:
            cur.execute(
                "SELECT id, file_path, sz_name FROM images WHERE file_path LIKE ?",
                (f"%{sub}%",),
            )
        else:
            cur.execute("SELECT id, file_path, sz_name FROM images")

        # 事件 ID -> 待处理的图片行（不过滤 sz_name，避免 TSV 有事件但误判为「库中无图」）
        event_to_rows: Dict[str, List[Tuple[int, Optional[str]]]] = {}
        for image_id, fp, sz_name in cur.fetchall():
            eid = extract_vqd_event_id_from_file_path(fp or "")
            if not eid:
                continue
            event_to_rows.setdefault(eid, []).append((image_id, sz_name))

        updated = 0
        skipped_no_image = 0
        skipped_no_short_in_tsv = 0
        skipped_no_map = 0
        skipped_already_has_sz_name = 0
        sample_unmapped_short: set[str] = set()

        now = datetime.now().isoformat()

        for eid, short_raw in event_to_short.items():
            rows = event_to_rows.get(eid)
            if not rows:
                skipped_no_image += 1
                continue
            short_key = str(short_raw).strip()
            if not short_key:
                skipped_no_short_in_tsv += 1
                continue
            entry = biz.get(short_key)
            if entry is None:
                skipped_no_map += 1
                if len(sample_unmapped_short) < 20:
                    sample_unmapped_short.add(short_key)
                continue
            parsed = map_entry_to_fields(entry)
            if not parsed:
                skipped_no_map += 1
                continue
            sz_name, tag_refs = parsed
            for image_id, sz_name_old in rows:
                if (
                    not args.overwrite
                    and sz_name_old is not None
                    and str(sz_name_old).strip()
                ):
                    skipped_already_has_sz_name += 1
                    continue
                if not args.dry_run:
                    update_image_row(cur, image_id, short_key, sz_name, tag_refs, now)
                updated += 1

        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(f"TSV: {args.tsv}（事件条数 {len(event_to_short)}）")
    print(f"数据库: {args.db}")
    print(f"映射: {args.map}")
    print(f"path 过滤: {sub or '(无)'}；overwrite={args.overwrite}；dry_run={args.dry_run}")
    if args.dry_run:
        print("dry-run：未写入")
    print(f"更新行数（按 image 行计）: {updated}")
    print(f"TSV 中事件在库中无匹配图片: {skipped_no_image}")
    print(f"TSV 中短编号为空跳过: {skipped_no_short_in_tsv}")
    print(f"短编号在 business_structure_map 无条目或 sz_name 为空: {skipped_no_map}")
    print(f"已有 sz_name 且未开 --overwrite 跳过: {skipped_already_has_sz_name}")
    if sample_unmapped_short:
        print(
            "无映射短编号样例（最多 20 个）: "
            + ", ".join(sorted(sample_unmapped_short)[:20])
        )


if __name__ == "__main__":
    main()
