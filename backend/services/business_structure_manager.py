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

PDDY_PROJECT_NAMES = {"浦东道运视频质量诊断", "浦东道运"}

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

    def get_camera_sz_and_tag_refs(self, ubi_short_id: int | str) -> Tuple[str, List[str]]:
        """
        根据 ubi_short_id 返回 (sz_name, [szTagRef1, szTagRef2, ...] 非空项)。
        与业务结构缓存 _data_map 中 szTagRef1~3 一致。
        """
        key = str(ubi_short_id).strip()
        if not key:
            return ("未知设备", [])
        info = self._data_map.get(key)
        if not info:
            return (f"未知设备({key})", [])
        sz_name = (info.get("sz_name") or "").strip() or "未知名称"
        refs: List[str] = []
        for ref_key in ("szTagRef1", "szTagRef2", "szTagRef3"):
            val = info.get(ref_key)
            if val is not None and str(val).strip():
                refs.append(str(val).strip())
        return (sz_name, refs)


class PDDYBusinessStructureManager(BusinessStructureManager):
    """
    浦东道运业务目录结构管理类
    - 02 项目没有 View_CameraGroupTag 视图
    - 改为使用相机表 + 相机分组关系表 + 分组树自行还原目录路径
    """

    SSH_HOST = "192.168.1.10"
    SSH_PORT = 61014
    SSH_USER = "root"
    SSH_PASSWORD = "md@xinxi2022"

    DB_HOST = "127.0.0.1"
    DB_PORT = 3307
    DB_USER = "webadmin"
    DB_PASSWORD = "3edcVFR$"
    DB_NAME = "web-op"

    OUTPUT_FILE = BusinessStructureManager.DATA_DIR / "business_structure_map_pddy.json"

    ROOT_GROUP_IDS = {"1000000"}
    ROOT_GROUP_NAMES = {"默认目录"}

    def _fetch_all_from_db(self) -> List[Dict[str, Any]]:
        """连接数据库并还原浦东道运的相机目录结构"""
        print(f"[PDDYBusinessStructureManager] 正在连接 SSH 隧道 ({self.SSH_HOST})...")

        all_results: List[Dict[str, Any]] = []
        start_time = time.time()

        with SSHTunnelForwarder(
            (self.SSH_HOST, self.SSH_PORT),
            ssh_username=self.SSH_USER,
            ssh_password=self.SSH_PASSWORD,
            remote_bind_address=(self.DB_HOST, self.DB_PORT)
        ) as tunnel:
            print(f"[PDDYBusinessStructureManager] SSH 隧道已建立 (Port: {tunnel.local_bind_port})")

            print(f"[PDDYBusinessStructureManager] 正在连接 MySQL ({self.DB_HOST})...")
            connection = pymysql.connect(
                host="127.0.0.1",
                port=tunnel.local_bind_port,
                user=self.DB_USER,
                password=self.DB_PASSWORD,
                database=self.DB_NAME,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=20,
                charset="gbk",
            )

            try:
                with connection.cursor() as cursor:
                    print("[PDDYBusinessStructureManager] 正在拉取相机基础信息...")
                    cursor.execute(
                        """
                        SELECT ubi_share_camera_id, ubi_short_id, sz_name
                        FROM tbl_share_camera_info
                        WHERE ubi_short_id IS NOT NULL
                        """
                    )
                    cameras = cursor.fetchall()

                    print("[PDDYBusinessStructureManager] 正在拉取相机与目录关联关系...")
                    cursor.execute(
                        """
                        SELECT ubi_share_camera_id, ubi_group_id
                        FROM tbl_share_custom_group_camera
                        WHERE ubi_share_camera_id IS NOT NULL
                          AND ubi_group_id IS NOT NULL
                        """
                    )
                    camera_group_rows = cursor.fetchall()

                    print("[PDDYBusinessStructureManager] 正在拉取目录树...")
                    cursor.execute(
                        """
                        SELECT ubi_group_id, sz_name, ubi_parent_group_id
                        FROM tbl_share_custom_group
                        WHERE ubi_group_id IS NOT NULL
                        """
                    )
                    group_rows = cursor.fetchall()

                group_map: Dict[str, Dict[str, Any]] = {
                    str(row["ubi_group_id"]): row for row in group_rows if row.get("ubi_group_id") is not None
                }

                camera_group_map: Dict[str, List[str]] = {}
                for row in camera_group_rows:
                    camera_id = row.get("ubi_share_camera_id")
                    group_id = row.get("ubi_group_id")
                    if camera_id is None or group_id is None:
                        continue
                    camera_group_map.setdefault(str(camera_id), []).append(str(group_id))

                for camera in cameras:
                    short_id = camera.get("ubi_short_id")
                    share_camera_id = camera.get("ubi_share_camera_id")
                    if short_id is None or share_camera_id is None:
                        continue

                    path_parts = self._select_best_path_parts(
                        camera_group_map.get(str(share_camera_id), []),
                        group_map,
                    )
                    all_results.append(
                        {
                            "ubi_short_id": short_id,
                            "sz_name": camera.get("sz_name", ""),
                            "szTagRef1": path_parts[0],
                            "szTagRef2": path_parts[1],
                            "szTagRef3": path_parts[2],
                        }
                    )

                total_time = time.time() - start_time
                print(
                    f"[PDDYBusinessStructureManager] 数据拉取完成! 相机 {len(cameras)} 条, "
                    f"目录关系 {len(camera_group_rows)} 条, 目录节点 {len(group_rows)} 条, "
                    f"总耗时: {total_time:.2f}秒"
                )
            finally:
                connection.close()
                print("[PDDYBusinessStructureManager] 数据库连接已关闭")

        return all_results

    def _select_best_path_parts(
        self,
        group_ids: List[str],
        group_map: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """从一个相机的多个分组候选中选择最完整的一条路径"""
        best_path: List[str] = []

        for group_id in group_ids:
            path = self._build_path_from_group(group_id, group_map)
            if len(path) > len(best_path):
                best_path = path

        trimmed_path = best_path[:3]
        while len(trimmed_path) < 3:
            trimmed_path.append("")
        return trimmed_path

    def _build_path_from_group(
        self,
        group_id: str,
        group_map: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """沿父节点向上回溯，并过滤根目录等无业务意义节点"""
        path_nodes: List[str] = []
        visited = set()
        current_group_id = str(group_id)

        while current_group_id and current_group_id not in visited:
            visited.add(current_group_id)
            group = group_map.get(current_group_id)
            if not group:
                break

            group_name = (group.get("sz_name") or "").strip()
            if (
                group_name
                and current_group_id not in self.ROOT_GROUP_IDS
                and group_name not in self.ROOT_GROUP_NAMES
            ):
                path_nodes.append(group_name)

            parent_group_id = group.get("ubi_parent_group_id")
            if parent_group_id in (None, "", 0, "0"):
                break
            current_group_id = str(parent_group_id)

        path_nodes.reverse()
        return path_nodes

# 单例实例，方便其他模块直接引用
_instance = None
_pddy_instance = None

def get_business_manager():
    global _instance
    if _instance is None:
        _instance = BusinessStructureManager()
    return _instance


def get_pddy_business_manager():
    global _pddy_instance
    if _pddy_instance is None:
        _pddy_instance = PDDYBusinessStructureManager()
    return _pddy_instance


def get_business_manager_for_project(project_name: Optional[str]):
    if project_name in PDDY_PROJECT_NAMES:
        return get_pddy_business_manager()
    return get_business_manager()

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
