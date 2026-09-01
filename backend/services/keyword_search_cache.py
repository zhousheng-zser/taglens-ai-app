"""标签搜索记忆化：唯一 keyword 向量 + 图片标签映射 + (查询标签, keyword) 相似度缓存。"""
from __future__ import annotations

import threading
import time
from array import array
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

import numpy as np

from services.search_progress import SearchProgress

_KEYWORD_VEC_CACHE: Dict[str, np.ndarray] = {}
_QUERY_KEYWORD_SIM_CACHE: Dict[Tuple[str, str], float] = {}
_WARMED_QUERY_TAGS: set[str] = set()
_MAPPING_IMAGE_IDS: array = array("I")
_MAPPING_KEYWORDS: List[str] = []
_CACHE_LOCK = threading.RLock()
_KEYWORDS_LOADED = False
_MAPPING_LOADED = False
_LOADING = False
_LOADED_AT: Optional[str] = None
_LAST_LOAD_SECONDS: Optional[float] = None
_DB_DISTINCT_COUNT: Optional[int] = None
_MAPPING_ROW_COUNT: Optional[int] = None
_MAPPING_IMAGE_COUNT: Optional[int] = None


class KeywordCacheNotLoadedError(Exception):
    """标签向量库未加载，需先手动加载。"""


class KeywordCacheLoadingError(Exception):
    """标签向量库正在加载中。"""


class KeywordCacheAlreadyLoadedError(Exception):
    """标签向量库已加载，请使用重载。"""


def _cache_fully_loaded() -> bool:
    return _KEYWORDS_LOADED and bool(_KEYWORD_VEC_CACHE) and _MAPPING_LOADED


def get_cache_stats() -> Dict[str, int]:
    with _CACHE_LOCK:
        return {
            "keyword_vectors": len(_KEYWORD_VEC_CACHE),
            "query_keyword_pairs": len(_QUERY_KEYWORD_SIM_CACHE),
            "mapping_rows": len(_MAPPING_KEYWORDS),
        }


def get_keyword_cache_status() -> Dict[str, Any]:
    with _CACHE_LOCK:
        loaded = _cache_fully_loaded()
        image_ids = _MAPPING_IMAGE_IDS
        image_count = len(set(image_ids)) if image_ids else 0
        return {
            "loaded": loaded,
            "loading": _LOADING,
            "keywordCount": len(_KEYWORD_VEC_CACHE),
            "queryPairCount": len(_QUERY_KEYWORD_SIM_CACHE),
            "mappingRowCount": len(_MAPPING_KEYWORDS),
            "mappingImageCount": _MAPPING_IMAGE_COUNT if _MAPPING_IMAGE_COUNT is not None else image_count,
            "loadedAt": _LOADED_AT,
            "lastLoadSeconds": _LAST_LOAD_SECONDS,
            "dbDistinctCount": _DB_DISTINCT_COUNT,
        }


def release_keyword_cache() -> Dict[str, Any]:
    """从内存释放标签向量库与图片标签映射（全部网页共用同一后端进程缓存）。"""
    global _KEYWORDS_LOADED, _MAPPING_LOADED, _LOADING, _LOADED_AT, _LAST_LOAD_SECONDS
    global _DB_DISTINCT_COUNT, _MAPPING_ROW_COUNT, _MAPPING_IMAGE_COUNT
    global _MAPPING_IMAGE_IDS, _MAPPING_KEYWORDS
    with _CACHE_LOCK:
        if _LOADING:
            raise KeywordCacheLoadingError("标签向量库正在加载中，请稍后再释放")
        _KEYWORD_VEC_CACHE.clear()
        _QUERY_KEYWORD_SIM_CACHE.clear()
        _WARMED_QUERY_TAGS.clear()
        _MAPPING_IMAGE_IDS = array("I")
        _MAPPING_KEYWORDS = []
        _KEYWORDS_LOADED = False
        _MAPPING_LOADED = False
        _LOADED_AT = None
        _LAST_LOAD_SECONDS = None
        _DB_DISTINCT_COUNT = None
        _MAPPING_ROW_COUNT = None
        _MAPPING_IMAGE_COUNT = None
    print("[keyword_cache] 已释放内存中的标签向量库与图片标签映射")
    return get_keyword_cache_status()


def invalidate_keyword_search_cache() -> None:
    """兼容旧调用：等同于 release。"""
    try:
        release_keyword_cache()
    except KeywordCacheLoadingError:
        pass


def require_keyword_vectors_loaded(progress: Optional[SearchProgress] = None) -> int:
    """搜索前检查：未加载则抛错，已加载则返回唯一标签数。"""
    with _CACHE_LOCK:
        if _cache_fully_loaded():
            if progress:
                progress.report(
                    "cache",
                    45,
                    (
                        f"标签库已就绪（{len(_KEYWORD_VEC_CACHE)} 个唯一标签，"
                        f"{len(_MAPPING_KEYWORDS)} 条图片标签映射）"
                    ),
                )
            return len(_KEYWORD_VEC_CACHE)
    raise KeywordCacheNotLoadedError("标签向量库未加载，请先点击「加载标签」")


