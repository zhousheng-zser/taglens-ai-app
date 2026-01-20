# -*- coding: utf-8 -*-
"""
批量导入任务存储模块 - 使用JSON文件存储任务信息
"""
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from threading import Lock

# JSON文件路径
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "bulk_import"
ALL_JOBS_STATUS_FILE = DATA_DIR / "all_jobs_status.json"

# 文件锁，确保线程安全
_file_lock = Lock()


def ensure_data_dir():
    """确保数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json_file(file_path: Path, default: Any = None) -> Any:
    """加载JSON文件"""
    if default is None:
        default = []
    if not file_path.exists():
        return default
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def _save_json_file(file_path: Path, data: Any):
    """保存JSON文件"""
    ensure_data_dir()
    with _file_lock:
        # 先写入临时文件，然后重命名，确保原子性
        temp_file = file_path.with_suffix('.tmp')
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 使用 os.replace 确保原子性（Python 3.3+）
        import shutil
        shutil.move(str(temp_file), str(file_path))


def _get_next_job_id() -> int:
    """获取下一个任务ID"""
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    if not all_jobs:
        return 1
    max_id = max((job.get('id', 0) for job in all_jobs.values()), default=0)
    return max_id + 1


def get_job_dir(job_id: int, job_name: Optional[str] = None) -> Path:
    """获取任务文件夹路径（使用任务名）"""
    if job_name:
        # 使用任务名作为文件夹名，确保没有特殊字符
        safe_name = job_name.replace(' ', '_').replace('/', '_').replace('\\', '_').replace(':', '_')
        return DATA_DIR / safe_name
    # 如果没有提供任务名，尝试从任务对象中获取
    job = get_bulk_import_job(job_id)
    if job and job.get('name'):
        safe_name = job['name'].replace(' ', '_').replace('/', '_').replace('\\', '_').replace(':', '_')
        return DATA_DIR / safe_name
    # 如果获取不到任务名，使用job_id作为后备方案
    return DATA_DIR / f"job_{job_id}"


def create_bulk_import_job(threshold: float, directory: str) -> Dict[str, Any]:
    """创建新的批量导入任务"""
    job_id = _get_next_job_id()
    now = datetime.now()
    now_iso = now.isoformat()
    # 使用当前时间作为任务名称，格式：YYYY-MM-DD_HH:MM（精确到分钟，使用下划线代替空格）
    job_name = now.strftime('%Y-%m-%d_%H:%M')
    
    job = {
        'id': job_id,
        'name': job_name,
        'status': 'pending',
        'total_files': 0,
        'processed': 0,
        'succeeded': 0,
        'skipped_similar': 0,
        'failed': 0,
        'current_file': None,
        'last_error': None,
        'threshold': threshold,
        'directory': directory,
        'created_at': now_iso,
        'updated_at': now_iso
    }
    
    # 创建任务文件夹（使用任务名）
    job_dir = get_job_dir(job_id, job_name=job_name)
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # 添加到all_jobs_status.json
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    all_jobs[str(job_id)] = job
    _save_json_file(ALL_JOBS_STATUS_FILE, all_jobs)
    
    return job


def get_bulk_import_job(job_id: int) -> Optional[Dict[str, Any]]:
    """获取任务信息"""
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    return all_jobs.get(str(job_id))


def update_bulk_import_job_status(
    job_id: int,
    status: str,
    current_file: Optional[str] = None,
    last_error: Optional[str] = None
):
    """更新任务状态"""
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    job = all_jobs.get(str(job_id))
    if not job:
        return
    
    job['status'] = status
    job['updated_at'] = datetime.now().isoformat()
    if current_file is not None:
        job['current_file'] = current_file
    if last_error is not None:
        job['last_error'] = last_error
    
    # 更新all_jobs_status.json
    all_jobs[str(job_id)] = job
    _save_json_file(ALL_JOBS_STATUS_FILE, all_jobs)


def update_bulk_import_total(job_id: int, total_files: int):
    """更新任务总文件数"""
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    job = all_jobs.get(str(job_id))
    if not job:
        return
    
    job['total_files'] = total_files
    job['updated_at'] = datetime.now().isoformat()
    all_jobs[str(job_id)] = job
    _save_json_file(ALL_JOBS_STATUS_FILE, all_jobs)


def update_bulk_import_progress(
    job_id: int,
    processed: int = 0,
    succeeded: int = 0,
    skipped_similar: int = 0,
    failed: int = 0,
    current_file: Optional[str] = None
):
    """更新任务进度"""
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    job = all_jobs.get(str(job_id))
    if not job:
        return
    
    job['processed'] = job.get('processed', 0) + processed
    job['succeeded'] = job.get('succeeded', 0) + succeeded
    job['skipped_similar'] = job.get('skipped_similar', 0) + skipped_similar
    job['failed'] = job.get('failed', 0) + failed
    job['updated_at'] = datetime.now().isoformat()
    if current_file is not None:
        job['current_file'] = current_file
    
    all_jobs[str(job_id)] = job
    _save_json_file(ALL_JOBS_STATUS_FILE, all_jobs)


def log_bulk_import(
    job_id: int,
    file_name: str,
    status: str,
    similarity: Optional[float],
    message: str,
    ai_json_data: Optional[Dict[str, Any]] = None
):
    """记录导入日志（日志保存在任务文件夹中）"""
    job = get_bulk_import_job(job_id)
    if not job:
        return
    
    # 获取任务文件夹
    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # 构建日志文件路径（使用文件名，但将特殊字符替换为安全字符）
    safe_file_name = file_name.replace('/', '_').replace('\\', '_').replace(':', '_')
    log_file = job_dir / f"{safe_file_name}.json"
    
    # 构建日志条目
    log_entry = {
        'file_name': file_name,
        'status': status,
        'similarity': float(similarity) if similarity is not None else None,
        'message': message,
        'created_at': datetime.now().isoformat()
    }
    
    # 如果提供了AI生成的JSON数据，添加到日志中
    if ai_json_data:
        log_entry['ai_analysis'] = ai_json_data
    
    # 保存日志到文件
    with _file_lock:
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_entry, f, ensure_ascii=False, indent=2)
    
    # 更新任务的updated_at时间
    job['updated_at'] = datetime.now().isoformat()
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    all_jobs[str(job_id)] = job
    _save_json_file(ALL_JOBS_STATUS_FILE, all_jobs)


def get_bulk_import_logs(
    job_id: int,
    page: int = 0,
    page_size: int = 50,
    status_filter: Optional[str] = None
) -> tuple[List[Dict[str, Any]], int]:
    """获取任务日志（从任务文件夹中读取，分页，按时间倒序，最新的在前）"""
    job = get_bulk_import_job(job_id)
    if not job:
        return [], 0
    
    # 获取任务文件夹
    job_dir = get_job_dir(job_id)
    if not job_dir.exists():
        return [], 0
    
    # 读取所有日志文件
    logs = []
    for log_file in job_dir.glob("*.json"):
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                log_entry = json.load(f)
                logs.append(log_entry)
        except (json.JSONDecodeError, IOError):
            continue
    
    # 状态筛选
    if status_filter and status_filter != 'all':
        logs = [log for log in logs if log.get('status') == status_filter]
    
    # 按创建时间倒序排序（最新的在前）
    logs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    total = len(logs)
    
    # 分页
    start_idx = page * page_size
    end_idx = start_idx + page_size
    paginated_logs = logs[start_idx:end_idx]
    
    return paginated_logs, total


def get_bulk_import_processed_files(job_id: int) -> set:
    """获取已处理文件列表（用于断点续传，从任务文件夹中读取）"""
    job = get_bulk_import_job(job_id)
    if not job:
        return set()
    
    # 获取任务文件夹
    job_dir = get_job_dir(job_id)
    if not job_dir.exists():
        return set()
    
    # 从日志文件中提取已处理的文件
    processed = set()
    for log_file in job_dir.glob("*.json"):
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                log_entry = json.load(f)
                if log_entry.get('status') in ('success', 'skipped_similar', 'fail'):
                    processed.add(log_entry.get('file_name'))
        except (json.JSONDecodeError, IOError):
            continue
    
    return processed


def get_active_bulk_import_job() -> Optional[Dict[str, Any]]:
    """获取当前活跃的任务（running或pending状态）"""
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    for job in all_jobs.values():
        if job.get('status') in ('running', 'pending'):
            return job
    return None


def get_all_active_bulk_import_jobs() -> List[Dict[str, Any]]:
    """获取所有活跃的任务"""
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    return [job for job in all_jobs.values() if job.get('status') in ('running', 'pending', 'paused')]


def get_all_bulk_import_jobs() -> List[Dict[str, Any]]:
    """获取所有任务（按创建时间倒序）"""
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    jobs_list = list(all_jobs.values())
    # 按创建时间倒序排序
    jobs_list.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return jobs_list


def delete_bulk_import_job_and_logs(job_id: int):
    """删除任务及其日志文件夹"""
    all_jobs = _load_json_file(ALL_JOBS_STATUS_FILE, {})
    if str(job_id) not in all_jobs:
        return
    
    # 删除任务文件夹
    job_dir = get_job_dir(job_id)
    if job_dir.exists():
        import shutil
        try:
            shutil.rmtree(job_dir)
        except Exception as e:
            print(f"删除任务文件夹失败: {e}")
    
    # 从all_jobs_status.json中删除
    del all_jobs[str(job_id)]
    _save_json_file(ALL_JOBS_STATUS_FILE, all_jobs)
