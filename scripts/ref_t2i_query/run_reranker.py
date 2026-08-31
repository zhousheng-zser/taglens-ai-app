import os
import json
import argparse
from pathlib import Path
from typing import List, Dict, Union, Optional

import torch
import numpy as np
from PIL import Image
from transformers import AutoModel

# ==================== 用户配置区 ====================
IMAGE_FOLDER = "./picture"          # 图片文件夹
INDEX_DIR = "./image_index"         # 索引文件保存目录
TRUNCATE_DIM = 2048                 # 嵌入维度
BATCH_SIZE = 24                     # 编码批次大小
CLIP_MODEL_PATH = "./jina-clip-v2"  # CLIP 模型路径
RERANKER_PATH = "./reranker"        # Reranker 模型路径
# ===================================================

def collect_images(folder: str) -> List[str]:
    """收集文件夹内所有常见格式的图片路径（去重）"""
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

def to_tensor(emb: Union[np.ndarray, torch.Tensor], device: torch.device) -> torch.Tensor:
    """统一将 numpy 或 tensor 转换为 torch.Tensor 并放到目标设备"""
    if isinstance(emb, np.ndarray):
        return torch.from_numpy(emb).to(device)
    elif isinstance(emb, torch.Tensor):
        return emb.to(device)
    else:
        raise TypeError(f"不支持的嵌入类型: {type(emb)}")

def get_file_signature(path: str) -> str:
    """返回文件签名（大小+修改时间），用于检测图片是否被修改"""
    try:
        stat = os.stat(path)
        return f"{stat.st_size}_{stat.st_mtime}"
    except Exception:
        return None

