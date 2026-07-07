#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 MySQL taglens_taglens.images 表中导出 sz_name 为空的记录对应的「交委指挥中心事件 ID」，
按 file_path 是否包含关键字分别写入两个目录下的 txt（每行一个 ID）。

文件名约定（与实际上传路径一致）：
  .../{uuid}_{事件id}.jpg
  例如：.../076eb05e-1a16-4f1c-8c04-e92fb526d211_2040037689938243588.jpg
  其中事件 ID 为下划线后、扩展名前的纯数字段，对应 MySQL tbl_vqd_event_info.ubi_vqd_event_id。

注意：images.uuid 可能为应用生成的 UUID，与业务事件 ID 不一致，故不再导出 uuid 列。

默认关键字：
  - 目录「交委指挥中心」：file_path 包含「交委指挥中心」
  - 目录「浦东道运」：file_path 包含「浦东道运」

若同一条路径同时包含两个关键字，事件 ID 会同时写入两个文件。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "backend" / ".env")

from core.database import get_db_connection


def _empty_sz_condition() -> str:
    return "(sz_name IS NULL OR TRIM(sz_name) = '')"


def extract_vqd_event_id_from_file_path(file_path: str) -> str | None:
    """
    从路径 basename 解析 {任意前缀}_{纯数字}.(jpg|...) 中的事件 ID。
    使用「最后一个下划线」右侧作为候选，避免误伤其它命名。
    """
    stem = Path(file_path).stem
    if "_" not in stem:
        return None
    _head, _sep, tail = stem.rpartition("_")
    if not tail or not tail.isdigit():
        return None
    return tail


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="导出 sz_name 为空的记录的 VQD 事件 ID（从 file_path 文件名解析），按路径关键字分目录"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=root / "scripts" / "empty_sz_uuids_export",
        help="输出根目录（其下会建两个子文件夹）",
    )
    parser.add_argument(
        "--name-video",
        default="交委指挥中心",
        help="匹配 file_path 的子串（输出到子目录「交委指挥中心」）",
    )
    parser.add_argument(
        "--name-pudong",
        default="浦东道运",
        help="匹配 file_path 的子串（输出到子目录「浦东道运」）",
    )
    parser.add_argument(
        "--filename",
        default="uuids.txt",
        help="各子目录内生成的 txt 文件名（内容为事件 ID，默认名沿用历史 uuids.txt）",
    )
    args = parser.parse_args()

    sql = f"""
        SELECT file_path
        FROM images
        WHERE {_empty_sz_condition()}
    """

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()

    video_ids: set[str] = set()
    pudong_ids: set[str] = set()
    neither = 0
    parse_fail = 0

    for row in rows:
        fp = row["file_path"] or ""
        eid = extract_vqd_event_id_from_file_path(fp)
        if eid is None:
            parse_fail += 1
            continue

        in_video = args.name_video in fp
        in_pudong = args.name_pudong in fp
        if in_video:
            video_ids.add(eid)
        if in_pudong:
            pudong_ids.add(eid)
        if not in_video and not in_pudong:
            neither += 1

    out_root: Path = args.out_dir
    dir_video = out_root / args.name_video
    dir_pudong = out_root / args.name_pudong
    dir_video.mkdir(parents=True, exist_ok=True)
    dir_pudong.mkdir(parents=True, exist_ok=True)

    def write_sorted(path: Path, ids: set[str]) -> None:
        lines = "\n".join(sorted(ids, key=lambda x: int(x))) + ("\n" if ids else "")
        path.write_text(lines, encoding="utf-8")

    write_sorted(dir_video / args.filename, video_ids)
    write_sorted(dir_pudong / args.filename, pudong_ids)

    print("数据库: MySQL taglens_taglens")
    print(f"sz_name 为空的记录总数: {len(rows)}")
    print(f"无法从 file_path 解析事件 ID（无「_数字」后缀等）: {parse_fail} 条")
    print(f"「{args.name_video}」: {len(video_ids)} 条事件 ID -> {dir_video / args.filename}")
    print(f"「{args.name_pudong}」: {len(pudong_ids)} 条事件 ID -> {dir_pudong / args.filename}")
    print(f"未匹配任一关键字（未写入）: {neither} 条")


if __name__ == "__main__":
    main()
