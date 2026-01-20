from typing import List, Dict, Any, Optional, Tuple
import pymysql
import paramiko
import time
from datetime import datetime
import json
import os
import threading
from pathlib import Path

# Monkey patch for compatibility between sshtunnel and paramiko >= 3.0
if not hasattr(paramiko, "DSSKey"):
    class FakeDSSKey:
        pass
    paramiko.DSSKey = FakeDSSKey

from sshtunnel import SSHTunnelForwarder

class BusinessStructureManager:
    """
    业务目录结构管理类
    - 初始化时优先读取本地文件
    - 若无本地文件，则从远程数据库拉取
    - 内存中维护 id -> info 的字典映射
    - 提供根据 ubi_short_id 获取目录结构的接口
    """

    # Configuration
    SSH_HOST = "192.168.1.10"
    SSH_PORT = 61008
    SSH_USER = "root"
    SSH_PASSWORD = "md@xinxi2022" 

    DB_HOST = "10.31.243.3"
    DB_PORT = 3306
    DB_USER = "webadmin"
    DB_PASSWORD = "3edcVFR$"
    DB_NAME = "web-op"

    # Local storage path
    DATA_DIR = Path(__file__).parent.parent.parent / "data"
    OUTPUT_FILE = DATA_DIR / "business_structure_map.json"

    def __init__(self):
        self._data_map: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        
        # Ensure data dir exists
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        self._load_data()

    def _load_data(self):
        """加载数据：优先本地，失败则远程同步"""
        if self.OUTPUT_FILE.exists():
            print(f"[BusinessStructureManager] 发现本地缓存文件: {self.OUTPUT_FILE}")
            try:
                with open(self.OUTPUT_FILE, "r", encoding="utf-8") as f:
                    self._data_map = json.load(f)
                print(f"[BusinessStructureManager] 本地缓存加载成功，共 {len(self._data_map)} 条记录")
                return
            except Exception as e:
                print(f"[BusinessStructureManager] 本地缓存已损坏，将重新同步: {e}")
        
        # 如果文件不存在或加载失败，从远程同步
        self.sync_from_remote()

    def sync_from_remote(self):
        """从远程数据库全量同步数据到本地文件和内存"""
        print(f"[BusinessStructureManager] 开始从远程数据库同步数据...")
        try:
            raw_list = self._fetch_all_from_db()
            
            # 转换为以 ubi_short_id 为 Key 的字典
            # "ubi_short_id used as string key in JSON"
            new_map = {}
            for item in raw_list:
                uid = str(item.get("ubi_short_id"))
                if uid:
                    # 只保留有效数据
                    new_map[uid] = {
                        "sz_name": item.get("sz_name", ""),
                        "szTagRef1": item.get("szTagRef1", ""),
                        "szTagRef2": item.get("szTagRef2", ""),
                        "szTagRef3": item.get("szTagRef3", "")
                    }
            
            # 保存到本地
            tmp_file = self.OUTPUT_FILE.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(new_map, f, ensure_ascii=False, indent=2)
            
            if self.OUTPUT_FILE.exists():
                try:
                    os.unlink(self.OUTPUT_FILE)
                except:
                    pass
            os.rename(tmp_file, self.OUTPUT_FILE)
            
            # 更新内存
            with self._lock:
                self._data_map = new_map
                
            print(f"[BusinessStructureManager] 同步完成! 已保存 {len(new_map)} 条记录到 {self.OUTPUT_FILE}")
            
        except Exception as e:
            print(f"[BusinessStructureManager] 同步失败: {e}")
            import traceback
            traceback.print_exc()

    import time
    def _fetch_all_from_db(self) -> List[Dict[str, Any]]:
        """连接数据库并拉取所有数据"""
        print(f"[BusinessStructureManager] 正在连接 SSH 隧道 ({self.SSH_HOST})...")
        
        all_results = []
        start_time = time.time() # Start timing
        
        # Create SSH Tunnel
        with SSHTunnelForwarder(
            (self.SSH_HOST, self.SSH_PORT),
            ssh_username=self.SSH_USER,
            ssh_password=self.SSH_PASSWORD,
            remote_bind_address=(self.DB_HOST, self.DB_PORT)
        ) as tunnel:
            print(f"[BusinessStructureManager] SSH 隧道已建立 (Port: {tunnel.local_bind_port})")
            
            # Connect to Database
            print(f"[BusinessStructureManager] 正在连接 MySQL ({self.DB_HOST})...")
            connection = pymysql.connect(
                host='127.0.0.1',
                port=tunnel.local_bind_port,
                user=self.DB_USER,
                password=self.DB_PASSWORD,
                database=self.DB_NAME,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=20,
                charset='gbk' 
            )
            
            try:
                print("[BusinessStructureManager] 数据库连接成功，开始批量拉取数据...")
                limit = 2000
                offset = 0
                
                start_load = time.time()
                with connection.cursor() as cursor:
                    sql = """
                        SELECT
                          cam.sz_name,
                          cam.ubi_short_id,
                          g1.sz_name AS szTagRef1,
                          g2.sz_name AS szTagRef2,
                          g3.sz_name AS szTagRef3
                        FROM tbl_share_camera_info cam
                        LEFT JOIN View_CameraGroupTag vt 
                          ON vt.ubi_share_camera_id = cam.ubi_share_camera_id
                        LEFT JOIN tbl_share_custom_group g1 
                          ON g1.ubi_group_id = vt.ubi_group_id1
                        LEFT JOIN tbl_share_custom_group g2 
                          ON g2.ubi_group_id = vt.ubi_group_id2
                        LEFT JOIN tbl_share_custom_group g3 
                          ON g3.ubi_group_id = vt.ubi_group_id3
                    """
                    print("[BusinessStructureManager] 正在执行全量查询 (这可能需要一些时间)...")
                    cursor.execute(sql)
                    print(f"[BusinessStructureManager] 查询执行完成 (耗时: {time.time()-start_load:.2f}s). 正在获取结果...")
                    
                    all_results = cursor.fetchall()

                total_time = time.time() - start_time
                print(f"[BusinessStructureManager] 数据拉取完成! 共 {len(all_results)} 条, 总耗时: {total_time:.2f}秒")
                
            finally:
                connection.close()
                print("[BusinessStructureManager] 数据库连接已关闭")
        
        return all_results

    def get_camera_info(self, ubi_short_id: int | str) -> Tuple[str, str]:
        """
        根据 ubi_short_id 获取摄像头信息
        
        Returns:
            (sz_name, full_path_string)
            Example: ("下立交-同济快速路富锦路下立交CMDJ01", "道路监控->快速道路->同济快速路")
        """
        key = str(ubi_short_id)
        info = self._data_map.get(key)
        
        if not info:
             return (f"未知设备({key})", "未知区域")
             
        sz_name = info.get("sz_name") or "未知名称"
        
        # 构建路径字符串，过滤掉 None 或空字符串
        path_parts = []
        if info.get("szTagRef1"): path_parts.append(info.get("szTagRef1"))
        if info.get("szTagRef2"): path_parts.append(info.get("szTagRef2"))
        if info.get("szTagRef3"): path_parts.append(info.get("szTagRef3"))
        
        full_path = "->".join(path_parts) if path_parts else "未分组"
        
        return (sz_name, full_path)

# 单例实例，方便其他模块直接引用
_instance = None

def get_business_manager():
    global _instance
    if _instance is None:
        _instance = BusinessStructureManager()
    return _instance

# 方便测试的主函数
if __name__ == "__main__":
    print("Initializing manager...")
    manager = get_business_manager()
    
    # IDs from your example + the ones you mentioned
    test_ids = [16131, 16132, 9999999]
    
    print("\n--- Testing API Results ---")
    for ubi_id in test_ids:
        name, path = manager.get_camera_info(ubi_id)
        print(f"ID: {ubi_id}")
        print(f"Name: {name}")
        print(f"Path: {path}")
        print("-" * 30)