def _load_image_keyword_mapping(cursor, progress: Optional[SearchProgress] = None) -> int:
    global _MAPPING_LOADED, _MAPPING_ROW_COUNT, _MAPPING_IMAGE_COUNT
    global _MAPPING_IMAGE_IDS, _MAPPING_KEYWORDS

    if progress:
        progress.report("mapping", 42, "正在加载图片标签映射…")

    t0 = time.time()
    cursor.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM keyword_embeddings ke
        INNER JOIN images i ON i.id = ke.image_id
        """
    )
    expected = max(1, int(cursor.fetchone()["cnt"]))

    with _CACHE_LOCK:
        _MAPPING_IMAGE_IDS = array("I")
        _MAPPING_KEYWORDS = []
        _MAPPING_LOADED = False
        _MAPPING_ROW_COUNT = expected

    cursor.execute(
        """
        SELECT ke.image_id, ke.keyword
        FROM keyword_embeddings ke
        INNER JOIN images i ON i.id = ke.image_id
        ORDER BY ke.image_id
        """
    )

    loaded = 0
    last_image_id: Optional[int] = None
    unique_images = 0
    chunk_size = 100_000
    local_image_ids = array("I")
    local_keywords: List[str] = []

    while True:
        batch = cursor.fetchmany(chunk_size)
        if not batch:
            break
        for row in batch:
            image_id = int(row["image_id"])
            keyword = row["keyword"]
            if last_image_id != image_id:
                unique_images += 1
                last_image_id = image_id
            local_image_ids.append(image_id)
            local_keywords.append(keyword)
            loaded += 1

        if progress:
            progress.check_cancelled()
            pct = 42 + min(55, (loaded / expected) * 55)
            progress.report(
                "mapping",
                pct,
                f"正在加载图片标签映射（{loaded}/{expected}）…",
            )

    with _CACHE_LOCK:
        _MAPPING_IMAGE_IDS = local_image_ids
        _MAPPING_KEYWORDS = local_keywords
        _MAPPING_LOADED = True
        _MAPPING_IMAGE_COUNT = unique_images

    elapsed = time.time() - t0
    print(
        f"[keyword_cache] 已加载图片标签映射 {loaded} 条 "
        f"（{unique_images} 张图片）, 耗时={elapsed:.2f}s"
    )
    return loaded


def scan_image_keyword_similarities(
    tag_labels: List[str],
    num_queries: int,
    progress: Optional[SearchProgress] = None,
) -> Tuple[DefaultDict[int, List[float]], set[int], int, int, int]:
    """
    在内存中扫描图片–标签映射，返回每张图对各查询标签的最高相似度。
    """
    with _CACHE_LOCK:
        if not _MAPPING_LOADED:
            raise KeywordCacheNotLoadedError("图片标签映射未加载，请先点击「加载标签」")
        image_ids = _MAPPING_IMAGE_IDS
        keywords = _MAPPING_KEYWORDS

    total = len(keywords)
    if progress:
        progress.report("scan", 56, f"正在内存匹配图片标签（共 {total} 条）…")

    image_query_max: DefaultDict[int, List[float]] = defaultdict(lambda: [-1.0] * num_queries)
    rows_with_keywords_set: set[int] = set()
    cache_hits = 0
    cache_miss = 0

    for idx in range(total):
        if idx > 0 and idx % 100_000 == 0:
            if progress:
                progress.check_cancelled()
                pct = 56 + min(34, (idx / total) * 34)
                progress.report(
                    "scan",
                    pct,
                    f"正在内存匹配图片标签（{idx}/{total}）…",
                )

        image_id = image_ids[idx]
        keyword = keywords[idx]
        rows_with_keywords_set.add(image_id)

        for q_idx, query_tag in enumerate(tag_labels):
            sim = get_query_keyword_similarity(query_tag, keyword)
            if sim is None:
                cache_miss += 1
                continue
            cache_hits += 1
            prev = image_query_max[image_id][q_idx]
            if sim > prev:
                image_query_max[image_id][q_idx] = sim

    if progress and total > 0:
        progress.report("scan", 90, f"内存匹配完成（{total}/{total}）…")

    return image_query_max, rows_with_keywords_set, total, cache_hits, cache_miss


def load_keyword_vectors(
    cursor,
    *,
    force_reload: bool = False,
    progress: Optional[SearchProgress] = None,
) -> int:
    """从 DB 加载唯一 keyword 向量与图片标签映射到进程内存。"""
    global _KEYWORDS_LOADED, _LOADING, _LOADED_AT, _LAST_LOAD_SECONDS, _DB_DISTINCT_COUNT
    global _MAPPING_LOADED, _MAPPING_ROW_COUNT, _MAPPING_IMAGE_COUNT
    global _MAPPING_IMAGE_IDS, _MAPPING_KEYWORDS

    with _CACHE_LOCK:
        if _LOADING:
            raise KeywordCacheLoadingError("标签向量库正在加载中，请稍候")
        if not force_reload and _cache_fully_loaded():
            raise KeywordCacheAlreadyLoadedError(
                f"标签库已加载（{len(_KEYWORD_VEC_CACHE)} 个唯一标签，"
                f"{len(_MAPPING_KEYWORDS)} 条映射），如需刷新请点击「重载标签」"
            )
        if force_reload:
            _KEYWORD_VEC_CACHE.clear()
            _QUERY_KEYWORD_SIM_CACHE.clear()
            _WARMED_QUERY_TAGS.clear()
            _MAPPING_IMAGE_IDS = array("I")
            _MAPPING_KEYWORDS = []
            _KEYWORDS_LOADED = False
            _MAPPING_LOADED = False
            _LOADED_AT = None
            _MAPPING_ROW_COUNT = None
            _MAPPING_IMAGE_COUNT = None
        _LOADING = True

    if progress:
        progress.report("cache", 5, "正在加载 keyword 向量…")

    t0 = time.time()
    loaded = 0
    bad_dim = 0
    expected = 1

    try:
        cursor.execute("SELECT COUNT(DISTINCT keyword) AS cnt FROM keyword_embeddings")
        expected = max(1, int(cursor.fetchone()["cnt"]))

        with _CACHE_LOCK:
            _DB_DISTINCT_COUNT = expected

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
                pct = 5 + min(35, (loaded / expected) * 35)
                progress.report(
                    "cache",
                    pct,
                    f"正在加载 keyword 向量（{loaded}/{expected}）…",
                )

        with _CACHE_LOCK:
            _KEYWORDS_LOADED = True

        mapping_rows = _load_image_keyword_mapping(cursor, progress)

        elapsed = time.time() - t0
        with _CACHE_LOCK:
            _LOADED_AT = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            _LAST_LOAD_SECONDS = round(elapsed, 2)

        stats = get_cache_stats()
        print(
            f"[keyword_cache] 已加载唯一 keyword 向量 {stats['keyword_vectors']} 个 "
            f"(本次新增 {loaded}, 坏维度 {bad_dim}), 映射 {mapping_rows} 条, 耗时={elapsed:.2f}s"
        )
        if progress:
            progress.report(
                "cache",
                100,
                (
                    f"加载完成：{stats['keyword_vectors']} 个唯一标签，"
                    f"{mapping_rows} 条图片标签映射"
                ),
            )
        return stats["keyword_vectors"]
    finally:
        with _CACHE_LOCK:
            _LOADING = False


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


def patch_image_keywords_in_cache(
    image_id: int,
    keyword_embedding_pairs: List[Tuple[str, bytes]],
) -> bool:
    """
    若关键词向量库已加载，增量更新单张图的关键词映射与全局 keyword 向量。
  返回是否成功同步到内存缓存。
    """
    global _MAPPING_IMAGE_IDS, _MAPPING_KEYWORDS, _MAPPING_ROW_COUNT

    with _CACHE_LOCK:
        if not _cache_fully_loaded():
            return False

        old_keywords = {
            _MAPPING_KEYWORDS[idx]
            for idx, iid in enumerate(_MAPPING_IMAGE_IDS)
            if int(iid) == int(image_id)
        }

        new_image_ids = array("I")
        new_keywords: List[str] = []
        for idx, iid in enumerate(_MAPPING_IMAGE_IDS):
            if int(iid) != int(image_id):
                new_image_ids.append(int(iid))
                new_keywords.append(_MAPPING_KEYWORDS[idx])

        for keyword, embedding_bytes in keyword_embedding_pairs:
            vec = np.frombuffer(embedding_bytes, dtype=np.float32)
            norm = float(np.linalg.norm(vec))
            if norm <= 0:
                continue
            normalized = (vec / norm).astype(np.float32, copy=False)

            kw = str(keyword).strip()
            if not kw:
                continue
            if kw not in _KEYWORD_VEC_CACHE:
                _KEYWORD_VEC_CACHE[kw] = normalized
            new_image_ids.append(int(image_id))
            new_keywords.append(kw)

        removed_keywords = old_keywords - {kw for kw, _ in keyword_embedding_pairs}
        if removed_keywords:
            keys_to_drop = [
                key
                for key in list(_QUERY_KEYWORD_SIM_CACHE.keys())
                if key[1] in removed_keywords
            ]
            for key in keys_to_drop:
                _QUERY_KEYWORD_SIM_CACHE.pop(key, None)

        _MAPPING_IMAGE_IDS = new_image_ids
        _MAPPING_KEYWORDS = new_keywords
        _MAPPING_ROW_COUNT = len(new_keywords)
        return True
