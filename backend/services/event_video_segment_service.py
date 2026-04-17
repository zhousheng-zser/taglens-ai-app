from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List


def normalize_object_key(path_value: str) -> str:
    normalized = (path_value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("/mnt/"):
        normalized = normalized[len("/mnt/") :]
    return normalized.lstrip("/")


def ensure_ffmpeg_available() -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError("系统未找到 ffmpeg 命令，请先安装 ffmpeg")


def split_video_to_segments(input_file: Path, output_pattern: Path) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_file),
        "-map",
        "0",
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        "60",
        "-reset_timestamps",
        "1",
        str(output_pattern),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg 分段失败")


def process_event_video_segmentation(
    minio_client,
    video_path: str,
) -> Dict[str, List[str]]:
    object_key = normalize_object_key(video_path)
    if not object_key:
        raise ValueError("video_path 为空，无法处理")

    video_name = Path(object_key).name
    stem = Path(video_name).stem
    parent = Path(object_key).parent.as_posix().strip("/")

    with tempfile.TemporaryDirectory(prefix="event-segment-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_file = tmp_path / video_name
        minio_client.download_file(object_key, str(source_file))
        if not source_file.exists():
            raise RuntimeError("源视频下载失败")

        output_pattern = tmp_path / f"{stem}_%03d.mp4"
        split_video_to_segments(source_file, output_pattern)

        local_segments = sorted(tmp_path.glob(f"{stem}_*.mp4"))
        if not local_segments:
            raise RuntimeError("未生成任何分段视频")

        segment_paths: List[str] = []
        for seg_file in local_segments:
            object_seg_key = f"{parent}/{seg_file.name}" if parent else seg_file.name
            minio_client.upload_file(str(seg_file), object_seg_key, content_type="video/mp4")
            segment_paths.append(f"/{object_seg_key}")

    segment_descriptions = ["" for _ in segment_paths]
    segment_statuses = ["待定" for _ in segment_paths]
    return {
        "segment_paths": segment_paths,
        "segment_descriptions": segment_descriptions,
        "segment_statuses": segment_statuses,
    }
