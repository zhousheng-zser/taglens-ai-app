"""Jina Reranker（jina-clip-v2/reranker）精排服务。"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List, Optional, Sequence

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# 与 CLIP 同树但独立子目录，避免与 jina-clip-v2/config.json 混用
RERANKER_DIR = Path(
    os.getenv("JINA_RERANKER_DIR", str(BASE_DIR / "jina-clip-v2" / "reranker"))
)
RERANK_BATCH_SIZE = int(os.getenv("JINA_RERANK_BATCH_SIZE", "8"))
RERANK_MAX_LENGTH = int(os.getenv("JINA_RERANK_MAX_LENGTH", "2048"))
# 默认固定 cuda:2，避开 0 号卡；可用环境变量覆盖（cuda:1 / cpu 等）
RERANKER_DEVICE = os.getenv("JINA_RERANKER_DEVICE", "cuda:2").strip().lower()

_reranker = None
_device = None
_lock = threading.Lock()
_infer_lock = threading.Lock()


def _pick_device() -> str:
    """选择设备：默认避开已占满的 GPU0，优先空闲卡。"""
    import torch

    pref = RERANKER_DEVICE
    if pref == "cpu" or not torch.cuda.is_available():
        return "cpu"
    if pref.startswith("cuda"):
        return pref if ":" in pref else "cuda:0"

    # auto：选 free 最大的 GPU（通常是 1/2，避免与 DTC/CLIP 抢 0 号卡）
    best_idx = 0
    best_free = -1
    for i in range(torch.cuda.device_count()):
        free_b, _total = torch.cuda.mem_get_info(i)
        if free_b > best_free:
            best_free = free_b
            best_idx = i
    return f"cuda:{best_idx}"


def get_reranker():
    """懒加载 Reranker（仅从 jina-clip-v2/reranker 本地目录加载）。"""
    global _reranker, _device
    if _reranker is not None:
        return _reranker, _device

    with _lock:
        if _reranker is not None:
            return _reranker, _device

        if not RERANKER_DIR.is_dir():
            raise FileNotFoundError(f"Reranker 目录不存在: {RERANKER_DIR}")
        if not (RERANKER_DIR / "model.safetensors").is_file():
            raise FileNotFoundError(f"缺少 model.safetensors: {RERANKER_DIR}")
        if not (RERANKER_DIR / "config.json").is_file():
            raise FileNotFoundError(f"缺少 config.json: {RERANKER_DIR}")

        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        import torch
        from transformers import AutoModel

        device = _pick_device()
        print(f"[jina_reranker] 正在加载 {RERANKER_DIR} → {device}（torch_dtype=auto）…")

        model = AutoModel.from_pretrained(
            str(RERANKER_DIR),
            torch_dtype="auto",
            trust_remote_code=True,
            local_files_only=True,
        )
        model.to(device)
        model.eval()

        _reranker = model
        _device = device
        print(f"[jina_reranker] 模型就绪 device={device}")
        return _reranker, _device


def rerank_text_pairs(
    query: str,
    documents: Sequence[str],
    *,
    batch_size: Optional[int] = None,
    max_length: Optional[int] = None,
) -> List[float]:
    """
    对 (query, document) 文本对打精排分，返回与 documents 同序的 [0,1] 分数。
    """
    query = (query or "").strip()
    if not documents:
        return []
    if not query:
        return [0.0] * len(documents)

    model, _device = get_reranker()
    bs = batch_size or RERANK_BATCH_SIZE
    ml = max_length or RERANK_MAX_LENGTH
    pairs = [[query, (doc or "").strip() or " "] for doc in documents]

    with _infer_lock:
        scores = model.compute_score(
            pairs,
            batch_size=bs,
            max_length=ml,
            query_type="text",
            doc_type="text",
        )

    if isinstance(scores, (int, float)):
        return [float(scores)]
    return [float(s) for s in scores]
