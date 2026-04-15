#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 search_results_all_*.json 中提取 filePath 并批量下载 MinIO 文件。

用法示例:
python3 scripts/download_minio_from_search_results.py \
  --json /opt/Traffic-LLM/zser/taglens-ai-app/data/minio_tmp/search_results_all_2026-04-14.json \
  --output /opt/Traffic-LLM/zser/taglens-ai-app/data/minio_tmp
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterator, Set


def _setup_import_path() -> None:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    backend_dir = project_root / "backend"
    sys.path.append(str(backend_dir))


def iter_file_paths(json_path: Path) -> Iterator[str]:
    """
    读取顶层为数组的 JSON，逐条产出 filePath。
    这里直接 json.load，逻辑简单稳定。
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("输入 JSON 顶层不是数组")

    for item in data:
        if not isinstance(item, dict):
            continue
        fp = item.get("filePath")
        if fp and isinstance(fp, str):
            yield fp


def download_from_filepaths(
    json_path: Path,
    output_dir: Path,
    skip_existing: bool = True,
    dry_run: bool = False,
) -> None:
    _setup_import_path()
    from core.minio_storage_client import get_storage_client  # type: ignore

    client_wrapper = get_storage_client(skip_bucket_check=True)
    minio_client = client_wrapper.client
    bucket = client_wrapper.bucket

    output_dir.mkdir(parents=True, exist_ok=True)

    seen: Set[str] = set()
    total = 0
    ok = 0
    failed = 0
    skipped = 0

    for obj_name in iter_file_paths(json_path):
        if obj_name in seen:
            continue
        seen.add(obj_name)
        total += 1

        local_path = output_dir / obj_name
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if skip_existing and local_path.exists():
            skipped += 1
            continue

        if dry_run:
            print(f"[DRY-RUN] {obj_name} -> {local_path}")
            continue

        try:
            minio_client.fget_object(bucket, obj_name, str(local_path))
            ok += 1
            if total % 100 == 0:
                print(f"已处理 {total} 条, 成功 {ok}, 跳过 {skipped}, 失败 {failed}")
        except Exception as e:
            failed += 1
            print(f"[失败] {obj_name}: {e}")

    print("==== 下载完成 ====")
    print(f"总对象数(去重后): {len(seen)}")
    print(f"成功: {ok}")
    print(f"跳过(已存在): {skipped}")
    print(f"失败: {failed}")
    print(f"输出目录: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="按搜索结果 JSON 批量下载 MinIO 文件")
    parser.add_argument(
        "--json",
        default="/opt/Traffic-LLM/zser/taglens-ai-app/data/minio_tmp/search_results_all_2026-04-08.json",
        help="search_results JSON 路径",
    )
    parser.add_argument(
        "--output",
        default="/opt/Traffic-LLM/zser/taglens-ai-app/data/minio_tmp",
        help="本地输出目录",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="不跳过已存在文件（默认跳过）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印将下载的对象，不实际下载",
    )
    args = parser.parse_args()

    json_path = Path(args.json).resolve()
    output_dir = Path(args.output).resolve()

    if not json_path.exists():
        raise FileNotFoundError(f"JSON 文件不存在: {json_path}")

    download_from_filepaths(
        json_path=json_path,
        output_dir=output_dir,
        skip_existing=not args.no_skip_existing,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
