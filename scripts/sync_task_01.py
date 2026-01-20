#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#视频质量诊断  
import time
import threading
import json

import paramiko
import time
import tarfile
import os
import sys
import shutil
import requests
from datetime import datetime
from scp import SCPClient
from io import StringIO
import sys
import requests
from sshtunnel import SSHTunnelForwarder


# 设置 NO_PROXY 环境变量，确保 localhost 请求不走代理
os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
os.environ['no_proxy'] = 'localhost,127.0.0.1'

# ==================== 配置部分 ====================
MID_SSH_HOST = "192.168.1.10"
MID_SSH_PORT = 61008

TARGET_SSH_HOST = "10.31.243.3"
TARGET_SSH_DB_PORT = 3306
TARGET_SSH_USER = "root"
TARGET_SSH_PASSWORD = "md@xinxi2022"
TARGET_DIR = "/root/CollectionIMGJudgment/upload"


TMP_DIR = "./tmp"
TMP_SECOND = "./tmpSecond"
LOG_DIR = "./log"


REMOTE_SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "QualityJudgment.sh")
PROJECT_NAME="视频质量诊断"
PROJECT_ROOT="/root/CollectionIMGJudgment"


# CAMERA_DIR_INFO   =====   ssh port forwarding ====================================
HTTP_USER="mingding"
HTTP_PW="md@luwang0"

FORWARD_SSH_IP="192.168.1.10"
FORWARD_SSH_PORT=9008
FORWARD_SSH_USER="root"
FORWARD_SSH_PD="md@xinxi2022"

FORWARD_TARGET_IP="10.31.153.128"
FORWARD_TARGET_PORT=1200


cameras = []
group_mapping = {}
forward_count = 0

