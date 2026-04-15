"""
从minio下载指定bucket和prefix下的所有文件到本地目录
Bucket：bucket-taglens
Prefix：project_data/视频质量诊断/2026-01-14/
本地保存：你执行命令时的当前目录下 minio/
"""


import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 1. 设置环境路径以便导入 backend 模块
# 假设脚本位于 scripts/ 目录下，项目根目录是其父目录
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
backend_dir = project_root / "backend"

# 添加 backend 目录到 sys.path，以便可以导入 minio_storage_client
sys.path.append(str(backend_dir))

# 2. 加载环境变量
# 尝试加载 backend/.env 以获取 MinIO 连接信息
env_path = backend_dir / ".env"
if env_path.exists():
    print(f"正在加载环境变量: {env_path}")
    load_dotenv(env_path)
else:
    print("警告: 未找到 backend/.env 文件，尝试使用默认环境变量")

try:
    from minio_storage_client import get_storage_client
except ImportError as e:
    print(f"错误: 无法导入 minio_storage_client。原因: {e}")
    print(f"当前的 sys.path: {sys.path}")
    sys.exit(1)

def download_folder(bucket_name, prefix, local_dir):
    """
    下载 MinIO 指定 Bucket 和 Prefix 下的所有文件到本地目录
    """
    print(f"\n🚀 开始下载任务")
    print(f"   Bucket: {bucket_name}")
    print(f"   Prefix: {prefix}")
    print(f"   本地目录: {local_dir}")
    
    # 获取 storage client 实例
    # skip_bucket_check=True 防止因为权限问题导致的检查失败
    try:
        client_wrapper = get_storage_client(skip_bucket_check=True)
    except Exception as e:
        print(f"❌ 初始化 MinIO 客户端失败: {e}")
        return

    # 临时修改 bucket (如果与默认配置不同)
    original_bucket = client_wrapper.bucket
    if original_bucket != bucket_name:
        print(f"ℹ️  切换 Bucket: {original_bucket} -> {bucket_name}")
        client_wrapper.bucket = bucket_name
    
    # 获取底层的 minio.Minio 客户端
    minio_client = client_wrapper.client
    
    print(f"📡 正在列出文件...")
    
    try:
        # recursive=True 递归列出所有对象
        objects = minio_client.list_objects(bucket_name, prefix=prefix, recursive=True)
        
        # 将迭代器转换为列表以获取数量（注意：如果文件极多可能会慢，但在脚本中通常可以接受）
        # 为了实时显示，我们直接遍历
        
        local_base_path = Path(local_dir).resolve()
        # 确保本地根目录存在
        local_base_path.mkdir(parents=True, exist_ok=True)
        
        count = 0
        success_count = 0
        fail_count = 0
        
        for obj in objects:
            if obj.is_dir:
                continue
                
            count += 1
            obj_name = obj.object_name
            
            # 计算相对路径，以便在本地保持相同的目录结构（去掉 prefix 部分）
            if obj_name.startswith(prefix):
                rel_path = obj_name[len(prefix):]
            else:
                rel_path = obj_name
                
            # 去掉开头的斜杠（如果有）
            if rel_path.startswith('/'):
                rel_path = rel_path[1:]
            
            # 如果 rel_path 为空（即正好是 prefix 目录本身），跳过
            if not rel_path:
                continue

            local_file_path = local_base_path / rel_path
            
            # 确保父目录存在
            local_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            print(f"⬇️  [{count}] 下载: {obj_name} -> {local_file_path.name}")
            try:
                minio_client.fget_object(bucket_name, obj_name, str(local_file_path))
                success_count += 1
            except Exception as e:
                print(f"    ❌ 下载失败: {e}")
                fail_count += 1
        
        if count == 0:
            print("⚠️  未找到任何匹配的文件。请检查 Bucket 名称和 Prefix 路径是否正确。")
            print(f"   (注意: Prefix 通常需要以 '/' 结尾，例如 'folder/')")
        else:
            print("\n" + "="*50)
            print(f"✅ 下载完成！")
            print(f"   总文件数: {count}")
            print(f"   成功: {success_count}")
            print(f"   失败: {fail_count}")
            print(f"   保存位置: {local_base_path}")
            print("="*50)

    except Exception as e:
        print(f"❌ 发生错误: {e}")
    finally:
        # 恢复 bucket 设置（虽然脚本要结束了，但保持良好习惯）
        client_wrapper.bucket = original_bucket

if __name__ == "__main__":
    # 测试配置
    TARGET_BUCKET = "bucket-taglens"
    TARGET_PREFIX = "project_data/视频质量诊断/2026-01-14/"
    
    # 获取当前执行命令的目录作为基准，或者直接使用脚本所在目录
    # 用户要求: "保存在当前目录的'minio'文件夹"
    # os.getcwd() 获取的是运行 python 命令时的目录
    CURRENT_WORKING_DIR = os.getcwd()
    LOCAL_SAVE_DIR = os.path.join(CURRENT_WORKING_DIR, "minio")
    
    download_folder(TARGET_BUCKET, TARGET_PREFIX, LOCAL_SAVE_DIR)
