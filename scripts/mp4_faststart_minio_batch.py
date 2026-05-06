#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量将 MinIO 桶内 MP4 转为 faststart（moov 前移，仅重封装 -c copy）。

依赖：已安装 ffmpeg；Python 使用 backend 虚拟环境（含 minio）。

示例：
  cd /opt/Traffic-LLM/zser/taglens-ai-app
  source backend/venv/bin/activate
  python3 scripts/mp4_faststart_minio_batch.py --dry-run
  python3 scripts/mp4_faststart_minio_batch.py --prefix event_data/ --limit 5
  python3 scripts/mp4_faststart_minio_batch.py --prefix event_data/

连接信息与 backend 一致，可在 backend/.env 中配置 MINIO_ACCESS_KEY 等。
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
backend_dir = project_root / "backend"
sys.path.append(str(backend_dir / "core"))

try:
    import dotenv

    env_path = backend_dir / ".env"
    if env_path.exists():
        dotenv.load_dotenv(env_path)
except ImportError:
    pass

try:
    from minio_storage_client import MinIOStorageClient
except ImportError as e:
    print(f"错误: 无法导入 minio_storage_client: {e}", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MinIO MP4 批量 faststart（movflags +faststart）")
    p.add_argument(
        "--prefix",
        default="event_data/",
        help="只处理该前缀下的对象（默认 event_data/）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出将检查的 mp4 路径，不写回 MinIO",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多检查多少个 mp4（0=不限制；含跳过与失败）",
    )
    p.add_argument(
        "--no-skip-faststart-ok",
        action="store_true",
        help="对已明显 faststart 的文件仍强制跑 ffmpeg",
    )
    p.add_argument(
        "--stop-on-error",
        action="store_true",
        help="任一失败则立即退出",
    )
    p.add_argument(
        "--ffmpeg",
        default="ffmpeg",
        help="ffmpeg 可执行文件路径",
    )
    return p.parse_args()


def top_level_moov_before_mdat(data: bytes) -> bool | None:
    """
    解析 data 中顶层 box：若先于 mdat 见到 moov 则 True；
    若先于 moov 见到 mdat 则 False；缓冲内无法断定则 None。
    """
    pos = 0
    while pos + 8 <= len(data):
        size = struct.unpack(">I", data[pos : pos + 4])[0]
        typ = data[pos + 4 : pos + 8]
        if size < 8:
            return None
        if typ == b"moov":
            return True
        if typ == b"mdat":
            return False
        if typ in (b"ftyp", b"free", b"uuid", b"sidx", b"styp", b"prft", b"skip"):
            if size > len(data) - pos:
                return None
            pos += size
            continue
        if size > len(data) - pos:
            return None
        pos += size
    return None


def file_looks_faststart(path: Path, read_bytes: int = 512 * 1024) -> bool:
    with open(path, "rb") as f:
        chunk = f.read(read_bytes)
    r = top_level_moov_before_mdat(chunk)
    return r is True


def run_ffmpeg(ffmpeg: str, src: Path, dst: Path) -> None:
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(dst),
        ],
        check=True,
        timeout=7200,
    )


def main() -> int:
    args = parse_args()
    continue_on_error = not args.stop_on_error

    storage = MinIOStorageClient(skip_bucket_check=True)
    client = storage.client
    bucket = storage.bucket

    prefix = args.prefix
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"

    examined = 0
    written = 0
    skipped_fs = 0
    skipped_other = 0
    failed = 0
    t0 = time.time()

    ffmpeg_bin = shutil.which(args.ffmpeg) or args.ffmpeg

    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        name = obj.object_name
        if not name.lower().endswith(".mp4"):
            skipped_other += 1
            continue

        if args.limit and examined >= args.limit:
            break
        examined += 1

        print(f"[{examined}] {name}", flush=True)

        if args.dry_run:
            continue

        tmpdir = tempfile.mkdtemp(prefix="mp4_fs_")
        src = Path(tmpdir) / "in.mp4"
        dst = Path(tmpdir) / "out.mp4"
        try:
            client.fget_object(bucket, name, str(src))
            if not args.no_skip_faststart_ok and file_looks_faststart(src):
                print(f"  skip (already faststart)", flush=True)
                skipped_fs += 1
                continue

            run_ffmpeg(ffmpeg_bin, src, dst)
            if not dst.is_file() or dst.stat().st_size < 1024:
                raise RuntimeError("ffmpeg 输出异常过小或缺失")

            client.fput_object(
                bucket,
                name,
                str(dst),
                content_type="video/mp4",
            )
            print(f"  ok -> {dst.stat().st_size} bytes written", flush=True)
            written += 1
        except Exception as e:
            failed += 1
            print(f"  FAIL: {e}", file=sys.stderr, flush=True)
            if not continue_on_error:
                return 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    elapsed = time.time() - t0
    print(
        f"\n完成: 检查 mp4 {examined} 个, 写回 {written} 个, "
        f"跳过已 faststart {skipped_fs}, 跳过非 mp4 {skipped_other}, "
        f"失败 {failed}, 用时 {elapsed:.1f}s",
        flush=True,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
