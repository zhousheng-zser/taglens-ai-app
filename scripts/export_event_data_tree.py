"""
递归读取 MinIO 的 bucket-taglens/event_data 目录结构，并输出事件目录下的媒体文件清单。

“事件目录”定义：
- 仅将包含媒体文件（图片/视频）的最末级目录作为一个单位；
- 例如：bucket-taglens/event_data/WHJM-9096/106/202512/1995161217576189953_01_00_01_14_12/
- 不会把更上层目录（如 event_data/WHJM-9096/106/202512/）当作单位。

输出格式（文本文件，每行一个 JSON）：
{
  "folder": "bucket-taglens/event_data/WHJM-9096/106/202512/xxxx/",
  "images": ["bucket-taglens/event_data/.../a.jpg", ...],
  "videos": ["bucket-taglens/event_data/.../a.mp4", ...]
}
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v"}

TARGET_BUCKET = "bucket-taglens"
TARGET_PREFIX = "event_data/"


def setup_imports():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    backend_core_dir = project_root / "backend" / "core"
    backend_env = project_root / "backend" / ".env"

    sys.path.append(str(backend_core_dir))
    if backend_env.exists():
        load_dotenv(backend_env)

    try:
        from minio_storage_client import get_storage_client
    except ImportError as exc:
        raise RuntimeError(f"无法导入 minio_storage_client: {exc}") from exc

    return get_storage_client


def classify_object(object_name: str):
    suffix = Path(object_name).suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in VIDEO_EXTS:
        return "video"
    return None


def export_event_tree(output_file: Path):
    get_storage_client = setup_imports()
    client_wrapper = get_storage_client(skip_bucket_check=True)
    minio_client = client_wrapper.client

    print(f"开始扫描: {TARGET_BUCKET}/{TARGET_PREFIX}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    # 先清空文件，再流式追加
    output_file.write_text("", encoding="utf-8")

    total_objects = 0
    kept_media = 0
    written_folders = 0
    current_folder = None
    current_images: List[str] = []
    current_videos: List[str] = []

    def flush_current(writer):
        nonlocal written_folders, current_folder, current_images, current_videos
        if current_folder is None:
            return
        if not current_images and not current_videos:
            return
        record = {
            "folder": current_folder,
            "images": sorted(current_images),
            "videos": sorted(current_videos),
        }
        writer.write(json.dumps(record, ensure_ascii=False) + "\n")
        written_folders += 1

    # 边扫描边写（避免全量聚合占用内存）
    objects = minio_client.list_objects(TARGET_BUCKET, prefix=TARGET_PREFIX, recursive=True)
    with output_file.open("a", encoding="utf-8") as f:
        for obj in objects:
            if obj.is_dir:
                continue

            total_objects += 1
            object_name = obj.object_name
            media_type = classify_object(object_name)
            if media_type is None:
                continue

            kept_media += 1
            parent = Path(object_name).parent.as_posix().rstrip("/") + "/"
            folder_key = f"{TARGET_BUCKET}/{parent}"
            full_path = f"{TARGET_BUCKET}/{object_name}"

            # list_objects 通常按 object_name 升序输出，目录切换时可立即落盘
            if current_folder is None:
                current_folder = folder_key
            elif folder_key != current_folder:
                flush_current(f)
                current_folder = folder_key
                current_images = []
                current_videos = []

            if media_type == "image":
                current_images.append(full_path)
            else:
                current_videos.append(full_path)

        # 刷新最后一个目录
        flush_current(f)

    print("=" * 60)
    print(f"扫描对象数: {total_objects}")
    print(f"媒体文件数: {kept_media}")
    print(f"事件目录数: {written_folders}")
    print(f"输出文件: {output_file}")
    print("=" * 60)


if __name__ == "__main__":
    # 可通过环境变量 EVENT_TREE_OUTPUT 覆盖输出路径
    default_output = Path.cwd() / "event_data_tree.txt"
    output_path = Path(os.getenv("EVENT_TREE_OUTPUT", str(default_output)))
    export_event_tree(output_path)
