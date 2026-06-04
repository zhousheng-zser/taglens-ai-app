"""标签搜索记忆化：唯一 keyword 向量 + (查询标签, keyword) 相似度缓存。"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from services.search_progress import SearchProgress

_KEYWORD_VEC_CACHE: Dict[str, np.ndarray] = {}
_QUERY_KEYWORD_SIM_CACHE: Dict[Tuple[str, str], float] = {}
_WARMED_QUERY_TAGS: set[str] = set()
_CACHE_LOCK = threading.RLock()
_KEYWORDS_LOADED = False


def get_cache_stats() -> Dict[str, int]:
    with _CACHE_LOCK:
        return {
            "keyword_vectors": len(_KEYWORD_VEC_CACHE),
            "query_keyword_pairs": len(_QUERY_KEYWORD_SIM_CACHE),
        }


def invalidate_keyword_search_cache() -> None:
    """keyword 向量或 embedding 变更后调用，清空进程内缓存。"""
    global _KEYWORDS_LOADED
    with _CACHE_LOCK:
        _KEYWORD_VEC_CACHE.clear()
        _QUERY_KEYWORD_SIM_CACHE.clear()
        _WARMED_QUERY_TAGS.clear()
        _KEYWORDS_LOADED = False


def ensure_keyword_vectors_loaded(cursor, progress: Optional[SearchProgress] = None) -> int:
    """从 DB 加载全部唯一 keyword 向量（每个 keyword 只保留一条代表 embedding）。"""
    global _KEYWORDS_LOADED
    with _CACHE_LOCK:
        if _KEYWORDS_LOADED and _KEYWORD_VEC_CACHE:
            if progress:
                progress.report(
                    "cache",
                    45,
                    f"keyword 向量缓存已就绪（{len(_KEYWORD_VEC_CACHE)} 个唯一标签）",
                )
            return len(_KEYWORD_VEC_CACHE)

    if progress:
        progress.report("cache", 12, "正在加载 keyword 向量库…")

    t0 = time.time()
    cursor.execute("SELECT COUNT(DISTINCT keyword) AS cnt FROM keyword_embeddings")
    expected = max(1, int(cursor.fetchone()["cnt"]))

    cursor.execute(
        """
        SELECT ke.keyword, ke.embedding
        FROM keyword_embeddings ke
        INNER JOIN (
            SELECT keyword, MIN(id) AS min_id
            FROM keyword_embeddings
            GROUP BY keyword
        ) u ON ke.id = u.min_id
        """
    )

    loaded = 0
    bad_dim = 0
    chunk_size = 20_000
    while True:
        batch = cursor.fetchmany(chunk_size)
        if not batch:
            break
        with _CACHE_LOCK:
            for row in batch:
                keyword = row["keyword"]
                if keyword in _KEYWORD_VEC_CACHE:
                    continue
                embedding_bytes = row["embedding"]
                if not embedding_bytes:
                    continue
                vec = np.frombuffer(embedding_bytes, dtype=np.float32)
                if len(vec) != 768:
                    bad_dim += 1
                    continue
                _KEYWORD_VEC_CACHE[keyword] = vec / np.linalg.norm(vec)
                loaded += 1

        if progress:
            progress.check_cancelled()
            pct = 12 + min(33, (loaded / expected) * 33)
            progress.report(
                "cache",
                pct,
                f"正在加载 keyword 向量（{loaded}/{expected}）…",
            )

    with _CACHE_LOCK:
        _KEYWORDS_LOADED = True

    stats = get_cache_stats()
    print(
        f"[keyword_cache] 已加载唯一 keyword 向量 {stats['keyword_vectors']} 个 "
        f"(本次新增 {loaded}, 坏维度 {bad_dim}), 耗时={time.time() - t0:.2f}s"
    )
    if progress:
        progress.report(
            "cache",
            45,
            f"keyword 向量加载完成（{stats['keyword_vectors']} 个唯一标签）",
        )
    return stats["keyword_vectors"]


def warm_query_keyword_similarities(
    query_tags: List[str],
    query_vecs: List[np.ndarray],
    progress: Optional[SearchProgress] = None,
) -> int:
    """批量预计算并缓存所有 (query_tag, keyword) 相似度，避免逐行重复 dot。"""
    if not query_tags or not query_vecs:
        return 0

    with _CACHE_LOCK:
        keywords = list(_KEYWORD_VEC_CACHE.keys())
        if not keywords:
            return 0

        tags_to_warm: List[str] = []
        vecs_to_warm: List[np.ndarray] = []
        for query_tag, query_vec in zip(query_tags, query_vecs):
            if query_tag not in _WARMED_QUERY_TAGS:
                tags_to_warm.append(query_tag)
                vecs_to_warm.append(query_vec)

        if not tags_to_warm:
            print(
                f"[keyword_cache] 查询标签已全部命中相似度缓存: {query_tags}, "
                f"keyword={len(keywords)}, 对={len(_QUERY_KEYWORD_SIM_CACHE)}"
            )
            if progress:
                progress.report("warm", 55, "查询标签相似度已全部缓存，跳过计算")
            return 0

        if progress:
            progress.check_cancelled()
            progress.report("warm", 48, f"正在计算查询标签与 {len(keywords)} 个 keyword 的相似度…")

        t0 = time.time()
        mat = np.stack([_KEYWORD_VEC_CACHE[kw] for kw in keywords])
        warmed = 0
        for query_tag, query_vec in zip(tags_to_warm, vecs_to_warm):
            sims = mat @ query_vec
            for keyword, sim in zip(keywords, sims):
                key = (query_tag, keyword)
                if key not in _QUERY_KEYWORD_SIM_CACHE:
                    warmed += 1
                _QUERY_KEYWORD_SIM_CACHE[key] = float(sim)
            _WARMED_QUERY_TAGS.add(query_tag)

        print(
            f"[keyword_cache] 预热 query×keyword 相似度: 新查询标签={tags_to_warm}, "
            f"唯一 keyword={len(keywords)}, 新增缓存={warmed}, "
            f"总缓存对数={len(_QUERY_KEYWORD_SIM_CACHE)}, 耗时={time.time() - t0:.2f}s"
        )
        if progress:
            progress.report("warm", 55, "标签相似度计算完成")
        return warmed


def get_query_keyword_similarity(query_tag: str, keyword: str) -> Optional[float]:
    """读取已缓存的 (query_tag, keyword) 相似度。"""
    with _CACHE_LOCK:
        return _QUERY_KEYWORD_SIM_CACHE.get((query_tag, keyword))
