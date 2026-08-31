import os
import json
import tempfile
import threading
import base64
import re
import shutil
import hashlib
import time
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Union
from urllib import parse

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch
import numpy as np
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field
from transformers import AutoModel

# ==================== 配置 ====================
IMAGE_FOLDER = "./picture"          # 图片文件夹
INDEX_DIR = "./image_index"         # 索引保存目录
DATASETS_ROOT = "./datasets"        # 后续多图片集目录：datasets/<dataset_id>/
DATASET_INDEX_ROOT = "./image_indexes"
THUMB_ROOT = "./.thumbs"
VIDEO_ROOT = "./videos"
VIDEO_INDEX_ROOT = "./video_indexes"
VIDEO_FRAME_ROOT = "./video_frames"
DEFAULT_DATASET_ID = "default"
DATASET_DISPLAY_NAMES = {
    DEFAULT_DATASET_ID: "\u5c0f\u578b\u5ba2\u8f66\u56fe\u7247\u96c6",
    "road_monitor": "\u89c6\u9891\u76d1\u63a7\u56fe\u7247\u96c6",
    "passenger_freight": "\u5ba2\u8d27\u8f66\u56fe\u7247\u96c6",
    "vehicle_merged": "客货车图片集",
}
TRUNCATE_DIM = 2048                 # 嵌入维度
BATCH_SIZE = 24                     # 编码批次大小
CLIP_MODEL_PATH = "./jina-clip-v2"  # CLIP 模型路径
RERANKER_PATH = "./reranker"        # Reranker 模型路径
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MAX_IMAGE_SIZE_MB = 10              # 允许的最大图片大小（MB）
IMG_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
VIDEO_EXTS = {'.mp4'}
THUMB_MAX_SIZE = (320, 240)
THUMB_QUALITY = 78
DEFAULT_VIDEO_SAMPLE_FPS = 2.0
DEFAULT_SEGMENT_GAP_SECONDS = 1.0
RERANK_BATCH_SIZE = 8

# ==================== 全局锁 ====================
model_lock = threading.Lock()

def compute_rerank_scores(reranker, pairs, device, doc_type="image", query_type="text", max_length=2048, batch_size=RERANK_BATCH_SIZE):
    scores = []
    for i in range(0, len(pairs), batch_size):
        batch = pairs[i:i + batch_size]
        with torch.no_grad():
            batch_scores = reranker.compute_score(batch, max_length=max_length, doc_type=doc_type, query_type=query_type)
        if isinstance(batch_scores, (float, int)):
            batch_scores = [batch_scores]
        scores.extend(float(s) for s in batch_scores)
        if getattr(device, "type", "") == "cuda":
            torch.cuda.empty_cache()
    return scores

# ==================== 辅助函数 ====================
def collect_images(folder: str) -> List[str]:
    exts = ['*.jpg', '*.jpeg', '*.png', '*.webp', '*.bmp', '*.gif']
    paths = []
    for ext in exts:
        paths.extend(Path(folder).glob(ext))
        paths.extend(Path(folder).glob(ext.upper()))
    seen = set()
    unique_paths = []
    for p in paths:
        p_str = str(p.resolve())
        if p_str not in seen:
            seen.add(p_str)
            unique_paths.append(p_str)
    return sorted(unique_paths)

def collect_videos(folder: str) -> List[str]:
    root = Path(folder)
    if not root.exists():
        return []
    paths = []
    for ext in VIDEO_EXTS:
        paths.extend(root.rglob(f"*{ext}"))
        paths.extend(root.rglob(f"*{ext.upper()}"))
    seen = set()
    unique_paths = []
    for p in paths:
        p_str = str(p.resolve())
        if p_str not in seen:
            seen.add(p_str)
            unique_paths.append(p_str)
    return sorted(unique_paths)

def count_images_recursive(folder: str) -> int:
    root = Path(folder)
    if not root.exists():
        return 0
    return sum(1 for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMG_EXTS)

def list_frame_files_recursive(folder: str) -> List[Path]:
    root = Path(folder)
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMG_EXTS)

def dataset_folder(dataset_id: str = DEFAULT_DATASET_ID) -> Path:
    dataset_id = normalize_dataset_id(dataset_id)
    if dataset_id == DEFAULT_DATASET_ID:
        return Path(IMAGE_FOLDER).resolve()
    return (Path(DATASETS_ROOT) / dataset_id).resolve()

def dataset_index_dir(dataset_id: str = DEFAULT_DATASET_ID) -> Path:
    dataset_id = normalize_dataset_id(dataset_id)
    if dataset_id == DEFAULT_DATASET_ID:
        return Path(INDEX_DIR).resolve()
    return (Path(DATASET_INDEX_ROOT) / dataset_id).resolve()

def video_dataset_folder(dataset_id: str = DEFAULT_DATASET_ID) -> Path:
    dataset_id = normalize_dataset_id(dataset_id)
    return (Path(VIDEO_ROOT) / dataset_id).resolve()

def video_index_dir(dataset_id: str = DEFAULT_DATASET_ID) -> Path:
    dataset_id = normalize_dataset_id(dataset_id)
    return (Path(VIDEO_INDEX_ROOT) / dataset_id).resolve()

def video_frame_dataset_dir(dataset_id: str = DEFAULT_DATASET_ID) -> Path:
    dataset_id = normalize_dataset_id(dataset_id)
    return (Path(VIDEO_FRAME_ROOT) / dataset_id).resolve()

def normalize_dataset_id(dataset_id: str = None) -> str:
    dataset_id = (dataset_id or DEFAULT_DATASET_ID).strip()
    if dataset_id == "":
        dataset_id = DEFAULT_DATASET_ID
    if not re.match(r'^[A-Za-z0-9_.-]+$', dataset_id):
        raise HTTPException(status_code=400, detail="无效的数据集 ID")
    return dataset_id

def discover_datasets() -> List[Dict]:
    items = [{
        "id": DEFAULT_DATASET_ID,
        "name": DATASET_DISPLAY_NAMES.get(DEFAULT_DATASET_ID, DEFAULT_DATASET_ID),
        "path": str(dataset_folder(DEFAULT_DATASET_ID)),
        "is_default": True,
    }]
    root = Path(DATASETS_ROOT)
    if root.exists():
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if not re.match(r'^[A-Za-z0-9_.-]+$', child.name):
                continue
            items.append({
                "id": child.name,
                "name": DATASET_DISPLAY_NAMES.get(child.name, child.name),
                "path": str(child.resolve()),
                "is_default": False,
            })
    for item in items:
        folder = Path(item["path"])
        images = collect_images(str(folder)) if folder.exists() else []
        index_dir = dataset_index_dir(item["id"])
        item["count"] = len(images)
        item["indexed"] = (index_dir / "vectors.pt").exists() and (index_dir / "meta.json").exists()
    return items

def discover_video_datasets() -> List[Dict]:
    items = []
    root = Path(VIDEO_ROOT)
    if not root.exists():
        return items
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or not re.match(r'^[A-Za-z0-9_.-]+$', child.name):
            continue
        videos = collect_videos(str(child))
        index_dir = video_index_dir(child.name)
        frame_dir = video_frame_dataset_dir(child.name)
        frame_count = count_images_recursive(str(frame_dir)) if frame_dir.exists() else 0
        items.append({
            "id": child.name,
            "name": DATASET_DISPLAY_NAMES.get(child.name, child.name),
            "path": str(child.resolve()),
            "count": len(videos),
            "frame_count": frame_count,
            "indexed": (index_dir / "vectors.pt").exists() and (index_dir / "meta.json").exists(),
        })
    return items

