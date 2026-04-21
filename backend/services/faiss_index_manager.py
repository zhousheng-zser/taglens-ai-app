# -*- coding: utf-8 -*-
"""
Faiss LSH 索引管理模块
用于管理图片特征向量的 Faiss LSH 索引（使用汉明距离）
支持从 MinIO 同步数据
"""
import faiss
import numpy as np
import json
import time
import atexit
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
import threading
from core.minio_storage_client import get_storage_client


class FaissIndexManager:
    """
    Faiss LSH 索引管理器
    使用 IndexLSH - 汉明距离（快速但精度较低）
    """
    
    def __init__(self, data_dir: str = "/opt/Traffic-LLM/zser/taglens-ai-app/data"):
        """
        初始化索引管理器
        
        参数:
            data_dir: 数据目录，包含索引文件和UUID映射文件
        """
        self.data_dir = Path(data_dir)
        self.index_file = self.data_dir / "faiss_spatial_histogram.index"
        self.index_type = "IndexLSH"
        self.uuid_map_file = self.data_dir / "faiss_uuid_map.json"
        
        # MinIO 配置
        self.minio_prefix = "vector_data"
        self.minio_index_path = f"{self.minio_prefix}/faiss_spatial_histogram.index"
        self.minio_uuid_map_path = f"{self.minio_prefix}/faiss_uuid_map.json"
        
        self.index = None  # IndexLSH
        self.uuid_map: Dict[str, Any] = {}
        self.lock = threading.Lock()  # 线程锁，用于并发安全
        
        # 内存中的"正在处理"列表，用于并发时的临时占位
        # 格式: {temp_uuid: binary_code_numpy_array}
        self.pending_vectors: Dict[str, np.ndarray] = {}
        
        # 上传控制
        self.last_upload_time = 0  # 上次上传时间
        self.upload_interval = 180  # 3分钟（秒）
        self.upload_batch_size = int(os.getenv("FAISS_UPLOAD_BATCH_SIZE", "500"))
        self.flush_hour = int(os.getenv("FAISS_FLUSH_HOUR", "19"))
        self.pending_delete_file = self.data_dir / "faiss_pending_delete_uuids.json"
        self.is_modified = False  # 是否已修改
        self.pending_update_count = 0
        self.last_modified_time = 0.0
        self.pending_delete_uuids: List[str] = []
        self._uploader_stop_event = threading.Event()
        self._uploader_thread: Optional[threading.Thread] = None
        
        # 初始化 MinIO 客户端
        self.storage_client = get_storage_client(skip_bucket_check=True)
        
        # 注册退出时上传
        atexit.register(self._upload_to_minio_on_exit)
        
        # 清空本地数据并从 MinIO 加载
        self._clear_local_data()
        self._load_from_minio()
        self._load_pending_delete_file()
        self._replay_pending_deletes()
        self._start_uploader_thread()
    
    def _clear_local_data(self):
        """清空本地 Faiss 相关数据"""
        try:
            if self.index_file.exists():
                self.index_file.unlink()
            if self.uuid_map_file.exists():
                self.uuid_map_file.unlink()
        except Exception as e:
            pass
    
    def _load_from_minio(self):
        """从 MinIO 加载索引和UUID映射，如果不存在则创建新的"""
        try:
            # 尝试从 MinIO 下载索引文件
            if self.storage_client.file_exists(self.minio_index_path):
                self.storage_client.download_file(self.minio_index_path, str(self.index_file))
            
            # 尝试从 MinIO 下载UUID映射文件
            if self.storage_client.file_exists(self.minio_uuid_map_path):
                self.storage_client.download_file(self.minio_uuid_map_path, str(self.uuid_map_file))
            
            # 加载索引和映射
            self._load_index()
            
        except Exception as e:
            # 如果下载失败，创建新索引
            self._load_index()
    
    def _load_index(self):
        """加载索引和UUID映射"""
        try:
            # 加载索引文件
            if self.index_file.exists():
                self.index = faiss.read_index(str(self.index_file))
            else:
                # 如果索引文件不存在，创建新的索引
                self._create_new_index()
                return
            
            # 加载UUID映射文件
            if self.uuid_map_file.exists():
                with open(self.uuid_map_file, 'r', encoding='utf-8') as f:
                    self.uuid_map = json.load(f)
            else:
                self.uuid_map = {
                    "index_to_uuid": [],
                    "uuid_to_index": {},
                    "total_vectors": 0,
                    "vector_dimension": 9000,
                    "index_type": self.index_type,
                    "nbits": 128
                }
                
        except Exception as e:
            # 如果加载失败，创建新索引
            self._create_new_index()
    
    def _upload_to_minio(self):
        """上传索引和UUID映射到 MinIO"""
        try:
            self.save_index()
            if self.index_file.exists():
                self.storage_client.upload_file(str(self.index_file), self.minio_index_path)
            if self.uuid_map_file.exists():
                self.storage_client.upload_file(str(self.uuid_map_file), self.minio_uuid_map_path)
            self.last_upload_time = time.time()
            self.is_modified = False
            self.pending_update_count = 0
            self.pending_delete_uuids = []
            self._persist_pending_delete_file()
            print("[faiss] flush success, pending delete file cleared")
        except Exception:
            pass
    
    def _upload_to_minio_on_exit(self):
        """程序退出时上传到 MinIO"""
        self._uploader_stop_event.set()
        try:
            if self._uploader_thread and self._uploader_thread.is_alive():
                self._uploader_thread.join(timeout=2.0)
        except Exception:
            pass
        if self.is_modified:
            self._upload_to_minio()
    
    def _mark_modified(self):
        # 调用方应在持有 self.lock 时调用
        self.is_modified = True
        self.pending_update_count += 1
        self.last_modified_time = time.time()

    def _persist_pending_delete_file(self):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.pending_delete_file, "w", encoding="utf-8") as f:
                json.dump(self.pending_delete_uuids, f, ensure_ascii=False)
        except Exception as e:
            print(f"[faiss] persist pending delete file failed: {e}")

    def _load_pending_delete_file(self):
        if not self.pending_delete_file.exists():
            self.pending_delete_uuids = []
            return
        try:
            with open(self.pending_delete_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.pending_delete_uuids = [str(x).strip() for x in data if str(x).strip()]
            else:
                self.pending_delete_uuids = []
            if self.pending_delete_uuids:
                print(f"[faiss] loaded pending deletes: {len(self.pending_delete_uuids)}")
        except Exception as e:
            print(f"[faiss] load pending delete file failed: {e}")
            self.pending_delete_uuids = []

    def _replay_pending_deletes(self):
        if not self.pending_delete_uuids:
            return
        removed = 0
        with self.lock:
            for uid in self.pending_delete_uuids:
                if uid in self.uuid_map.get("uuid_to_index", {}):
                    del self.uuid_map["uuid_to_index"][uid]
                    removed += 1
            if removed > 0:
                self._mark_modified()
        if removed > 0:
            print(f"[faiss] replay pending deletes removed={removed}")

    def _is_flush_time(self) -> bool:
        now = datetime.now()
        return now.hour == self.flush_hour

    def _start_uploader_thread(self):
        def _run():
            while not self._uploader_stop_event.is_set():
                try:
                    should_upload = False
                    with self.lock:
                        if self.is_modified:
                            batch_reached = len(self.pending_delete_uuids) >= self.upload_batch_size
                            should_upload = batch_reached and self._is_flush_time()
                    if should_upload:
                        print(
                            f"[faiss] flush trigger reached pending={len(self.pending_delete_uuids)} "
                            f"hour={datetime.now().hour}"
                        )
                        self._upload_to_minio()
                except Exception:
                    pass
                self._uploader_stop_event.wait(15.0)
        self._uploader_thread = threading.Thread(target=_run, daemon=True, name="faiss-uploader")
        self._uploader_thread.start()
    
    def _create_new_index(self, dim: int = 9000, nbits: int = 128):
        """
        创建新的 LSH 索引
        
        参数:
            dim: 向量维度
            nbits: 二进制签名位数
        """
        if nbits > dim:
            nbits = dim
        self.index = faiss.IndexLSH(dim, nbits)
        self.uuid_map = {
            "index_to_uuid": [],
            "uuid_to_index": {},
            "total_vectors": 0,
            "vector_dimension": dim,
            "nbits": nbits,
            "index_type": "IndexLSH"
        }
    
    def add_vector(self, uuid: str, vector: np.ndarray) -> bool:
        """添加向量到索引"""
        result = False
        with self.lock:
            try:
                if len(vector.shape) != 1:
                    vector = vector.flatten()
                if vector.dtype != np.float32:
                    vector = vector.astype(np.float32)
                if len(vector) != 9000:
                    return False
                if uuid in self.uuid_map.get("uuid_to_index", {}):
                    return False
                vector_2d = vector.reshape(1, -1)
                self.index.add(vector_2d)
                index_id = self.index.ntotal - 1
                self.uuid_map["index_to_uuid"].append(uuid)
                self.uuid_map["uuid_to_index"][uuid] = index_id
                self.uuid_map["total_vectors"] = self.index.ntotal
                self._mark_modified()
                result = True
            except Exception:
                return False
        return result
    
    def search_similar(self, query_vector: np.ndarray, k: int = 1, threshold: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        搜索相似向量
        
        参数:
            query_vector: 查询向量 (numpy数组，float32，9000维)
            k: 返回最相似的k个结果
            threshold: 相似度阈值（LSH返回的是距离，需要转换为相似度）
        
        返回:
            List[Dict]: 相似图片列表，每个包含 uuid, distance, similarity
        """
        with self.lock:
            try:
                if self.index is None or self.index.ntotal == 0:
                    return []
                
                # 验证查询向量
                if len(query_vector.shape) != 1:
                    query_vector = query_vector.flatten()
                
                if query_vector.dtype != np.float32:
                    query_vector = query_vector.astype(np.float32)
                
                expected_dim = 9000
                if len(query_vector) != expected_dim:
                    return []
                
                # 执行搜索
                query_2d = query_vector.reshape(1, -1)
                distances, indices = self.index.search(query_2d, min(k, self.index.ntotal))
                
                # 转换结果
                results = []
                index_to_uuid = self.uuid_map.get("index_to_uuid", [])
                
                for idx, dist in zip(indices[0], distances[0]):
                    if idx < 0 or idx >= len(index_to_uuid):
                        continue
                    
                    uuid = index_to_uuid[idx]
                    
                    # 检查是否已逻辑删除
                    if uuid not in self.uuid_map["uuid_to_index"]:
                        continue

                    distance = float(dist)
                    
                    # IndexLSH 返回的是汉明距离（范围: 0 到 nbits）
                    # 对于LSH，距离越小表示越相似
                    # 获取nbits参数（从索引的元数据或默认值）
                    nbits = self.uuid_map.get("nbits", 128)
                    
                    # 相似度转换公式：
                    # similarity = (nbits - distance) / nbits
                    # 这样距离=0时相似度=1.0，距离=nbits时相似度=0.0
                    if distance <= nbits:
                        similarity = (nbits - distance) / nbits
                    else:
                        # 如果距离超过nbits，相似度为0
                        similarity = 0.0
                    
                    # 确保相似度在[0, 1]范围内
                    similarity = max(0.0, min(1.0, similarity))
                    
                    # 如果设置了阈值，过滤结果
                    if threshold is not None and similarity < threshold:
                        continue
                    
                    results.append({
                        "uuid": uuid,
                        "index": int(idx),
                        "distance": float(dist),
                        "similarity": similarity
                    })
                
                return results
                
            except Exception as e:
                return []
    
    def remove_vector(self, uuid: str) -> bool:
        """
        逻辑删除向量
        Faiss IndexLSH 不支持高效的物理删除，这里从映射表中移除
        """
        with self.lock:
            if uuid in self.uuid_map.get("uuid_to_index", {}):
                del self.uuid_map["uuid_to_index"][uuid]
                self._mark_modified()
                if uuid not in self.pending_delete_uuids:
                    self.pending_delete_uuids.append(uuid)
                    self._persist_pending_delete_file()
                return True
            return False
    
    def check_similarity_exists(self, query_vector: np.ndarray, threshold: float) -> Tuple[bool, float, Optional[str]]:
        """
        检查是否存在相似度 >= threshold 的向量（只检查已入库的）
        建议使用 check_similarity_and_reserve 来防止并发竞争
        """
        results = self.search_similar(query_vector, k=1, threshold=threshold)
        
        if results:
            best = results[0]
            return True, best["similarity"], best["uuid"]
        else:
            return False, 0.0, None

    def _calculate_hamming_similarity(self, code1: np.ndarray, code2: np.ndarray, nbits: int) -> float:
        """计算两个二进制编码的汉明相似度"""
        # 注意: IndexLSH 的 sa_encode 返回的是 packed bytes (uint8)
        # 汉明距离 = 异或后的 1 的个数
        # numpy 异或
        xor_result = np.bitwise_xor(code1, code2)
        # 计算 1 的个数
        distance = np.unpackbits(xor_result).sum()
        
        # 转换为相似度
        if distance <= nbits:
            return (nbits - distance) / nbits
        return 0.0

    def check_similarity_and_reserve(self, query_vector: np.ndarray, threshold: float, reserved_uuid: str) -> Tuple[bool, float, Optional[str], Optional[str]]:
        """
        (线程安全) 检查是否存在相似向量（包括已入库和正在处理中的）。
        如果没有相似，则将此向量加入"正在处理中"列表进行占位。
        
        参数:
            query_vector: 查询向量
            threshold: 相似度阈值
            reserved_uuid: 用于占位的临时UUID（通常是图片的UUID）
            
        返回:
            (是否相似, 最大相似度, 相似UUID, 匹配源['index'|'pending'|None])
            如果是 False，表示已成功占位
        """
        with self.lock:
            try:
                # 1. 先检查已入库的索引
                # 准备数据
                if len(query_vector.shape) != 1:
                    query_vector = query_vector.flatten()
                if query_vector.dtype != np.float32:
                    query_vector = query_vector.astype(np.float32)
                query_2d = query_vector.reshape(1, -1)
                
                # 1.1 搜索 Faiss 索引
                if self.index is not None and self.index.ntotal > 0:
                    distances, indices = self.index.search(query_2d, 1)
                    idx = indices[0][0]
                    dist = distances[0][0]
                    
                    if idx >= 0:
                        nbits = self.uuid_map.get("nbits", 128)
                        similarity = max(0.0, min(1.0, (nbits - dist) / nbits)) if dist <= nbits else 0.0
                        
                        if similarity >= threshold:
                            existing_uuid = self.uuid_map["index_to_uuid"][idx]
                            return True, similarity, existing_uuid, 'index'
                
                # 2. 检查 "正在处理中" (Pending) 的向量
                # 我们需要将 query_vector 编码为二进制码用于比较
                # IndexLSH 提供了 sa_encode 方法
                current_code = self.index.sa_encode(query_2d)[0]
                nbits = self.uuid_map.get("nbits", 128)
                
                best_pending_sim = 0.0
                best_pending_uuid = None
                
                for p_uuid, p_code in self.pending_vectors.items():
                    sim = self._calculate_hamming_similarity(current_code, p_code, nbits)
                    if sim > best_pending_sim:
                        best_pending_sim = sim
                        best_pending_uuid = p_uuid
                
                if best_pending_sim >= threshold:
                    return True, best_pending_sim, best_pending_uuid, 'pending'
                
                # 3. 如果都没有发现相似，则进行占位
                self.pending_vectors[reserved_uuid] = current_code
                return False, 0.0, None, None
                
            except Exception as e:
                print(f"check_similarity_and_reserve error: {e}")
                # 出错时为了安全起见，不阻止处理，返回不相似
                return False, 0.0, None, None

    def remove_pending_vector(self, uuid: str):
        """移除"正在处理中"的向量占位"""
        with self.lock:
            if uuid in self.pending_vectors:
                del self.pending_vectors[uuid]

    def save_index(self, skip_lock: bool = False):
        """保存索引和UUID映射到文件"""
        def _do_save():
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                if self.index is not None:
                    faiss.write_index(self.index, str(self.index_file))
                with open(self.uuid_map_file, 'w', encoding='utf-8') as f:
                    json.dump(self.uuid_map, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
        if skip_lock:
            _do_save()
        else:
            with self.lock:
                _do_save()
    
    def __del__(self):
        """析构函数：程序结束时上传到 MinIO"""
        if self.is_modified:
            try:
                self._upload_to_minio()
            except Exception:
                pass
    
    def get_total_vectors(self) -> int:
        """获取索引中的向量总数"""
        if self.index is None:
            return 0
        return self.index.ntotal


# 全局索引管理器实例（单例模式）
_index_manager: Optional[FaissIndexManager] = None
_index_manager_lock = threading.Lock()


def get_faiss_index_manager() -> FaissIndexManager:
    """
    获取全局 Faiss LSH 索引管理器实例（单例）
    使用 IndexLSH（汉明距离）
    """
    global _index_manager
    
    with _index_manager_lock:
        if _index_manager is None:
            _index_manager = FaissIndexManager()
        return _index_manager