def http_post(url, req_type):
    """统一发送 HTTP 请求"""
    payload = {
        "req_type": req_type,
        "req_header": {
            "guid": "C12A7328-F81F-11D2-BA4B-00A0C93EC93B",
            "user": HTTP_USER,
            "pwd": HTTP_PW
        }
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json()


def build_group_path(group_id, group_mapping):
    """根据 group_id 递归向上查找完整路径"""
    path = []
    while group_id in group_mapping:
        group = group_mapping[group_id]
        path.append(group["group_name"])
        group_id = group["parent_group_id"]
    return list(reversed(path))


def get_camera_path(camera_id):
    global forward_count
    global cameras
    global group_mapping
    if forward_count % 100 == 0:
        forward_count += 1

        with SSHTunnelForwarder(
            (FORWARD_SSH_IP, FORWARD_SSH_PORT),
            ssh_username=FORWARD_SSH_USER,
            ssh_password=FORWARD_SSH_PD,  # 或使用 ssh_pkey="/path/to/private/key"
            remote_bind_address=(FORWARD_TARGET_IP, FORWARD_TARGET_PORT),
            local_bind_address=('127.0.0.1', 28749)  # 本地绑定端口
        ) as tunnel:

            # 通过隧道访问
            camera_url = f"http://127.0.0.1:{tunnel.local_bind_port}/protocol/proxy/request"
            group_url = f"http://127.0.0.1:{tunnel.local_bind_port}/protocol/proxy/request"

            # 1) 获取相机列表
            camera_resp = http_post(camera_url, "get_camera_request")
            cameras = camera_resp["ret_body"]["camera_list"]

            # 2) 获取相机组列表
            group_resp = http_post(group_url, "get_camera_group_request")
            groups = group_resp["ret_body"]["camera_group_list"]

            # 3) 创建 group_id → group 信息映射
            group_mapping = {g["group_id"]: g for g in groups}


    """根据 camera_id 返回完整目录路径"""
    cam = next((c for c in cameras if c["id"] == camera_id), None)
    if cam is None:
        return "NULL"

    group_path = build_group_path(cam["group_id"], group_mapping)
    full_path = "/" + "/".join(group_path + [cam["name"]])
    return full_path


# =================== CV ==============================
# =================== CV ==============================
# TraditionalImageSimilarity class removed for aabbcc.py



# ==================== SSH 连接函数 ====================
def create_ssh_client(host, port, user, password):
    """创建 SSH 客户端连接"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port, user, password)
    return client



def list_remote_files(ssh_client, directory):
    """列出远程目录中的文件"""
    try:
        # 检查目录是否存在
        stdin, stdout, stderr = ssh_client.exec_command(f"test -d {directory} && echo 'exists' || echo 'not_exists'")
        result = stdout.read().decode().strip()
        if result != 'exists':
            print(f"⚠️ 远程目录不存在: {directory}")
            return []
        
        # 列出文件
        stdin, stdout, stderr = ssh_client.exec_command(f"ls {directory}")
        error = stderr.read().decode().strip()
        if error:
            print(f"⚠️ 列出文件时出错: {error}")
        
        files = stdout.read().decode().strip().split('\n')
        files = [f for f in files if f and not f.startswith('ls:')]  # 过滤错误信息
        
        print(f"📁 远程目录 {directory} 中找到 {len(files)} 个文件")
        return files
    except Exception as e:
        print(f"❌ 列出远程文件失败: {e}")
        return []


def download_file(ssh_client, remote_path, local_path):
    """下载远程文件"""
    try:
        # 先检查远程文件是否存在
        stdin, stdout, stderr = ssh_client.exec_command(f"test -f {remote_path} && echo 'exists' || echo 'not_exists'")
        result = stdout.read().decode().strip()
        if result != 'exists':
            raise FileNotFoundError(f"远程文件不存在: {remote_path}")
        
        # 获取远程文件大小
        stdin, stdout, stderr = ssh_client.exec_command(f"stat -c%s {remote_path}")
        remote_size = int(stdout.read().decode().strip())
        print(f"📥 远程文件大小: {remote_size / (1024*1024):.2f} MB")
        
        # 下载文件
        print(f"📥 开始下载: {remote_path} -> {local_path}")
        with SCPClient(ssh_client.get_transport()) as scp:
            scp.get(remote_path, local_path)
        
        # 验证下载的文件大小
        if os.path.exists(local_path):
            local_size = os.path.getsize(local_path)
            if local_size != remote_size:
                raise ValueError(f"文件大小不匹配: 远程={remote_size} 字节, 本地={local_size} 字节")
            print(f"✅ 下载完成: {local_path} ({local_size / (1024*1024):.2f} MB)")
        else:
            raise FileNotFoundError(f"下载后本地文件不存在: {local_path}")
            
    except FileNotFoundError as e:
        print(f"❌ 文件不存在错误: {e}")
        raise
    except Exception as e:
        print(f"❌ 下载失败: {remote_path} -> {local_path}, 错误: {e}")
        import traceback
        traceback.print_exc()
        raise


def delete_remote_file(ssh_client, remote_path):
    """删除远程文件"""
    ssh_client.exec_command(f"rm -f {remote_path}")


# ==================== 数据处理函数 ====================
def convert_vehicle_color(color_value):
    """将车辆颜色中文名称转换为编号"""
    color_value = (color_value or "").strip()
    if color_value in vehicle_color_map:
        return vehicle_color_map[color_value]
    print(f"⚠️ 未识别的车辆颜色: {color_value}，默认设为 12（未知）")
    return 12

# upload_file_to_minio removed


def normalize_null(x):
    return None if x == "NULL" else x


# process_json_and_insert_db removed


def process_archive(archive_file):

    try:

        """处理下载的归档文件"""
        shutil.rmtree(TMP_DIR, ignore_errors=True)
        shutil.rmtree(TMP_SECOND, ignore_errors=True)
        os.makedirs(TMP_DIR, exist_ok=True)
        os.makedirs(TMP_SECOND, exist_ok=True)
    
        print(f">>> 解压主文件: {archive_file} 到 {TMP_DIR}")
    
        # 获取文件大小（MB）
        file_size_mb = os.path.getsize(archive_file) / (1024 * 1024)
    
        # 解压主文件
        with tarfile.open(archive_file, 'r:gz') as tar:
            tar.extractall(TMP_DIR)
            file_count = len(tar.getnames())
    
        # 记录日志
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(f"{LOG_DIR}/pull.log", "a") as log:
            log.write(f"{datetime.now()} pull tar, file size {file_size_mb:.2f} MB, "
                      f"------- {file_count} inner files\n")
   
        try:
            # 处理子归档文件
            for file in os.listdir(TMP_DIR):
                if not file.endswith('.tar.gz'):
                    continue
        
                file_path = os.path.join(TMP_DIR, file)
                print(f">>> 处理子包: {file_path}")
        
                # 清空 tmpSecond
                shutil.rmtree(TMP_SECOND, ignore_errors=True)
                os.makedirs(TMP_SECOND, exist_ok=True)
        
                # 解压子包
                with tarfile.open(file_path, 'r:gz') as tar:
                    tar.extractall(TMP_SECOND)
        
                # 准备上传
                time_path = datetime.now().strftime("%Y/%m/%d/%H/%M")
                timestamp_ms = int(datetime.now().timestamp() * 1000)
        
                json_urls = ""
                jpeg_urls = ""
                img_hash = 0
                camera_id = None
                
                # 寻找 JSON 文件并提取相机编号
                try:
                    for subfile in os.listdir(TMP_SECOND):
                        # two_2012416954331881475.json
                        if subfile.endswith('.json') and subfile.startswith('two_'):
                            json_path = os.path.join(TMP_SECOND, subfile)
                            with open(json_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                camera_id = data.get("相机短编号")
                                if camera_id:
                                    print(f">>> 提取到相机短编号: {camera_id}")
                            break
                except Exception as e:
                    print(f"⚠️ 提取相机编号失败: {e}")

        
                # 上传文件并调用后端接口处理
                for subfile in os.listdir(TMP_SECOND):
                    subfile_path = os.path.join(TMP_SECOND, subfile)
            
                    if subfile.endswith('.jpg'):
                        print(f">>> 正在处理图片: {subfile} ...")
                        # 创建 Session，localhost 不走代理，外部 API 继续使用代理
                        session = requests.Session()
                        session.proxies = {
                            'http': None,   # localhost 不使用代理
                            'https': None
                        }
                        
                        try:
                            # 准备请求数据
                            with open(subfile_path, 'rb') as img_file:
                                files = {'file': (subfile, img_file, 'image/jpeg')}
                                data = {
                                    'project_name': PROJECT_NAME,
                                    'threshold': 0.74,
                                    'camera_id': camera_id
                                }
                                
                                # 调用后端接口
                                response = session.post(
                                    "http://localhost:8000/upload-image-for-processing",
                                    files=files,
                                    data=data,
                                    timeout=300 # 5分钟超时，等待AI分析
                                )
                                
                                if response.status_code == 200:
                                    res_json = response.json()
                                    status = res_json.get("status")
                                    if status == "success":
                                        if res_json.get("ai_error"):
                                             print(f"    ⚠️ 处理成功(无标签): {subfile} (UUID: {res_json.get('uuid')}) - AI 提取失败: {res_json.get('ai_error')}")
                                        elif res_json.get("ai_skipped"):
                                             print(f"    ⚠️ 处理成功(无标签): {subfile} (UUID: {res_json.get('uuid')}) - AI 分析被跳过")
                                        else:
                                             print(f"    ✅ 处理成功: {subfile} (UUID: {res_json.get('uuid')})")
                                    elif status == "skipped":
                                        print(f"    ⏭️ 跳过重复: {subfile} ({res_json.get('message')})")
                                    else:
                                        print(f"    ❌ 处理失败: {subfile} - {res_json.get('message')}")
                                else:
                                    print(f"    ❌ 请求失败: Status {response.status_code} - {response.text}")
                                    
                        except requests.exceptions.ConnectionError as e:
                            print(f"    ❌ [CRITICAL] 无法连接到后端服务 (Connection Refused)。后端可能已崩溃或正在重启。")
                            print(f"    详细错误: {e}")
                            sys.exit(0)
                        except requests.exceptions.Timeout:
                            print(f"    ❌ 请求超时 (300s)。后端处理时间过长。")
                        except Exception as e:
                            print(f"    ❌ 调用接口发生未预期的异常: {type(e).__name__}: {e}")
                            # 如果是其他严重错误也可以考虑退出，但暂时只针对连接错误退出
                        finally:
                            # 无论成功失败，都删除本地文件
                            if os.path.exists(subfile_path):
                                try:
                                    os.remove(subfile_path)
                                    print(f"       [Cleanup] 已删除本地文件: {subfile}")
                                except Exception as del_e:
                                    print(f"       [Cleanup] 删除文件失败: {del_e}")
                
                    elif subfile.startswith('two') and subfile.lower().endswith('.json'):
                        # 仍然保留对 JSON 的简单处理（如获取相机路径），但不再单独上传
                        # 如果需要将相机信息传给后端，可以在这里解析后存到一个字典里，供上面 jpg 循环使用
                        # (由于循环顺序不确定，理想做法是先遍历一次搜集信息，再遍历上传)
                        pass

        
        except Exception as e:
            print(f"处理单个数据失败: {e}")        

        # 清理
        shutil.rmtree(TMP_SECOND, ignore_errors=True)
        os.remove(os.path.abspath(file_path))
        print(f">>> 删除子压缩包: {file_path}")
    
    except Exception as e:
        print("出错：", e)


    shutil.rmtree(TMP_DIR, ignore_errors=True) 
    print(">>> 所有上传任务完成 ✅")
    os.remove(os.path.abspath(archive_file))


def create_ssh_connection():
    """创建 SSH 连接"""
    print("🔗 正在连接目标服务器...")
    
    # 直接连接目标服务器
    target_client = paramiko.SSHClient()
    target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target_client.connect(
        hostname=MID_SSH_HOST,
        port=MID_SSH_PORT,
        username=TARGET_SSH_USER,
        password=TARGET_SSH_PASSWORD
    )
    print(f"✅ 已连接目标服务器: {MID_SSH_HOST}:{MID_SSH_PORT}")
    
    return target_client



def execute_command(client, command, print_output=True):
    """执行命令并返回输出"""
    stdin, stdout, stderr = client.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    
    output = stdout.read().decode('utf-8')
    error = stderr.read().decode('utf-8')
    
    if print_output:
        if output:
            print(output)
        if error:
            print(f"⚠️ 错误输出: {error}")
    
    return exit_status, output, error


def create_directories(client):
    """在目标服务器创建所需目录"""
    print(f"\n📁 创建目录结构...")
  

    # 执行两次
    execute_command(client, f"pkill -9 -f {REMOTE_SH}", print_output=False)
    time.sleep(3)
    execute_command(client, f"pkill -9 -f {REMOTE_SH}", print_output=False)
    time.sleep(3)

    directories = [
        PROJECT_ROOT,
        f"{PROJECT_ROOT}/tmp",
        f"{PROJECT_ROOT}/upload"
    ]
    
    for directory in directories:
        print(f"      删除旧目录及内容...")
        execute_command(client, f"rm -rf {directory}", print_output=False)
        print(f"   创建目录: {directory}")
        execute_command(client, f"mkdir -p {directory}", print_output=False)
    
    print("✅ 目录创建完成")


def upload_script(client, local_script_path):
    """上传脚本文件到目标服务器"""
    print(f"\n📤 上传脚本文件...")
    
    if not os.path.exists(local_script_path):
        print(f"❌ 本地文件不存在: {local_script_path}")
        return False
    
    remote_script_path = f"{PROJECT_ROOT}/{os.path.basename(local_script_path)}"
    
    try:
        with SCPClient(client.get_transport()) as scp:
            scp.put(local_script_path, remote_script_path)
        
        print(f"✅ 文件已上传: {local_script_path} -> {remote_script_path}")
        
        # 添加执行权限
        print(f"🔧 添加执行权限...")
        execute_command(client, f"chmod +x {remote_script_path}", print_output=False)
        print("✅ 执行权限已添加")
        
        return remote_script_path
    
    except Exception as e:
        print(f"❌ 上传失败: {e}")
        return None


def execute_remote_script(client, remote_script_path):
    """在目标服务器执行脚本"""
    print(f"\n🚀 执行远程脚本...")
    
    script_name = os.path.basename(remote_script_path)
    
    # 构建执行命令
    command = f"LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 cd {PROJECT_ROOT} && ./{script_name} '{PROJECT_NAME}' {TARGET_SSH_HOST} {TARGET_SSH_DB_PORT}"
    
    print(f"📝 执行命令: {command}")
    print("=" * 80)
    
    # 执行命令（使用 nohup 后台运行）
    # 如果需要后台执行，使用下面这行
    # command = f"cd {PROJECT_ROOT} && nohup ./{script_name} '{PROJECT_NAME}' {TARGET_SSH_HOST} {PROJECT_PORT} > output.log 2>&1 &"
    
    exit_status, output, error = execute_command(client, command)
    
    print("=" * 80)
    
    if exit_status == 0:
        print("✅ 脚本执行成功")
    else:
        print(f"⚠️ 脚本执行完成，退出状态码: {exit_status}")
    
    return exit_status



def remote():
    print("🎯 开始部署和执行脚本\n")
    print(f"目标服务器: {TARGET_SSH_HOST}:{TARGET_SSH_DB_PORT}")
    print(f"项目名称: {PROJECT_NAME}")
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"本地脚本: {REMOTE_SH}")
    print("=" * 80)
    
    target_client = None
   
    while True:
        print("-----------000000000000--------------------")
        try:
            # 1. 建立 SSH 连接
            target_client = create_ssh_connection()
        
            # 2. 创建目录
            create_directories(target_client)
        
            # 3. 上传脚本
            remote_script_path = upload_script(target_client, REMOTE_SH)
        
            if not remote_script_path:
                print("❌ 上传失败，终止执行")
                continue
        
            # 4. 执行脚本
            exit_status = execute_remote_script(target_client, remote_script_path)

            print("\n" + "=" * 80)
            print("🎉 所有操作完成！")
        
            continue
    
        except Exception as e:
            print(f"\n❌ 发生错误: {e}")
            import traceback
            traceback.print_exc()
    
        finally:
            # 关闭连接
            if target_client:
                target_client.close()
                print("🔌 已关闭目标服务器连接")

        time.sleep(600)


def delete_tar_gz_in_cwd():
    cwd = os.getcwd()
    for file in os.listdir(cwd):
        if file.endswith(".tar.gz"):
            file_path = os.path.join(cwd, file)
            print("删除文件:", file_path)
            os.remove(file_path)

# 2. 删除目录及其所有内容
def delete_directory(path):
    if os.path.exists(path):
        print("删除目录:", path)
        shutil.rmtree(path)   # 递归删除整个目录
    else:
        print("目录不存在:", path)


# ==================== 主循环 ====================
def main():
    """主函数"""
    thread = threading.Thread(target=remote)
    thread.start()

    print("🚀 启动数据采集和处理服务...")
    
    while True:
        try:
            time.sleep(100)
            print("one loop -----------")
            
            # 直接连接目标服务器
            target_client = create_ssh_client(
                MID_SSH_HOST, MID_SSH_PORT, TARGET_SSH_USER, TARGET_SSH_PASSWORD
            )
            
            # 列出远程文件
            files = list_remote_files(target_client, TARGET_DIR)
            
            if len(files) < 2:
                print("文件数量不足，跳过本次循环")
                target_client.close()
                continue
            
            # 找到字典序最小的文件
            min_file = sorted(files)[0]
            print(f"min line (lexicographic): {min_file}")
            
            # 下载文件
            remote_path = f"{TARGET_DIR}/{min_file}"
            local_path = f"./{min_file}"
            
            print(f"\n📥 准备下载文件:")
            print(f"   远程路径: {remote_path}")
            print(f"   本地路径: {local_path}")
            
            try:
                download_file(target_client, remote_path, local_path)
                print("✅ 下载成功")
            except Exception as e:
                print(f"❌ 下载失败: {e}")
                target_client.close()
                continue
            
            # 删除远程文件
            delete_remote_file(target_client, remote_path)
            
            # 关闭连接
            target_client.close()
            
            # 处理下载的文件
            process_archive(local_path)
            
        except Exception as e:
            print(f"❌ 发生错误: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)

        delete_tar_gz_in_cwd()     # 删除当前目录下的 tar.gz 文件
        delete_directory(TMP_DIR)  # 删除 ./tmp
        delete_directory(TMP_SECOND)
        

    thread.join() 

if __name__ == "__main__":
    main()