def list_video_dataset_items(dataset_id: str) -> List[Dict]:
    dataset_id = assert_video_dataset_exists(dataset_id)
    items = []
    for video_path in collect_videos(str(video_dataset_folder(dataset_id))):
        video_file = Path(video_path).resolve()
        stat = video_file.stat()
        frame_dir = video_frame_dataset_dir(dataset_id) / VideoFrameIndex.video_dirname_for_path(video_file)
        frames = list_frame_files_recursive(str(frame_dir))
        first_frame = str(frames[0].resolve()) if frames else None
        duration = ffprobe_duration(str(video_file))
        items.append({
            "file": video_file.name,
            "path": str(video_file),
            "dataset_id": dataset_id,
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "duration_sec": round(duration, 3),
            "duration_label": format_timestamp(duration),
            "frame_count": len(frames),
            "preview_frame_path": first_frame,
        })
    return items

def assert_dataset_exists(dataset_id: str) -> str:
    dataset_id = normalize_dataset_id(dataset_id)
    folder = dataset_folder(dataset_id)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_id}")
    return dataset_id

def assert_video_dataset_exists(dataset_id: str) -> str:
    dataset_id = normalize_dataset_id(dataset_id)
    folder = video_dataset_folder(dataset_id)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"视频集不存在: {dataset_id}")
    return dataset_id