class ImageIndex:
    """封装向量索引的构建、增量更新和查询（支持 CLIP 粗排 + Reranker 精排）"""

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

        self.paths = []          # 路径列表，顺序对应向量矩阵行号
        self.signatures = {}     # 路径 -> 签名
        self.vectors = None      # [N, D] tensor
        self.reranker = None     # 延迟加载

    def _load_reranker(self):
        """加载 Reranker 模型（只加载一次）"""
        if self.reranker is None:
            print("⏳ 正在加载 Reranker 模型...")
            self.reranker = AutoModel.from_pretrained(
                self.reranker_path,
                torch_dtype="auto",
                trust_remote_code=True,
            )
            self.reranker.to(self.device)
            self.reranker.eval()
            print("✅ Reranker 模型加载完成")

    def _load_index(self):
        """从磁盘加载索引"""
        self.vectors = torch.load(self.vectors_path, map_location=self.device)
        with open(self.meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        self.paths = meta["paths"]
        self.signatures = {p: s for p, s in zip(meta["paths"], meta["signatures"])}
        print(f"📂 已加载索引: {len(self.paths)} 张图片")

    def _save_index(self):
        """保存索引到磁盘"""
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
        """编码一批图片为向量"""
        with torch.no_grad():
            emb = self.clip_model.encode_image(batch_paths, truncate_dim=self.truncate_dim)
            emb = to_tensor(emb, self.device)
        return emb

    def _full_rebuild(self, paths: List[str], signatures: Dict[str, str]):
        """全量重建索引"""
        self.paths = paths
        self.signatures = signatures
        embeddings = []
        total = len(paths)
        for i in range(0, total, self.batch_size):
            batch = paths[i: i + self.batch_size]
            print(f"   编码: [{i+len(batch)}/{total}] 当前批次 {len(batch)} 张")
            emb = self._encode_batch(batch)
            embeddings.append(emb)
        if embeddings:
            self.vectors = torch.cat(embeddings, dim=0)
        else:
            self.vectors = torch.empty((0, self.truncate_dim), device=self.device)

    def _incremental_update(self, to_remove: set, to_add_update: set, new_signatures: dict, ordered_paths: List[str]):
        """增量更新：保留未变的向量，只重新编码新增/变更的图片"""
        # 保留未删除且未变更的图片
        keep_paths = [p for p in self.paths if p not in to_remove and p not in to_add_update]
        keep_path_to_idx = {p: i for i, p in enumerate(self.paths)}
        keep_indices = [keep_path_to_idx[p] for p in keep_paths]
        if keep_indices:
            keep_vectors = self.vectors[keep_indices]
        else:
            keep_vectors = torch.empty((0, self.truncate_dim), device=self.device)

        # 编码新增或变更的图片
        add_paths = sorted(list(to_add_update))
        add_vectors_list = []
        for i in range(0, len(add_paths), self.batch_size):
            batch = add_paths[i: i + self.batch_size]
            print(f"   增量编码: [{i+len(batch)}/{len(add_paths)}] 当前批次 {len(batch)} 张")
            emb = self._encode_batch(batch)
            add_vectors_list.append(emb)
        if add_vectors_list:
            add_vectors = torch.cat(add_vectors_list, dim=0)
        else:
            add_vectors = torch.empty((0, self.truncate_dim), device=self.device)

        # 按 ordered_paths 的最终顺序重组向量矩阵
        keep_path_to_local = {p: i for i, p in enumerate(keep_paths)}
        add_path_to_local = {p: i for i, p in enumerate(add_paths)}
        self.paths = []
        self.signatures = new_signatures
        vectors_list = []
        for p in ordered_paths:
            self.paths.append(p)
            if p in keep_path_to_local:
                idx = keep_path_to_local[p]
                vectors_list.append(keep_vectors[idx: idx+1])
            else:
                idx = add_path_to_local[p]
                vectors_list.append(add_vectors[idx: idx+1])
        if vectors_list:
            self.vectors = torch.cat(vectors_list, dim=0)
        else:
            self.vectors = torch.empty((0, self.truncate_dim), device=self.device)

    def build_or_update(self, image_folder: str):
        """构建新索引或增量更新已有索引"""
        current_paths = collect_images(image_folder)
        current_sigs = {p: get_file_signature(p) for p in current_paths}

        # 尝试加载已有索引
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
                    print("✅ 索引已是最新，无需更新")
                    return

                print(f"🔄 增量更新: +{len(to_add)} 新增, -{len(to_remove)} 删除, ~{len(to_update)} 变更")
                self._incremental_update(to_remove, to_add | to_update, current_sigs, current_paths)
            except Exception as e:
                print(f"⚠️ 索引文件损坏或版本不兼容 ({e})，将执行全量重建...")
                self._full_rebuild(current_paths, current_sigs)
        else:
            print("🆕 首次构建索引...")
            self._full_rebuild(current_paths, current_sigs)

        self._save_index()
        print(f"💾 索引已保存至 {self.index_dir}\n")

    def search(self, query_text: str, coarse_k: int = 100, final_k: int = 5) -> List[Dict]:
        """
        文本查图片：两阶段检索
        1. CLIP 文本 -> 向量 -> 粗排 (cosine相似度)
        2. Reranker 精排 (query_type="text", doc_type="image")
        """
        print(f"📝 文本查询: '{query_text}'")

        # ---------- 1. CLIP 粗排 ----------
        with torch.no_grad():
            query_embedding = self.clip_model.encode_text(
                query_text,
                task='retrieval.query',
                truncate_dim=self.truncate_dim
            )
            query_embedding = to_tensor(query_embedding, self.device)

        similarities = (query_embedding @ self.vectors.T).squeeze(0)
        similarities = similarities.cpu().float().numpy()

        total = len(self.paths)
        if total == 0:
            print("⚠️ 索引为空，无法检索")
            return []

        actual_coarse_k = min(coarse_k, total)
        top_indices = np.argsort(similarities)[::-1][:actual_coarse_k]
        coarse_paths = [self.paths[i] for i in top_indices]
        coarse_clip_scores = [float(similarities[i]) for i in top_indices]

        print(f"🔍 CLIP 粗排: 从 {total} 张图中选出 {len(coarse_paths)} 个候选")

        # ---------- 2. Reranker 精排 ----------
        self._load_reranker()
        pairs = [[query_text, img_path] for img_path in coarse_paths]

        with torch.no_grad():
            rerank_scores = self.reranker.compute_score(
                pairs,
                max_length=2048,
                doc_type="image",
                query_type="text"
            )
            rerank_scores = [float(score) for score in rerank_scores]

        combined = list(zip(coarse_paths, coarse_clip_scores, rerank_scores))
        combined.sort(key=lambda x: x[2], reverse=True)

        final_results = []
        for rank, (path, clip_score, rerank_score) in enumerate(combined[:final_k], start=1):
            final_results.append({
                "rank": rank,
                "score": rerank_score,
                "clip_score": clip_score,
                "path": path
            })

        return final_results

    def search_by_image(self, query_image_path: str, coarse_k: int = 100, final_k: int = 5) -> List[Dict]:
        """
        图片查图片：两阶段检索
        1. CLIP 编码查询图片 -> 向量 -> 粗排
        2. Reranker 精排 (query_type="image", doc_type="image")
        """
        print(f"🖼️ 图片查询: '{query_image_path}'")

        # 检查查询图片是否存在
        if not os.path.exists(query_image_path):
            raise FileNotFoundError(f"查询图片不存在: {query_image_path}")

        # ---------- 1. CLIP 粗排 ----------
        with torch.no_grad():
            # 编码查询图片
            query_embedding = self.clip_model.encode_image(
                [query_image_path],
                truncate_dim=self.truncate_dim
            )
            query_embedding = to_tensor(query_embedding, self.device).squeeze(0)  # [D]

        similarities = (query_embedding @ self.vectors.T).cpu().float().numpy()  # [N]

        total = len(self.paths)
        if total == 0:
            print("⚠️ 索引为空，无法检索")
            return []

        actual_coarse_k = min(coarse_k, total)
        top_indices = np.argsort(similarities)[::-1][:actual_coarse_k]
        coarse_paths = [self.paths[i] for i in top_indices]
        coarse_clip_scores = [float(similarities[i]) for i in top_indices]

        print(f"🔍 CLIP 粗排: 从 {total} 张图中选出 {len(coarse_paths)} 个候选")

        # ---------- 2. Reranker 精排 ----------
        self._load_reranker()
        # 构造 (query_image_path, doc_image_path) 对
        pairs = [[query_image_path, img_path] for img_path in coarse_paths]

        with torch.no_grad():
            rerank_scores = self.reranker.compute_score(
                pairs,
                max_length=2048,
                doc_type="image",
                query_type="image"
            )
            rerank_scores = [float(score) for score in rerank_scores]

        combined = list(zip(coarse_paths, coarse_clip_scores, rerank_scores))
        combined.sort(key=lambda x: x[2], reverse=True)

        final_results = []
        for rank, (path, clip_score, rerank_score) in enumerate(combined[:final_k], start=1):
            final_results.append({
                "rank": rank,
                "score": rerank_score,
                "clip_score": clip_score,
                "path": path
            })

        return final_results

def main():
    parser = argparse.ArgumentParser(description="本地图片语义搜索（CLIP 粗排 + Reranker 精排）")
    parser.add_argument("--build", action="store_true", help="仅构建/更新索引，不执行查询")
    parser.add_argument("--query", type=str, default=None, help="文本查询")
    parser.add_argument("--image-query", type=str, default=None, help="图片查询（本地路径）")
    parser.add_argument("--coarse-k", type=int, default=100, help="粗排数量（CLIP 检索）")
    parser.add_argument("--top-k", type=int, default=5, help="最终返回数量（精排后）")
    parser.add_argument("--folder", type=str, default=IMAGE_FOLDER, help="图片文件夹路径")
    parser.add_argument("--index-dir", type=str, default=INDEX_DIR, help="索引保存目录")
    args = parser.parse_args()

    # 检查查询参数互斥
    if args.query is None and args.image_query is None:
        print("⚠️ 请提供 --query 或 --image-query 参数进行搜索。")
        return
    if args.query is not None and args.image_query is not None:
        print("⚠️ --query 和 --image-query 不能同时使用，请选择一种查询方式。")
        return

    # 设备与模型加载
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🔧 使用设备: {device}")
    if device == "cpu":
        print("⚠️ 警告: 未检测到 GPU。CPU 运行可能非常缓慢，建议在有 CUDA 的环境下运行。")

    print("⏳ 正在加载 jina-clip-v2 模型...")
    clip_model = AutoModel.from_pretrained(
        CLIP_MODEL_PATH,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16 if device == "cuda" else torch.float32
    ).to(device)
    clip_model.eval()
    print("✅ CLIP 模型加载完成\n")

    # 初始化索引并构建/更新
    index = ImageIndex(
        index_dir=args.index_dir,
        clip_model=clip_model,
        device=device,
        truncate_dim=TRUNCATE_DIM,
        batch_size=BATCH_SIZE,
        reranker_path=RERANKER_PATH
    )
    index.build_or_update(args.folder)

    if args.build:
        print("🏗️ 索引构建完成，已退出")
        return

    # 执行搜索
    if args.query is not None:
        results = index.search(args.query, coarse_k=args.coarse_k, final_k=args.top_k)
        query_info = {"type": "text", "content": args.query}
    else:  # args.image_query is not None
        results = index.search_by_image(args.image_query, coarse_k=args.coarse_k, final_k=args.top_k)
        query_info = {"type": "image", "content": args.image_query}

    # 输出结果
    print(f"\n{'='*60}")
    if query_info["type"] == "text":
        print(f"🔍 文本查询: \"{query_info['content']}\"")
    else:
        print(f"🔍 图片查询: \"{query_info['content']}\"")
    print(f"🏆 Top-{args.top_k} 精排结果 (总计索引 {len(index.paths)} 张)")
    print(f"{'='*60}")
    for r in results:
        print(f"{r['rank']}. Rerank得分: {r['score']:.4f}  |  CLIP得分: {r['clip_score']:.4f}  |  {r['path']}")

    # 保存 JSON
    output_json = "search_results.json"
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump({
            "query": query_info,
            "coarse_k": args.coarse_k,
            "final_k": args.top_k,
            "total_indexed": len(index.paths),
            "device": str(device),
            "results": results
        }, f, ensure_ascii=False, indent=2)
    print(f"\n💾 结果已保存至: {output_json}")

if __name__ == "__main__":
    main()
