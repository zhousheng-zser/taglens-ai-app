"""描述向量搜索记忆化：每图一个 Jina embedding + 矩阵余弦相似度扫描。"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, DefaultDict, Dict, List, Optional, Set, Tuple

import numpy as np

from services.search_progress import SearchProgress

EXPECTED_DIM = 1024

_IMAGE_IDS: List[int] = []
_MATRIX: Optional[np.ndarray] = None  # shape (N, 1024), L2-normalized
_IMAGE_INDEX: Dict[int, int] = {}  # image_id -> row index
_CACHE_LOCK = threading.RLock()
_LOADED = False
_LOADING = False
_LOADED_AT: Optional[str] = None
_LAST_LOAD_SECONDS: Optional[float] = None
_DB_COUNT: Optional[int] = None


class DescriptionCacheNotLoadedError(Exception):
    """描述向量库未加载，需先手动加载。"""


class DescriptionCacheLoadingError(Exception):
    """描述向量库正在加载中。"""


class DescriptionCacheAlreadyLoadedError(Exception):
    """描述向量库已加载，请使用重载。"""


def _cache_fully_loaded() -> bool:
    return _LOADED and _MATRIX is not None and len(_IMAGE_IDS) > 0


def get_cache_stats() -> Dict[str, int]:
    with _CACHE_LOCK:
        return {
            "image_vectors": len(_IMAGE_IDS),
            "dim": EXPECTED_DIM if _MATRIX is not None else 0,
        }


def get_description_cache_status() -> Dict[str, Any]:
    with _CACHE_LOCK:
        return {
            "loaded": _cache_fully_loaded(),
            "loading": _LOADING,
            "imageCount": len(_IMAGE_IDS),
            "dim": EXPECTED_DIM if _MATRIX is not None else 0,
            "loadedAt": _LOADED_AT,
            "lastLoadSeconds": _LAST_LOAD_SECONDS,
            "dbCount": _DB_COUNT,
        }


def release_description_cache() -> Dict[str, Any]:
    """从内存释放描述向量库。"""
    global _IMAGE_IDS, _MATRIX, _IMAGE_INDEX, _LOADED, _LOADING
    global _LOADED_AT, _LAST_LOAD_SECONDS, _DB_COUNT
    with _CACHE_LOCK:
        if _LOADING:
            raise DescriptionCacheLoadingError("描述向量库正在加载中，请稍后再释放")
        _IMAGE_IDS = []
        _MATRIX = None
        _IMAGE_INDEX = {}
        _LOADED = False
        _LOADED_AT = None
        _LAST_LOAD_SECONDS = None
        _DB_COUNT = None
    print("[description_cache] 已释放内存中的描述向量库")
    return get_description_cache_status()


def require_description_vectors_loaded(progress: Optional[SearchProgress] = None) -> int:
    """搜索前检查：未加载则抛错，已加载则返回图片向量数。"""
    with _CACHE_LOCK:
        if _cache_fully_loaded():
            if progress:
                progress.report(
                    "cache",
                    45,
                    f"描述向量库已就绪（{len(_IMAGE_IDS)} 张图片）",
                )
            return len(_IMAGE_IDS)
    raise DescriptionCacheNotLoadedError("描述向量库未加载，请先点击「加载描述向量」")


def load_description_vectors(
    cursor,
    *,
    force_reload: bool = False,
    progress: Optional[SearchProgress] = None,
) -> int:
    """从 DB 加载 description_embeddings 到进程内存。"""
    global _IMAGE_IDS, _MATRIX, _IMAGE_INDEX, _LOADED, _LOADING
    global _LOADED_AT, _LAST_LOAD_SECONDS, _DB_COUNT

    with _CACHE_LOCK:
        if _LOADING:
            raise DescriptionCacheLoadingError("描述向量库正在加载中，请稍候")
        if not force_reload and _cache_fully_loaded():
            raise DescriptionCacheAlreadyLoadedError(
                f"描述向量库已加载（{len(_IMAGE_IDS)} 张图片），如需刷新请点击「重载」"
            )
        if force_reload:
            _IMAGE_IDS = []
            _MATRIX = None
            _IMAGE_INDEX = {}
            _LOADED = False
            _LOADED_AT = None
            _DB_COUNT = None
        _LOADING = True

    if progress:
        progress.report("cache", 5, "正在加载 description 向量…")

    t0 = time.time()
    loaded = 0
    bad_dim = 0

    try:
        cursor.execute("SELECT COUNT(*) AS cnt FROM description_embeddings")
        expected = max(1, int(cursor.fetchone()["cnt"]))
        with _CACHE_LOCK:
            _DB_COUNT = expected

        cursor.execute(
            """
            SELECT image_id, embedding
            FROM description_embeddings
            ORDER BY image_id
            """
        )

        local_ids: List[int] = []
        local_vecs: List[np.ndarray] = []
        chunk_size = 20_000

        while True:
            batch = cursor.fetchmany(chunk_size)
            if not batch:
                break
            for row in batch:
                embedding_bytes = row["embedding"]
                if not embedding_bytes:
                    continue
                vec = np.frombuffer(embedding_bytes, dtype=np.float32)
                if len(vec) != EXPECTED_DIM:
                    bad_dim += 1
                    continue
                norm = float(np.linalg.norm(vec))
                if norm <= 0:
                    bad_dim += 1
                    continue
                local_ids.append(int(row["image_id"]))
                local_vecs.append(vec / norm)
                loaded += 1

            if progress:
                progress.check_cancelled()
                pct = 5 + min(90, (loaded / expected) * 90)
                progress.report(
                    "cache",
                    pct,
                    f"正在加载 description 向量（{loaded}/{expected}）…",
                )

        if local_vecs:
            matrix = np.stack(local_vecs).astype(np.float32, copy=False)
            index = {image_id: idx for idx, image_id in enumerate(local_ids)}
        else:
            matrix = None
            index = {}

        elapsed = time.time() - t0
        with _CACHE_LOCK:
            _IMAGE_IDS = local_ids
            _MATRIX = matrix
            _IMAGE_INDEX = index
            _LOADED = bool(local_ids)
            _LOADED_AT = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            _LAST_LOAD_SECONDS = round(elapsed, 2)

        print(
            f"[description_cache] 已加载 description 向量 {loaded} 个 "
            f"(坏维度 {bad_dim}), 耗时={elapsed:.2f}s"
        )
        if progress:
            progress.report("cache", 100, f"加载完成：{loaded} 张图片描述向量")
        return loaded
    finally:
        with _CACHE_LOCK:
            _LOADING = False


def scan_image_description_similarities(
    query_vecs: List[np.ndarray],
    progress: Optional[SearchProgress] = None,
    allowed_image_ids: Optional[Set[int]] = None,
) -> Tuple[DefaultDict[int, List[float]], set[int], int]:
    """
    对每张有描述向量的图，计算对各查询向量的余弦相似度。

    返回:
        image_query_sims: image_id -> [sim_q0, sim_q1, ...]
        rows_with_vectors: 参与计算的 image_id 集合
        row_count: 扫描的向量行数
    """
    with _CACHE_LOCK:
        if not _cache_fully_loaded() or _MATRIX is None:
            raise DescriptionCacheNotLoadedError("描述向量库未加载，请先点击「加载描述向量」")
        image_ids = list(_IMAGE_IDS)
        matrix = _MATRIX
        image_index = dict(_IMAGE_INDEX)

    num_queries = len(query_vecs)
    if num_queries == 0:
        return defaultdict(lambda: []), set(), 0

    if allowed_image_ids is not None:
        row_indices = [
            image_index[iid]
            for iid in allowed_image_ids
            if iid in image_index
        ]
        if not row_indices:
            return defaultdict(lambda: [-1.0] * num_queries), set(), 0
        sub_matrix = matrix[row_indices]
        sub_ids = [image_ids[i] for i in row_indices]
    else:
        sub_matrix = matrix
        sub_ids = image_ids

    total = len(sub_ids)
    if progress:
        progress.report("scan", 56, f"正在计算描述向量相似度（共 {total} 张）…")

    # shape: (num_queries, N)
    query_mat = np.stack(query_vecs).astype(np.float32, copy=False)
    sims_mat = query_mat @ sub_matrix.T

    image_query_sims: DefaultDict[int, List[float]] = defaultdict(
        lambda: [-1.0] * num_queries
    )
    rows_with_vectors: set[int] = set()

    for col_idx, image_id in enumerate(sub_ids):
        rows_with_vectors.add(image_id)
        image_query_sims[image_id] = [float(sims_mat[q, col_idx]) for q in range(num_queries)]

    if progress and total > 0:
        progress.report("scan", 90, f"描述向量匹配完成（{total}/{total}）…")

    return image_query_sims, rows_with_vectors, total


def patch_description_embedding_in_cache(image_id: int, embedding_bytes: bytes) -> bool:
    """若内存缓存已加载，更新或追加单条描述向量。"""
    global _IMAGE_IDS, _MATRIX, _IMAGE_INDEX, _LOADED

    vec = np.frombuffer(embedding_bytes, dtype=np.float32)
    if len(vec) != EXPECTED_DIM:
        return False
    norm = float(np.linalg.norm(vec))
    if norm <= 0:
        return False
    normalized = (vec / norm).astype(np.float32, copy=False)

    with _CACHE_LOCK:
        if not _cache_fully_loaded() or _MATRIX is None:
            return False
        if image_id in _IMAGE_INDEX:
            idx = _IMAGE_INDEX[image_id]
            _MATRIX[idx] = normalized
            return True

        _IMAGE_IDS.append(int(image_id))
        new_idx = len(_IMAGE_IDS) - 1
        _IMAGE_INDEX[int(image_id)] = new_idx
        _MATRIX = np.vstack([_MATRIX, normalized.reshape(1, -1)]).astype(np.float32, copy=False)
        _LOADED = True
        return True


def remove_description_embedding_from_cache(image_id: int) -> bool:
    """若内存缓存已加载，移除单条描述向量。"""
    global _IMAGE_IDS, _MATRIX, _IMAGE_INDEX, _LOADED

    with _CACHE_LOCK:
        if not _cache_fully_loaded() or _MATRIX is None:
            return False
        idx = _IMAGE_INDEX.get(int(image_id))
        if idx is None:
            return False

        keep_mask = np.ones(len(_IMAGE_IDS), dtype=bool)
        keep_mask[idx] = False
        _IMAGE_IDS = [iid for i, iid in enumerate(_IMAGE_IDS) if keep_mask[i]]
        if _IMAGE_IDS:
            _MATRIX = _MATRIX[keep_mask]
            _IMAGE_INDEX = {iid: i for i, iid in enumerate(_IMAGE_IDS)}
            _LOADED = True
        else:
            _MATRIX = None
            _IMAGE_INDEX = {}
            _LOADED = False
        return True