def resolve_video_path(video_path: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    dataset_id = assert_video_dataset_exists(dataset_id)
    root = video_dataset_folder(dataset_id).resolve()
    candidate = Path(video_path)
    target = candidate.resolve() if candidate.is_absolute() else (root / video_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="视频路径不在视频集目录内")
    if not target.is_file() or target.suffix.lower() not in VIDEO_EXTS:
        raise HTTPException(status_code=404, detail=f"视频不存在或类型不支持: {video_path}")
    return str(target)

def resolve_video_frame_path(frame_path: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    dataset_id = normalize_dataset_id(dataset_id)
    root = video_frame_dataset_dir(dataset_id).resolve()
    candidate = Path(frame_path)
    target = candidate.resolve() if candidate.is_absolute() else (root / frame_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="帧图片路径不在抽帧目录内")
    if not target.is_file() or target.suffix.lower() not in IMG_EXTS:
        raise HTTPException(status_code=404, detail=f"帧图片不存在: {frame_path}")
    return str(target)

def ffprobe_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
        return max(0.0, float(out or 0))
    except Exception:
        return 0.0

def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    total = int(seconds)
    ms = int(round((seconds - total) * 1000))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if ms:
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"

def to_tensor(emb: Union[np.ndarray, torch.Tensor], device: torch.device) -> torch.Tensor:
    if isinstance(emb, np.ndarray):
        return torch.from_numpy(emb).to(device)
    elif isinstance(emb, torch.Tensor):
        return emb.to(device)
    else:
        raise TypeError(f"不支持的嵌入类型: {type(emb)}")

def get_file_signature(path: str) -> Optional[str]:
    try:
        stat = os.stat(path)
        return f"{stat.st_size}_{stat.st_mtime}"
    except Exception:
        return None

def decode_base64_image(base64_str: str) -> bytes:
    base64_str = base64_str.strip()
    match = re.match(r'data:image/(?P<ext>\w+);base64,(?P<data>.+)', base64_str)
    if match:
        base64_data = match.group('data')
    else:
        base64_data = base64_str
    try:
        image_bytes = base64.b64decode(base64_data)
    except Exception as e:
        raise ValueError(f"无效的 Base64 图片数据: {e}")
    size_mb = len(image_bytes) / (1024 * 1024)
    if size_mb > MAX_IMAGE_SIZE_MB:
        raise ValueError(f"图片大小超过限制 ({MAX_IMAGE_SIZE_MB} MB)")
    return image_bytes

def save_temp_image(image_bytes: bytes, suffix: str = ".jpg") -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(image_bytes)
        return tmp.name

def generate_unique_filename(original_filename: str = None, ext: str = ".jpg") -> str:
    if original_filename and '.' in original_filename:
        ext = Path(original_filename).suffix
    timestamp = int(time.time() * 1000)
    random_hash = hashlib.md5(os.urandom(16)).hexdigest()[:8]
    return f"{timestamp}_{random_hash}{ext}"

def resolve_index_image_path(image_path: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """Resolve a result path or filename safely inside the selected dataset."""
    dataset_id = assert_dataset_exists(dataset_id)
    image_root = dataset_folder(dataset_id).resolve()
    candidate = Path(image_path)
    if candidate.is_absolute():
        target = candidate.resolve()
    else:
        target = (image_root / image_path).resolve()
    try:
        target.relative_to(image_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="图片路径不在索引目录内")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"图片不存在: {image_path}")
    if target.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
        raise HTTPException(status_code=400, detail="不支持的图片类型")
    return str(target)

def thumb_path_for(image_path: str, dataset_id: str) -> Path:
    dataset_id = normalize_dataset_id(dataset_id)
    image_root = dataset_folder(dataset_id).resolve()
    target = Path(image_path).resolve()
    rel = target.relative_to(image_root)
    digest = hashlib.md5(str(rel).encode("utf-8")).hexdigest()[:10]
    stem = re.sub(r'[^A-Za-z0-9_.-]+', '_', rel.stem)[:80]
    return (Path(THUMB_ROOT) / dataset_id / f"{stem}_{digest}.jpg").resolve()

def build_or_get_thumb(image_path: str, dataset_id: str) -> str:
    thumb = thumb_path_for(image_path, dataset_id)
    src = Path(image_path)
    if thumb.exists() and thumb.stat().st_mtime >= src.stat().st_mtime:
        return str(thumb)
    thumb.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im.thumbnail(THUMB_MAX_SIZE)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(thumb, format="JPEG", quality=THUMB_QUALITY, optimize=True)
    return str(thumb)

# ==================== 索引类 ====================
class ImageIndex:
    def __init__(
        self,
        index_dir: str,
        clip_model,
        device: torch.device,
        truncate_dim: int = 512,
        batch_size: int = 8,
        reranker_path: str = RERANKER_PATH
    ):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.vectors_path = self.index_dir / "vectors.pt"
        self.meta_path = self.index_dir / "meta.json"
        self.clip_model = clip_model
        self.device = device
        self.truncate_dim = truncate_dim
        self.batch_size = batch_size
        self.reranker_path = reranker_path
        self.paths = []
        self.signatures = {}
        self.vectors = None
        self.reranker = None

    def _load_reranker(self):
        if self.reranker is None:
            print("⏳ 加载 Reranker 模型...")
            self.reranker = AutoModel.from_pretrained(
                self.reranker_path,
                torch_dtype="auto",
                trust_remote_code=True,
                local_files_only=True,
            )
            self.reranker.to(self.device)
            self.reranker.eval()
            print("✅ Reranker 加载完成")

    def _load_index(self):
        self.vectors = torch.load(self.vectors_path, map_location=self.device)
        with open(self.meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        self.paths = meta["paths"]
        self.signatures = {p: s for p, s in zip(meta["paths"], meta["signatures"])}
        print(f"📂 加载索引: {len(self.paths)} 张图片")

    def _save_index(self):
        torch.save(self.vectors, self.vectors_path)
        meta = {
            "paths": self.paths,
            "signatures": [self.signatures[p] for p in self.paths],
            "dim": self.truncate_dim,
            "model": "jinaai/jina-clip-v2"
        }
        with open(self.meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _encode_batch(self, batch_paths: List[str]) -> torch.Tensor:
        with torch.no_grad():
            emb = self.clip_model.encode_image(batch_paths, truncate_dim=self.truncate_dim)
            emb = to_tensor(emb, self.device)
        return emb

    def _full_rebuild(self, paths: List[str], signatures: Dict[str, str]):
        self.paths = paths
        self.signatures = signatures
        embeddings = []
        total = len(paths)
        for i in range(0, total, self.batch_size):
            batch = paths[i:i+self.batch_size]
            print(f"   编码: [{i+len(batch)}/{total}]")
            emb = self._encode_batch(batch)
            embeddings.append(emb)
        if embeddings:
            self.vectors = torch.cat(embeddings, dim=0)
        else:
            self.vectors = torch.empty((0, self.truncate_dim), device=self.device)

    def _incremental_update(self, to_remove: set, to_add_update: set, new_signatures: dict, ordered_paths: List[str]):
        keep_paths = [p for p in self.paths if p not in to_remove and p not in to_add_update]
        keep_path_to_idx = {p: i for i, p in enumerate(self.paths)}
        keep_indices = [keep_path_to_idx[p] for p in keep_paths]
        if keep_indices:
            keep_vectors = self.vectors[keep_indices]
        else:
            keep_vectors = torch.empty((0, self.truncate_dim), device=self.device)

        add_paths = sorted(list(to_add_update))
        add_vectors_list = []
        for i in range(0, len(add_paths), self.batch_size):
            batch = add_paths[i:i+self.batch_size]
            print(f"   增量编码: [{i+len(batch)}/{len(add_paths)}]")
            emb = self._encode_batch(batch)
            add_vectors_list.append(emb)
        if add_vectors_list:
            add_vectors = torch.cat(add_vectors_list, dim=0)
        else:
            add_vectors = torch.empty((0, self.truncate_dim), device=self.device)

        keep_path_to_local = {p: i for i, p in enumerate(keep_paths)}
        add_path_to_local = {p: i for i, p in enumerate(add_paths)}
        self.paths = []
        self.signatures = new_signatures
        vectors_list = []
        for p in ordered_paths:
            self.paths.append(p)
            if p in keep_path_to_local:
                idx = keep_path_to_local[p]
                vectors_list.append(keep_vectors[idx:idx+1])
            else:
                idx = add_path_to_local[p]
                vectors_list.append(add_vectors[idx:idx+1])
        if vectors_list:
            self.vectors = torch.cat(vectors_list, dim=0)
        else:
            self.vectors = torch.empty((0, self.truncate_dim), device=self.device)

    def build_or_update(self, image_folder: str):
        current_paths = collect_images(image_folder)
        current_sigs = {p: get_file_signature(p) for p in current_paths}
        if self.vectors_path.exists() and self.meta_path.exists():
            try:
                self._load_index()
                old_paths_set = set(self.paths)
                new_paths_set = set(current_paths)
                to_remove = old_paths_set - new_paths_set
                to_add = new_paths_set - old_paths_set
                to_update = set()
                for p in (old_paths_set & new_paths_set):
                    if self.signatures.get(p) != current_sigs[p]:
                        to_update.add(p)
                if not to_remove and not to_add and not to_update:
                    print("✅ 索引已是最新")
                    return
                print(f"🔄 增量更新: +{len(to_add)} 新增, -{len(to_remove)} 删除, ~{len(to_update)} 变更")
                self._incremental_update(to_remove, to_add | to_update, current_sigs, current_paths)
            except Exception as e:
                print(f"⚠️ 索引损坏，全量重建: {e}")
                self._full_rebuild(current_paths, current_sigs)
        else:
            print("🆕 首次构建索引")
            self._full_rebuild(current_paths, current_sigs)
        self._save_index()
        print(f"💾 索引保存至 {self.index_dir}")

    def add_single_image(self, image_path: str, save_to_folder: str = None) -> Dict:
        if save_to_folder is None:
            save_to_folder = IMAGE_FOLDER
        os.makedirs(save_to_folder, exist_ok=True)
        ext = Path(image_path).suffix
        if not ext:
            ext = ".jpg"
        final_filename = generate_unique_filename(ext=ext)
        final_path = os.path.join(save_to_folder, final_filename)
        shutil.copy2(image_path, final_path)
        final_path = os.path.abspath(final_path)

        with model_lock:
            with torch.no_grad():
                emb = self.clip_model.encode_image([final_path], truncate_dim=self.truncate_dim)
                emb = to_tensor(emb, self.device)
            new_signature = get_file_signature(final_path)
            if final_path in self.signatures:
                if self.signatures[final_path] == new_signature:
                    return {"status": "already_exists", "path": final_path, "total_indexed": len(self.paths)}
                else:
                    idx = self.paths.index(final_path)
                    self.vectors[idx] = emb[0]
                    self.signatures[final_path] = new_signature
            else:
                if self.vectors is None or self.vectors.size(0) == 0:
                    self.vectors = emb
                else:
                    self.vectors = torch.cat([self.vectors, emb], dim=0)
                self.paths.append(final_path)
                self.signatures[final_path] = new_signature
            self._save_index()
        return {"status": "added", "path": final_path, "total_indexed": len(self.paths)}

    def search(self, query_text: str, coarse_k: int = 100, final_k: int = 5, use_reranker: bool = True, rerank_top_k: int = None) -> List[Dict]:
        with model_lock:
            return self._search_text(query_text, coarse_k, final_k, use_reranker, rerank_top_k)

    def _search_text(self, query_text: str, coarse_k: int, final_k: int, use_reranker: bool = True, rerank_top_k: int = None):
        print(f"📝 文本查询: '{query_text}'")
        with torch.no_grad():
            query_emb = self.clip_model.encode_text(query_text, task='retrieval.query', truncate_dim=self.truncate_dim)
            query_emb = to_tensor(query_emb, self.device)
        similarities = (query_emb @ self.vectors.T).squeeze(0).cpu().float().numpy()
        total = len(self.paths)
        if total == 0:
            return []
        actual_coarse = min(coarse_k, total)
        top_idx = np.argsort(similarities)[::-1][:actual_coarse]
        coarse_paths = [self.paths[i] for i in top_idx]
        coarse_scores = [float(similarities[i]) for i in top_idx]

        if not use_reranker:
            return [
                {"rank": rank, "score": clip_score, "clip_score": clip_score, "path": path, "reranker_used": False}
                for rank, (path, clip_score) in enumerate(zip(coarse_paths, coarse_scores), 1)
            ][:final_k]

        rerank_count = min(max(1, rerank_top_k or actual_coarse), actual_coarse)
        coarse_paths = coarse_paths[:rerank_count]
        coarse_scores = coarse_scores[:rerank_count]
        self._load_reranker()
        pairs = [[query_text, p] for p in coarse_paths]
        rerank_scores = compute_rerank_scores(self.reranker, pairs, self.device, doc_type="image", query_type="text")

        combined = list(zip(coarse_paths, coarse_scores, rerank_scores))
        combined.sort(key=lambda x: x[2], reverse=True)
        results = []
        for rank, (path, clip_score, rerank_score) in enumerate(combined[:final_k], 1):
            results.append({
                "rank": rank,
                "score": rerank_score,
                "clip_score": clip_score,
                "path": path,
                "reranker_used": True
            })
        return results

    def search_by_image(self, query_image_path: str, coarse_k: int = 100, final_k: int = 5, use_reranker: bool = True, rerank_top_k: int = None) -> List[Dict]:
        with model_lock:
            return self._search_image(query_image_path, coarse_k, final_k, use_reranker, rerank_top_k)

    def _search_image(self, query_image_path: str, coarse_k: int, final_k: int, use_reranker: bool = True, rerank_top_k: int = None):
        print(f"🖼️ 图片查询: '{query_image_path}'")
        if not os.path.exists(query_image_path):
            raise FileNotFoundError(f"图片不存在: {query_image_path}")
        with torch.no_grad():
            query_emb = self.clip_model.encode_image([query_image_path], truncate_dim=self.truncate_dim)
            query_emb = to_tensor(query_emb, self.device).squeeze(0)
        similarities = (query_emb @ self.vectors.T).cpu().float().numpy()
        total = len(self.paths)
        if total == 0:
            return []
        actual_coarse = min(coarse_k, total)
        top_idx = np.argsort(similarities)[::-1][:actual_coarse]
        coarse_paths = [self.paths[i] for i in top_idx]
        coarse_scores = [float(similarities[i]) for i in top_idx]

        if not use_reranker:
            return [
                {"rank": rank, "score": clip_score, "clip_score": clip_score, "path": path, "reranker_used": False}
                for rank, (path, clip_score) in enumerate(zip(coarse_paths, coarse_scores), 1)
            ][:final_k]

        rerank_count = min(max(1, rerank_top_k or actual_coarse), actual_coarse)
        coarse_paths = coarse_paths[:rerank_count]
        coarse_scores = coarse_scores[:rerank_count]
        self._load_reranker()
        pairs = [[query_image_path, p] for p in coarse_paths]
        rerank_scores = compute_rerank_scores(self.reranker, pairs, self.device, doc_type="image", query_type="image")

        combined = list(zip(coarse_paths, coarse_scores, rerank_scores))
        combined.sort(key=lambda x: x[2], reverse=True)
        results = []
        for rank, (path, clip_score, rerank_score) in enumerate(combined[:final_k], 1):
            results.append({
                "rank": rank,
                "score": rerank_score,
                "clip_score": clip_score,
                "path": path,
                "reranker_used": True
            })
        return results

class VideoFrameIndex:
    @staticmethod
    def video_dirname_for_path(video_path: str | Path) -> str:
        target = Path(video_path).resolve()
        digest = hashlib.md5(str(target).encode("utf-8")).hexdigest()[:12]
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", target.stem)[:80]
        return f"{stem}_{digest}"

    def __init__(
        self,
        dataset_id: str,
        index_dir: str,
        frame_root: str,
        clip_model,
        device: torch.device,
        truncate_dim: int = 512,
        batch_size: int = 8,
        reranker_path: str = RERANKER_PATH,
    ):
        self.dataset_id = normalize_dataset_id(dataset_id)
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.frame_root = Path(frame_root)
        self.frame_root.mkdir(parents=True, exist_ok=True)
        self.vectors_path = self.index_dir / "vectors.pt"
        self.meta_path = self.index_dir / "meta.json"
        self.clip_model = clip_model
        self.device = device
        self.truncate_dim = truncate_dim
        self.batch_size = batch_size
        self.reranker_path = reranker_path
        self.frames = []
        self.vectors = None
        self.video_signatures = {}
        self.sample_fps = DEFAULT_VIDEO_SAMPLE_FPS
        self.reranker = None

    def _load_reranker(self):
        if self.reranker is None:
            print("⏳ 加载视频帧 Reranker 模型...")
            self.reranker = AutoModel.from_pretrained(
                self.reranker_path,
                torch_dtype="auto",
                trust_remote_code=True,
                local_files_only=True,
            )
            self.reranker.to(self.device)
            self.reranker.eval()
            print("✅ 视频帧 Reranker 加载完成")

    def _load_index(self):
        self.vectors = torch.load(self.vectors_path, map_location=self.device)
        with open(self.meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.frames = meta.get("frames") or []
        self.video_signatures = meta.get("video_signatures") or {}
        self.sample_fps = float(meta.get("sample_fps") or DEFAULT_VIDEO_SAMPLE_FPS)
        print(f"📂 加载视频帧索引: {len(self.frames)} 帧")

    def _save_index(self):
        torch.save(self.vectors, self.vectors_path)
        meta = {
            "frames": self.frames,
            "video_signatures": self.video_signatures,
            "sample_fps": self.sample_fps,
            "dim": self.truncate_dim,
            "model": "jinaai/jina-clip-v2",
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _video_frame_dir(self, video_path: str) -> Path:
        return (self.frame_root / self.video_dirname_for_path(video_path)).resolve()

    def _extract_frames(self, video_path: str, sample_fps: float, force: bool = False) -> List[Dict]:
        frame_dir = self._video_frame_dir(video_path)
        if force and frame_dir.exists():
            shutil.rmtree(frame_dir)
        frame_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(frame_dir.glob("frame_*.jpg"))
        if not existing:
            pattern = str(frame_dir / "frame_%06d.jpg")
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", video_path, "-vf", f"fps={sample_fps:g}", "-q:v", "2", pattern,
            ]
            subprocess.run(cmd, check=True)
            existing = sorted(frame_dir.glob("frame_*.jpg"))
        duration = ffprobe_duration(video_path)
        video_name = Path(video_path).name
        frames = []
        for idx, frame_path in enumerate(existing):
            timestamp = idx / sample_fps if sample_fps > 0 else float(idx)
            if duration:
                timestamp = min(timestamp, duration)
            frames.append({
                "frame_path": str(frame_path.resolve()),
                "video_path": str(Path(video_path).resolve()),
                "video_name": video_name,
                "frame_index": idx,
                "timestamp_sec": round(timestamp, 3),
                "timestamp_ms": int(round(timestamp * 1000)),
                "timestamp_label": format_timestamp(timestamp),
                "sample_fps": sample_fps,
                "duration_sec": round(duration, 3),
            })
        return frames

    def _encode_frames(self, frame_paths: List[str]) -> torch.Tensor:
        embeddings = []
        total = len(frame_paths)
        for i in range(0, total, self.batch_size):
            batch = frame_paths[i:i+self.batch_size]
            print(f"   视频帧编码: [{i+len(batch)}/{total}]")
            with torch.no_grad():
                emb = self.clip_model.encode_image(batch, truncate_dim=self.truncate_dim)
                emb = to_tensor(emb, self.device)
            embeddings.append(emb)
        if embeddings:
            return torch.cat(embeddings, dim=0)
        return torch.empty((0, self.truncate_dim), device=self.device)

    def build_or_update(self, video_folder: str, sample_fps: float = DEFAULT_VIDEO_SAMPLE_FPS, force_extract: bool = False):
        sample_fps = max(0.1, min(float(sample_fps or DEFAULT_VIDEO_SAMPLE_FPS), 10.0))
        videos = collect_videos(video_folder)
        current_sigs = {p: get_file_signature(p) for p in videos}
        if self.vectors_path.exists() and self.meta_path.exists() and not force_extract:
            try:
                self._load_index()
                if self.video_signatures == current_sigs and abs(self.sample_fps - sample_fps) < 1e-6:
                    print("✅ 视频帧索引已是最新")
                    return
            except Exception as e:
                print(f"⚠️ 视频帧索引损坏，全量重建: {e}")

        all_frames = []
        for video_path in videos:
            print(f"🎞️ 抽帧: {video_path}")
            all_frames.extend(self._extract_frames(video_path, sample_fps, force=force_extract))
        frame_paths = [f["frame_path"] for f in all_frames]
        self.frames = all_frames
        self.video_signatures = current_sigs
        self.sample_fps = sample_fps
        self.vectors = self._encode_frames(frame_paths)
        self._save_index()
        print(f"💾 视频帧索引保存至 {self.index_dir}: {len(self.frames)} 帧")

    def search_text(self, query_text: str, coarse_k: int = 100, final_k: int = 5, use_reranker: bool = True, rerank_top_k: int = None) -> List[Dict]:
        with model_lock:
            print(f"📝 文搜视频: '{query_text}'")
            with torch.no_grad():
                query_emb = self.clip_model.encode_text(query_text, task='retrieval.query', truncate_dim=self.truncate_dim)
                query_emb = to_tensor(query_emb, self.device)
            return self._search_by_embedding(query_emb.squeeze(0), "text", query_text, coarse_k, final_k, use_reranker, rerank_top_k)

    def search_image(self, query_image_path: str, coarse_k: int = 100, final_k: int = 5, use_reranker: bool = True, rerank_top_k: int = None) -> List[Dict]:
        with model_lock:
            print(f"🖼️ 图搜视频: '{query_image_path}'")
            with torch.no_grad():
                query_emb = self.clip_model.encode_image([query_image_path], truncate_dim=self.truncate_dim)
                query_emb = to_tensor(query_emb, self.device).squeeze(0)
            return self._search_by_embedding(query_emb, "image", query_image_path, coarse_k, final_k, use_reranker, rerank_top_k)

    def debug_text_frame_match(self, query_text: str, frame_path: str, coarse_k: int = 100, rerank_top_k: int = None) -> Dict:
        with model_lock:
            frame_target = str(Path(resolve_video_frame_path(frame_path, self.dataset_id)).resolve())
            frame_idx = next(
                (i for i, item in enumerate(self.frames) if str(item.get("frame_path") or "") == frame_target),
                -1,
            )
            if frame_idx < 0:
                raise ValueError(f"未找到视频帧: {frame_path}")
            print("video frame debug:", query_text, "vs", frame_target)
            with torch.no_grad():
                query_emb = self.clip_model.encode_text(query_text, task="retrieval.query", truncate_dim=self.truncate_dim)
                query_emb = to_tensor(query_emb, self.device).squeeze(0)
            similarities = (query_emb @ self.vectors.T).cpu().float().numpy()
            total = len(self.frames)
            order = np.argsort(similarities)[::-1]
            coarse_rank = int(np.where(order == frame_idx)[0][0]) + 1
            coarse_score = float(similarities[frame_idx])
            actual_coarse = min(max(1, coarse_k), total)
            rerank_pool_size = min(max(1, rerank_top_k or actual_coarse), total)
            coarse_hit = coarse_rank <= actual_coarse
            rerank_hit = coarse_rank <= rerank_pool_size
            self._load_reranker()
            candidate_order = order[:rerank_pool_size].tolist()
            if frame_idx not in candidate_order:
                candidate_order.append(frame_idx)
            pairs = [[query_text, self.frames[i]["frame_path"]] for i in candidate_order]
            rerank_scores = compute_rerank_scores(self.reranker, pairs, self.device, doc_type="image", query_type="text")
            reranked = list(zip(candidate_order, rerank_scores))
            reranked.sort(key=lambda x: x[1], reverse=True)
            rerank_rank = next((rank for rank, (idx, _) in enumerate(reranked, 1) if idx == frame_idx), None)
            rerank_score = next((score for idx, score in reranked if idx == frame_idx), None)
            frame = dict(self.frames[frame_idx])
            frame.update({
                "query": query_text,
                "coarse_score": coarse_score,
                "coarse_rank": coarse_rank,
                "coarse_score_percent": round(coarse_score * 100, 1),
                "coarse_candidate_size": actual_coarse,
                "coarse_hit": coarse_hit,
                "rerank_score": rerank_score,
                "rerank_rank": rerank_rank,
                "rerank_score_percent": round(rerank_score * 100, 1) if rerank_score is not None else None,
                "rerank_pool_size": rerank_pool_size,
                "rerank_hit": rerank_hit,
                "total_indexed": total,
            })
            return frame

    def _segment_gap_seconds(self, sample_fps: float) -> float:
        frame_interval = 1.0 / max(sample_fps, 0.1)
        return max(DEFAULT_SEGMENT_GAP_SECONDS, frame_interval * 2.5)

    def _aggregate_ranked_frames(self, ranked: List[tuple], final_k: int) -> List[Dict]:
        if not ranked:
            return []
        hits = []
        for idx, clip_score, score, reranker_used in ranked:
            frame = dict(self.frames[idx])
            frame.update({
                "score": float(score),
                "clip_score": float(clip_score),
                "reranker_used": reranker_used,
                "dataset_id": self.dataset_id,
            })
            hits.append(frame)

        grouped = {}
        for hit in hits:
            grouped.setdefault(hit["video_path"], []).append(hit)

        segments = []
        for video_path, video_hits in grouped.items():
            ordered = sorted(video_hits, key=lambda x: (x["timestamp_sec"], -x["score"]))
            gap = self._segment_gap_seconds(float(ordered[0].get("sample_fps") or self.sample_fps or DEFAULT_VIDEO_SAMPLE_FPS))
            current = []
            for hit in ordered:
                if not current:
                    current = [hit]
                    continue
                if hit["timestamp_sec"] - current[-1]["timestamp_sec"] <= gap:
                    current.append(hit)
                else:
                    segments.append(self._build_segment(video_path, current))
                    current = [hit]
            if current:
                segments.append(self._build_segment(video_path, current))

        segments.sort(key=lambda x: (x["score"], x["hit_count"], x["avg_score"]), reverse=True)
        for rank, item in enumerate(segments[:final_k], 1):
            item["rank"] = rank
        return segments[:final_k]

    def _build_segment(self, video_path: str, hits: List[Dict]) -> Dict:
        best = max(hits, key=lambda x: (x["score"], x["clip_score"]))
        start = hits[0]["timestamp_sec"]
        end = hits[-1]["timestamp_sec"]
        avg_score = sum(h["score"] for h in hits) / len(hits)
        avg_clip = sum(h["clip_score"] for h in hits) / len(hits)
        return {
            "video_path": video_path,
            "video_name": best["video_name"],
            "frame_path": best["frame_path"],
            "best_frame_path": best["frame_path"],
            "frame_index": best["frame_index"],
            "timestamp_sec": best["timestamp_sec"],
            "timestamp_ms": best["timestamp_ms"],
            "timestamp_label": best["timestamp_label"],
            "segment_start_sec": round(start, 3),
            "segment_end_sec": round(end, 3),
            "segment_start_ms": int(round(start * 1000)),
            "segment_end_ms": int(round(end * 1000)),
            "segment_start_label": format_timestamp(start),
            "segment_end_label": format_timestamp(end),
            "segment_duration_sec": round(max(0.0, end - start), 3),
            "duration_sec": best["duration_sec"],
            "sample_fps": best["sample_fps"],
            "hit_count": len(hits),
            "score": float(best["score"]),
            "clip_score": float(best["clip_score"]),
            "avg_score": round(avg_score, 6),
            "avg_clip_score": round(avg_clip, 6),
            "reranker_used": best["reranker_used"],
            "dataset_id": self.dataset_id,
            "result_type": "segment",
        }

    def _search_by_embedding(self, query_emb, query_type: str, query_content: str, coarse_k: int, final_k: int, use_reranker: bool, rerank_top_k: int = None) -> List[Dict]:
        total = len(self.frames)
        if total == 0:
            return []
        similarities = (query_emb @ self.vectors.T).cpu().float().numpy()
        actual_coarse = min(coarse_k, total)
        top_idx = np.argsort(similarities)[::-1][:actual_coarse]
        coarse = [(int(i), float(similarities[i])) for i in top_idx]
        if use_reranker:
            rerank_count = min(max(1, rerank_top_k or actual_coarse), actual_coarse)
            candidates = coarse[:rerank_count]
            self._load_reranker()
            if query_type == "text":
                pairs = [[query_content, self.frames[i]["frame_path"]] for i, _ in candidates]
                qtype = "text"
            else:
                pairs = [[query_content, self.frames[i]["frame_path"]] for i, _ in candidates]
                qtype = "image"
            scores = compute_rerank_scores(self.reranker, pairs, self.device, doc_type="image", query_type=qtype)
            ranked = [(i, clip, score, True) for (i, clip), score in zip(candidates, scores)]
            ranked.sort(key=lambda x: x[2], reverse=True)
        else:
            ranked = [(i, clip, clip, False) for i, clip in coarse]
        return self._aggregate_ranked_frames(ranked, final_k)

# ==================== FastAPI 应用 ====================
app = FastAPI(title="图片语义搜索 API", description="支持文本搜图、文件上传搜图、视频帧检索")

global_index: Optional[ImageIndex] = None
global_indices: Dict[str, ImageIndex] = {}
global_video_indices: Dict[str, VideoFrameIndex] = {}
global_clip_model = None

def get_dataset_index(dataset_id: str = DEFAULT_DATASET_ID) -> ImageIndex:
    dataset_id = assert_dataset_exists(dataset_id)
    if global_clip_model is None:
        raise HTTPException(status_code=503, detail="服务未初始化")
    if dataset_id not in global_indices:
        idx = ImageIndex(
            str(dataset_index_dir(dataset_id)),
            global_clip_model,
            DEVICE,
            TRUNCATE_DIM,
            BATCH_SIZE,
            RERANKER_PATH,
        )
        idx.build_or_update(str(dataset_folder(dataset_id)))
        global_indices[dataset_id] = idx
    return global_indices[dataset_id]

def get_video_index(dataset_id: str = DEFAULT_DATASET_ID, sample_fps: float = DEFAULT_VIDEO_SAMPLE_FPS, force_extract: bool = False) -> VideoFrameIndex:
    dataset_id = assert_video_dataset_exists(dataset_id)
    if global_clip_model is None:
        raise HTTPException(status_code=503, detail="服务未初始化")
    idx = global_video_indices.get(dataset_id)
    if idx is None:
        idx = VideoFrameIndex(
            dataset_id,
            str(video_index_dir(dataset_id)),
            str(video_frame_dataset_dir(dataset_id)),
            global_clip_model,
            DEVICE,
            TRUNCATE_DIM,
            BATCH_SIZE,
            RERANKER_PATH,
        )
        global_video_indices[dataset_id] = idx
    idx.build_or_update(str(video_dataset_folder(dataset_id)), sample_fps=sample_fps, force_extract=force_extract)
    return idx

@app.on_event("startup")
async def startup_event():
    global global_index, global_clip_model
    print(f"🔧 使用设备: {DEVICE}")
    if DEVICE == "cpu":
        print("⚠️ 警告: CPU 模式下运行可能较慢")
    print("⏳ 加载 CLIP 模型...")
    clip_model = AutoModel.from_pretrained(
        CLIP_MODEL_PATH,
        trust_remote_code=True,
        local_files_only=True,
        torch_dtype=torch.bfloat16 if DEVICE == "cuda" else torch.float32
    ).to(DEVICE)
    clip_model.eval()
    global_clip_model = clip_model
    print("✅ CLIP 模型加载完成")
    global_index = get_dataset_index(DEFAULT_DATASET_ID)
    print("🚀 API 服务已就绪")

# ---------- Pydantic 请求模型 ----------
class TextSearchRequest(BaseModel):
    query: str
    coarse_k: int = Field(100, ge=1, le=500)
    top_k: int = Field(5, ge=1, le=100)
    dataset_id: str = Field(DEFAULT_DATASET_ID, description="数据集 ID，默认 default")
    use_reranker: bool = Field(True, description="是否启用 Reranker 精排")
    rerank_top_k: Optional[int] = Field(None, ge=1, le=500, description="参与 Reranker 精排的粗排候选数，默认等于 coarse_k")

class ImageBase64Request(BaseModel):
    image_base64: str = Field(..., description="Base64 编码的图片（支持 data URL 格式）")
    coarse_k: int = Field(100, ge=1, le=500)
    top_k: int = Field(5, ge=1, le=100)
    dataset_id: str = Field(DEFAULT_DATASET_ID, description="数据集 ID，默认 default")
    use_reranker: bool = Field(True, description="是否启用 Reranker 精排")
    rerank_top_k: Optional[int] = Field(None, ge=1, le=500, description="参与 Reranker 精排的粗排候选数，默认等于 coarse_k")

class AddImageBase64Request(BaseModel):
    image_base64: str = Field(..., description="Base64 编码的图片")
    filename: Optional[str] = Field(None, description="建议的文件名（扩展名需匹配）")

class ImageFromIndexRequest(BaseModel):
    image_path: str = Field(..., description="已在索引中的图片路径（绝对路径、相对路径或文件名）")
    coarse_k: int = Field(100, ge=1, le=500)
    top_k: int = Field(5, ge=1, le=100)
    dataset_id: str = Field(DEFAULT_DATASET_ID, description="数据集 ID，默认 default")
    use_reranker: bool = Field(True, description="是否启用 Reranker 精排")
    rerank_top_k: Optional[int] = Field(None, ge=1, le=500, description="参与 Reranker 精排的粗排候选数，默认等于 coarse_k")

class VideoTextSearchRequest(BaseModel):
    query: str
    coarse_k: int = Field(100, ge=1, le=500)
    top_k: int = Field(5, ge=1, le=100)
    dataset_id: str = Field(DEFAULT_DATASET_ID, description="视频集 ID，默认 default")
    sample_fps: float = Field(DEFAULT_VIDEO_SAMPLE_FPS, ge=0.1, le=10)
    use_reranker: bool = Field(True, description="是否启用 Reranker 精排")
    rerank_top_k: Optional[int] = Field(None, ge=1, le=500, description="参与 Reranker 精排的粗排候选数，默认等于 coarse_k")

class VideoFrameMatchDebugRequest(BaseModel):
    query: str = Field(..., min_length=1)
    frame_path: str = Field(..., min_length=1, description="视频帧图片路径")
    dataset_id: str = Field(DEFAULT_DATASET_ID, description="视频集 ID，默认 default")
    sample_fps: float = Field(DEFAULT_VIDEO_SAMPLE_FPS, ge=0.1, le=10)
    coarse_k: int = Field(100, ge=1, le=500)
    rerank_top_k: Optional[int] = Field(None, ge=1, le=500, description="参与 Reranker 精排的粗排候选数，默认等于 coarse_k")

class SearchResponse(BaseModel):
    query: dict
    coarse_k: int
    final_k: int
    total_indexed: int
    results: List[dict]

class AddImageResponse(BaseModel):
    status: str
    path: str
    total_indexed: int

# ---------- 文本搜索 ----------
@app.post("/search/text", response_model=SearchResponse)
async def search_text(request: TextSearchRequest):
    try:
        index = get_dataset_index(request.dataset_id)
        results = index.search(request.query, request.coarse_k, request.top_k, request.use_reranker, request.rerank_top_k)
        return SearchResponse(
            query={
                "type": "text",
                "content": request.query,
                "dataset_id": normalize_dataset_id(request.dataset_id),
                "use_reranker": request.use_reranker,
                "rerank_top_k": request.rerank_top_k or request.coarse_k,
            },
            coarse_k=request.coarse_k,
            final_k=request.top_k,
            total_indexed=len(index.paths),
            results=results
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------- 文件上传搜索 ----------
@app.post("/search/image", response_model=SearchResponse)
async def search_image_file(
    file: UploadFile = File(...),
    coarse_k: int = Form(100),
    top_k: int = Form(5),
    dataset_id: str = Form(DEFAULT_DATASET_ID),
    use_reranker: bool = Form(True),
    rerank_top_k: Optional[int] = Form(None),
):
    index = get_dataset_index(dataset_id)
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片大小超过 {MAX_IMAGE_SIZE_MB} MB")
    suffix = Path(file.filename).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        results = index.search_by_image(tmp_path, coarse_k, top_k, use_reranker, rerank_top_k)
        return SearchResponse(
            query={
                "type": "image",
                "content": file.filename,
                "dataset_id": normalize_dataset_id(dataset_id),
                "use_reranker": use_reranker,
                "rerank_top_k": rerank_top_k or coarse_k,
            },
            coarse_k=coarse_k,
            final_k=top_k,
            total_indexed=len(index.paths),
            results=results
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)

# ---------- Base64 图片搜索 ----------
@app.post("/search/image/base64", response_model=SearchResponse)
async def search_image_base64(request: ImageBase64Request):
    index = get_dataset_index(request.dataset_id)
    try:
        image_bytes = decode_base64_image(request.image_base64)
        tmp_path = save_temp_image(image_bytes, ".jpg")
        results = index.search_by_image(tmp_path, request.coarse_k, request.top_k, request.use_reranker, request.rerank_top_k)
        return SearchResponse(
            query={
                "type": "image_base64",
                "content": "base64_encoded_image",
                "dataset_id": normalize_dataset_id(request.dataset_id),
                "use_reranker": request.use_reranker,
                "rerank_top_k": request.rerank_top_k or request.coarse_k,
            },
            coarse_k=request.coarse_k,
            final_k=request.top_k,
            total_indexed=len(index.paths),
            results=results
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'tmp_path' in locals():
            try:
                os.unlink(tmp_path)
            except:
                pass

# ---------- 从已有索引中选择图片进行查询（新增）----------
@app.post("/search/image/from_index", response_model=SearchResponse)
async def search_image_from_index(request: ImageFromIndexRequest):
    index = get_dataset_index(request.dataset_id)
    
    query_path = request.image_path
    # 如果不是绝对路径，尝试在索引中匹配
    if not os.path.isabs(query_path):
        # 先尝试作为文件名匹配
        matched = [p for p in index.paths if os.path.basename(p) == query_path]
        if not matched:
            # 再尝试作为相对路径（相对于 IMAGE_FOLDER）
            abs_path = str((dataset_folder(request.dataset_id) / query_path).resolve())
            if abs_path in index.paths:
                matched = [abs_path]
        if not matched:
            raise HTTPException(status_code=404, detail=f"索引中未找到图片: {query_path}")
        query_path = matched[0]
    else:
        if query_path not in index.paths:
            raise HTTPException(status_code=404, detail=f"索引中不存在该图片: {query_path}")
    
    try:
        results = index.search_by_image(query_path, request.coarse_k, request.top_k, request.use_reranker, request.rerank_top_k)
        return SearchResponse(
            query={
                "type": "image_from_index",
                "content": query_path,
                "dataset_id": normalize_dataset_id(request.dataset_id),
                "use_reranker": request.use_reranker,
                "rerank_top_k": request.rerank_top_k or request.coarse_k,
            },
            coarse_k=request.coarse_k,
            final_k=request.top_k,
            total_indexed=len(index.paths),
            results=results
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# GET 方式调用，方便测试
@app.get("/search/image/from_index", response_model=SearchResponse)
async def search_image_from_index_get(
    image_path: str,
    coarse_k: int = 100,
    top_k: int = 5,
    dataset_id: str = DEFAULT_DATASET_ID,
    use_reranker: bool = True,
    rerank_top_k: Optional[int] = None,
):
    return await search_image_from_index(ImageFromIndexRequest(
        image_path=image_path,
        coarse_k=coarse_k,
        top_k=top_k,
        dataset_id=dataset_id,
        use_reranker=use_reranker,
        rerank_top_k=rerank_top_k,
    ))

# ---------- 视频帧检索 ----------
def enrich_video_results(results: List[Dict], dataset_id: str) -> List[Dict]:
    enriched = []
    for item in results:
        frame_path = item.get("frame_path") or ""
        video_path = item.get("video_path") or ""
        timestamp = float(item.get("timestamp_sec") or 0)
        enriched.append({
            **item,
            "filename": item.get("video_name") or Path(video_path).name,
            "frame_url": "/video/frame?" + parse.urlencode({"path": frame_path, "dataset_id": dataset_id}) if frame_path else None,
            "thumb_url": "/video/frame?" + parse.urlencode({"path": frame_path, "dataset_id": dataset_id}) if frame_path else None,
            "video_url": "/video?" + parse.urlencode({"path": video_path, "dataset_id": dataset_id}) if video_path else None,
            "seek_url": ("/video?" + parse.urlencode({"path": video_path, "dataset_id": dataset_id}) + f"#t={timestamp:.3f}") if video_path else None,
        })
    return enriched

@app.post("/search/video/text", response_model=SearchResponse)
async def search_video_text(request: VideoTextSearchRequest):
    try:
        dataset_id = normalize_dataset_id(request.dataset_id)
        index = get_video_index(dataset_id, sample_fps=request.sample_fps)
        results = index.search_text(request.query, request.coarse_k, request.top_k, request.use_reranker, request.rerank_top_k)
        return SearchResponse(
            query={
                "type": "video_text",
                "content": request.query,
                "dataset_id": dataset_id,
                "sample_fps": index.sample_fps,
                "use_reranker": request.use_reranker,
                "rerank_top_k": request.rerank_top_k or request.coarse_k,
            },
            coarse_k=request.coarse_k,
            final_k=request.top_k,
            total_indexed=len(index.frames),
            results=enrich_video_results(results, dataset_id),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search/video/image", response_model=SearchResponse)
async def search_video_image(
    file: UploadFile = File(...),
    coarse_k: int = Form(100),
    top_k: int = Form(5),
    dataset_id: str = Form(DEFAULT_DATASET_ID),
    sample_fps: float = Form(DEFAULT_VIDEO_SAMPLE_FPS),
    use_reranker: bool = Form(True),
    rerank_top_k: Optional[int] = Form(None),
):
    dataset_id = normalize_dataset_id(dataset_id)
    index = get_video_index(dataset_id, sample_fps=sample_fps)
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片大小超过 {MAX_IMAGE_SIZE_MB} MB")
    suffix = Path(file.filename).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        results = index.search_image(tmp_path, coarse_k, top_k, use_reranker, rerank_top_k)
        return SearchResponse(
            query={
                "type": "video_image",
                "content": file.filename,
                "dataset_id": dataset_id,
                "sample_fps": index.sample_fps,
                "use_reranker": use_reranker,
                "rerank_top_k": rerank_top_k or coarse_k,
            },
            coarse_k=coarse_k,
            final_k=top_k,
            total_indexed=len(index.frames),
            results=enrich_video_results(results, dataset_id),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)

@app.post("/debug/video/frame-match")
async def debug_video_frame_match(request: VideoFrameMatchDebugRequest):
    try:
        dataset_id = normalize_dataset_id(request.dataset_id)
        index = get_video_index(dataset_id, sample_fps=request.sample_fps)
        result = index.debug_text_frame_match(request.query, request.frame_path, request.coarse_k, request.rerank_top_k)
        return {
            "query": {
                "type": "video_frame_match_debug",
                "content": request.query,
                "frame_path": request.frame_path,
                "dataset_id": dataset_id,
                "sample_fps": index.sample_fps,
                "coarse_k": request.coarse_k,
                "rerank_top_k": request.rerank_top_k or request.coarse_k,
            },
            "result": {
                **result,
                "filename": result.get("video_name") or Path(str(result.get("video_path") or "")).name,
                "frame_url": "/video/frame?" + parse.urlencode({"path": result.get("frame_path") or "", "dataset_id": dataset_id}) if result.get("frame_path") else None,
                "thumb_url": "/video/frame?" + parse.urlencode({"path": result.get("frame_path") or "", "dataset_id": dataset_id}) if result.get("frame_path") else None,
                "video_url": "/video?" + parse.urlencode({"path": result.get("video_path") or "", "dataset_id": dataset_id}) if result.get("video_path") else None,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------- 添加图片到索引 ----------
@app.post("/add_image", response_model=AddImageResponse)
async def add_image_file(file: UploadFile = File(...)):
    if global_index is None:
        raise HTTPException(status_code=503, detail="服务未初始化")
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"图片大小超过 {MAX_IMAGE_SIZE_MB} MB")
    suffix = Path(file.filename).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        result = global_index.add_single_image(tmp_path)
        return AddImageResponse(
            status=result["status"],
            path=result["path"],
            total_indexed=result["total_indexed"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)

@app.post("/add_image/base64", response_model=AddImageResponse)
async def add_image_base64(request: AddImageBase64Request):
    if global_index is None:
        raise HTTPException(status_code=503, detail="服务未初始化")
    try:
        image_bytes = decode_base64_image(request.image_base64)
        tmp_path = save_temp_image(image_bytes, ".jpg")
        result = global_index.add_single_image(tmp_path)
        return AddImageResponse(
            status=result["status"],
            path=result["path"],
            total_indexed=result["total_indexed"]
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'tmp_path' in locals():
            try:
                os.unlink(tmp_path)
            except:
                pass

# ---------- 索引管理 ----------
@app.post("/build")
async def rebuild_index(background_tasks: BackgroundTasks, dataset_id: str = DEFAULT_DATASET_ID):
    index = get_dataset_index(dataset_id)
    dataset_id = normalize_dataset_id(dataset_id)
    background_tasks.add_task(index.build_or_update, str(dataset_folder(dataset_id)))
    return {"message": "索引更新任务已启动", "dataset_id": dataset_id}

@app.post("/build/videos")
async def rebuild_video_index(
    background_tasks: BackgroundTasks,
    dataset_id: str = DEFAULT_DATASET_ID,
    sample_fps: float = DEFAULT_VIDEO_SAMPLE_FPS,
    force_extract: bool = False,
):
    dataset_id = assert_video_dataset_exists(dataset_id)
    idx = get_video_index(dataset_id, sample_fps=sample_fps, force_extract=False)
    background_tasks.add_task(idx.build_or_update, str(video_dataset_folder(dataset_id)), sample_fps, force_extract)
    return {"message": "视频帧索引更新任务已启动", "dataset_id": dataset_id, "sample_fps": sample_fps}

@app.get("/datasets")
async def datasets():
    return {"items": discover_datasets(), "default_dataset_id": DEFAULT_DATASET_ID}

@app.get("/video-datasets")
async def video_datasets():
    return {"items": discover_video_datasets(), "default_dataset_id": DEFAULT_DATASET_ID}

@app.get("/video-datasets/{dataset_id}/videos")
async def dataset_videos(dataset_id: str):
    dataset_id = assert_video_dataset_exists(dataset_id)
    raw_items = list_video_dataset_items(dataset_id)
    items = []
    for item in raw_items:
        video_path = str(item.get("path") or "")
        frame_path = str(item.get("preview_frame_path") or "")
        items.append({
            **item,
            "video_url": "/video?" + parse.urlencode({"path": video_path, "dataset_id": dataset_id}) if video_path else None,
            "preview_frame_url": "/video/frame?" + parse.urlencode({"path": frame_path, "dataset_id": dataset_id}) if frame_path else None,
        })
    return {
        "dataset_id": dataset_id,
        "total": len(items),
        "items": items,
    }

@app.get("/datasets/{dataset_id}/images")
async def dataset_images(
    dataset_id: str,
    page: int = 1,
    page_size: int = 48,
    q: str = "",
):
    dataset_id = assert_dataset_exists(dataset_id)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    q_norm = (q or "").strip().lower()
    paths = collect_images(str(dataset_folder(dataset_id)))
    if q_norm:
        paths = [p for p in paths if q_norm in os.path.basename(p).lower()]
    total = len(paths)
    start = (page - 1) * page_size
    end = start + page_size
    items = []
    for p in paths[start:end]:
        stat = os.stat(p)
        name = os.path.basename(p)
        items.append({
            "file": name,
            "path": p,
            "dataset_id": dataset_id,
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "image_url": "/image?" + parse.urlencode({"path": p, "dataset_id": dataset_id, "size": "orig"}),
            "thumb_url": "/image?" + parse.urlencode({"path": p, "dataset_id": dataset_id, "size": "thumb"}),
        })
    return {
        "dataset_id": dataset_id,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
        "items": items,
    }

@app.get("/status")
async def status():
    if global_index is None:
        return {"status": "not_ready"}
    return {
        "status": "ready",
        "device": DEVICE,
        "total_indexed": len(global_index.paths),
        "models": {"clip": CLIP_MODEL_PATH, "reranker": RERANKER_PATH},
        "datasets": discover_datasets(),
        "video_datasets": discover_video_datasets(),
    }

@app.get("/image")
async def get_index_image(
    path: str = Query(..., description="索引结果中的图片绝对路径、相对路径或文件名"),
    dataset_id: str = Query(DEFAULT_DATASET_ID, description="数据集 ID，默认 default"),
    size: str = Query("orig", pattern="^(orig|thumb)$"),
):
    target = resolve_index_image_path(path, dataset_id)
    if size == "thumb":
        return FileResponse(build_or_get_thumb(target, dataset_id), media_type="image/jpeg")
    return FileResponse(target)

@app.get("/video")
async def get_video(
    path: str = Query(..., description="视频绝对路径、相对路径或文件名"),
    dataset_id: str = Query(DEFAULT_DATASET_ID, description="视频集 ID，默认 default"),
):
    target = resolve_video_path(path, dataset_id)
    return FileResponse(target, media_type="video/mp4")

@app.get("/video/frame")
async def get_video_frame(
    path: str = Query(..., description="视频帧图片路径"),
    dataset_id: str = Query(DEFAULT_DATASET_ID, description="视频集 ID，默认 default"),
):
    target = resolve_video_frame_path(path, dataset_id)
    return FileResponse(target, media_type="image/jpeg")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
