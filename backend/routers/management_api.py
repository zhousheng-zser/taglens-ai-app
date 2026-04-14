from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging
from pathlib import Path
import os
import asyncio
import json
import time
import requests
import subprocess
import sys
from datetime import datetime

from core.minio_storage_client import get_storage_client
from services.faiss_index_manager import get_faiss_index_manager
from core.database import (
    delete_image_by_uuid,
    get_images_by_path_prefix,
    get_all_image_uuids,
    get_image_by_uuid,
)

router = APIRouter(prefix="/api/management", tags=["management"])
logger = logging.getLogger(__name__)

# 缺失标签补齐任务的全局状态与日志文件
REEXTRACT_LOG_PATH = Path(__file__).parent.parent.parent / "data" / "reextract_missing_tags_gemini.log"
CURRENT_REEXTRACT_TASK: Dict[str, Any] = {
    "running": False,     # 当前是否有脚本进程在运行（由 /status 实时计算）
    "model": None,
    "limit": None,
    "started_at": None,
    "pid": None,          # 子进程 PID，用于在 /status 中判断是否仍在运行
}

class PathRequest(BaseModel):
    path: str

def format_log(message: str, type: str = "info"):
    return json.dumps({"message": message, "type": type}, ensure_ascii=False) + "\n"

def _sync_all_to_minio_gen():
    """Generator for syncing steps"""
    try:
        yield format_log(">> 系统: 正在上传 Faiss 索引...", "system")
        get_faiss_index_manager()._upload_to_minio()
        yield format_log(">> 系统: Faiss 索引同步完成", "success")
    except Exception as e:
        yield format_log(f"同步失败: {e}", "error")

async def delete_path_generator(prefix: str):
    yield format_log(f"任务启动: 目标前缀 '{prefix}'", "start")
    await asyncio.sleep(0.01) # Force flush
    
    try:
        yield format_log("正在初始化 MinIO 客户端...", "system")
        minio_client = get_storage_client(skip_bucket_check=True)
        yield format_log("MinIO 客户端连接成功", "success")
        await asyncio.sleep(0.01)

        yield format_log("正在加载 Faiss 索引管理器...", "system")
        faiss_manager = get_faiss_index_manager()
        yield format_log("Faiss 管理器加载成功", "success")
        await asyncio.sleep(0.01)
        
        
        # 1. Delete from DB and Faiss
        yield format_log("正在查询关联数据库记录 (可能需要几秒钟)...", "info")
        await asyncio.sleep(0.01) # Force Flush
        
        db_images = get_images_by_path_prefix(prefix)
        total_db = len(db_images)
        yield format_log(f"数据库查询完毕: 发现 {total_db} 条相关记录", "info" if total_db > 0 else "warning")
        
        deleted_db_count = 0
        for i, img in enumerate(db_images):
            uuid = img['uuid']
            rel_path = img.get('relative_path', '未知路径')
            yield format_log(f"处理记录 [{i+1}/{total_db}]: {rel_path}", "info")
            
            try:
                delete_image_by_uuid(uuid)
                yield format_log(f"  -> SQLite 删除: 成功", "success")
            except Exception as e:
                yield format_log(f"  -> SQLite 删除: 失败 ({e})", "error")
                
            try:
                faiss_manager.remove_vector(uuid)
                yield format_log(f"  -> Faiss 移除: 成功", "success")
            except Exception as e:
                yield format_log(f"  -> Faiss 移除: 失败 ({e})", "error")
            
            deleted_db_count += 1
            await asyncio.sleep(0.01) # Yield often

        if deleted_db_count > 0:
            yield format_log(f"第一阶段完成: 清理 {deleted_db_count} 条 DB/Faiss 记录", "success")
        else:
            yield format_log("第一阶段跳过: 无 DB 记录", "info")

        # 2. Delete from MinIO
        yield format_log("正在扫描 MinIO 物理文件列表...", "system")
        try:
            objects = list(minio_client.client.list_objects(minio_client.bucket, prefix=prefix, recursive=True))
            total_obj = len(objects)
            yield format_log(f"MinIO 扫描完毕: 发现 {total_obj} 个对象", "info" if total_obj > 0 else "warning")
            await asyncio.sleep(0.01)
            
            deleted_minio_count = 0
            for i, obj in enumerate(objects):
                yield format_log(f"正在删除文件 [{i+1}/{total_obj}]: {obj.object_name}", "info")
                try:
                    minio_client.delete_file(obj.object_name)
                    yield format_log(f"  -> MinIO 删除: 成功", "success")
                except Exception as e:
                    yield format_log(f"  -> MinIO 删除: 失败 ({e})", "error")
                    
                deleted_minio_count += 1
                await asyncio.sleep(0.01)
                    
            yield format_log(f"第二阶段完成: 共删除 {deleted_minio_count} 个 MinIO 文件", "success")
            
        except Exception as e:
            yield format_log(f"MinIO 操作发生严重错误: {e}", "error")

        # 3. Sync
        for log in _sync_all_to_minio_gen():
            yield log
            await asyncio.sleep(0.01)
            
        yield format_log("所有任务执行完毕", "done")

    except Exception as exc:
        yield format_log(f"任务异常崩溃: {exc}", "error")
        logger.error(f"Task Failed: {exc}")


@router.post("/delete-path")
async def delete_path_endpoint(req: PathRequest):
    return StreamingResponse(delete_path_generator(req.path), media_type="application/x-ndjson")


async def check_pairs_generator(prefix: str):
    yield format_log(f"任务启动: 配对一致性检查 (前缀: {prefix})", "start")
    await asyncio.sleep(0.01)
    
    try:
        minio_client = get_storage_client(skip_bucket_check=True)
        yield format_log("MinIO 客户端连接成功", "success")
        
        yield format_log("正在获取 MinIO 文件列表...", "system")
        objects = list(minio_client.client.list_objects(minio_client.bucket, prefix=prefix, recursive=True))
        yield format_log(f"列表获取完成: {len(objects)} 个对象", "info")
        await asyncio.sleep(0.01)
        
        groups = {}
        for obj in objects:
            if obj.is_dir: continue
            name = obj.object_name
            p = Path(name)
            stem = str(p.parent / p.stem)
            if stem not in groups:
                groups[stem] = []
            groups[stem].append(name)
        
        yield format_log(f"文件分组完成: 共 {len(groups)} 组", "info")
            
        deleted_count = 0
        processed = 0
        total_groups = len(groups)
        
        for stem, files in groups.items():
            processed += 1
            has_jpg = any(f.lower().endswith(('.jpg', '.jpeg', '.png')) for f in files)
            has_json = any(f.lower().endswith('.json') for f in files)
            
            status = "完整" if (has_jpg and has_json) else "缺失"
            if status == "缺失":
                yield format_log(f"分析组 [{processed}/{total_groups}] {stem}: 发现孤立 (JPG:{has_jpg}, JSON:{has_json})", "warning")
                
                for f in files:
                    yield format_log(f"  -> 清理孤立文件: {f}", "info")
                    minio_client.delete_file(f)
                    
                    # Try DB cleanup
                    img_rows = get_images_by_path_prefix(f)
                    for row in img_rows:
                        if row['relative_path'] == f:
                            delete_image_by_uuid(row['uuid'])
                            get_faiss_index_manager().remove_vector(row['uuid'])
                            yield format_log(f"  -> 关联数据库清理: 成功", "success")
                            
                    deleted_count += 1
                    await asyncio.sleep(0.01)
            else:
                # Log only every 50 for good files to avoid spam, or verbose if requested? 
                # User asked for "more logs". Let's log every 10 for success.
                if processed % 10 == 0:
                   yield format_log(f"分析组 [{processed}/{total_groups}] {stem}:验证通过", "success")
                   await asyncio.sleep(0.01)

        yield format_log(f"检查完成，共清理 {deleted_count} 个孤立文件", "success")
        
        for log in _sync_all_to_minio_gen():
            yield log
            await asyncio.sleep(0.01)
            
        yield format_log("任务全部完成", "done")
        
    except Exception as e:
        yield format_log(f"检查出错: {e}", "error")

@router.post("/check-pairs")
async def check_pairs_endpoint(req: PathRequest):
    return StreamingResponse(check_pairs_generator(req.path), media_type="application/x-ndjson")


async def check_db_existence_generator(prefix: str):
    yield format_log(f"任务启动: 数据库物理文件存在性校验 (前缀: {prefix})", "start")
    await asyncio.sleep(0.01)
    
    try:
        minio_client = get_storage_client(skip_bucket_check=True)
        faiss_manager = get_faiss_index_manager()
        yield format_log("MinIO/Faiss 客户端初始化成功", "success")
        
        yield format_log("正在查询数据库记录...", "system")
        db_images = get_images_by_path_prefix(prefix)
        total = len(db_images)
        yield format_log(f"数据库记录: {total} 条", "info")
        await asyncio.sleep(0.01)
        
        deleted_count = 0
        for i, img in enumerate(db_images):
            path = img['relative_path']
            
            # Check exist
            exists = minio_client.file_exists(path)
            
            if not exists:
                yield format_log(f"!!! 发现无效记录 [{i+1}/{total}]: {path} 在 MinIO 中不存在", "warning")
                delete_image_by_uuid(img['uuid'])
                faiss_manager.remove_vector(img['uuid'])
                yield format_log(f"  -> 数据库/向量记录已清理", "success")
                deleted_count += 1
            else:
                if i % 10 == 0: # Log verbose progress
                     yield format_log(f"记录校验通过 [{i+1}/{total}]: {path}", "success")
            
            await asyncio.sleep(0.01)

        yield format_log(f"校验完成，共清理 {deleted_count} 条无效记录", "success")
        
        for log in _sync_all_to_minio_gen():
            yield log
            await asyncio.sleep(0.01)
            
        yield format_log("任务全部完成", "done")
        
    except Exception as e:
        yield format_log(f"校验出错: {e}", "error")

@router.post("/check-db-existence")
async def check_db_existence_endpoint(req: PathRequest):
    return StreamingResponse(check_db_existence_generator(req.path), media_type="application/x-ndjson")


async def check_features_generator():
    yield format_log("任务启动: 全库特征向量审计", "start")
    await asyncio.sleep(0.01)
    
    try:
        faiss_manager = get_faiss_index_manager()
        minio_client = get_storage_client(skip_bucket_check=True)
        yield format_log("引擎初始化成功", "success")
        
        yield format_log("正在获取全量数据库记录...", "system")
        all_images = get_images_by_path_prefix('') # Empty string = known prefix matching all? or logic needs fix?
        # database.py get_images_by_path_prefix uses "LIKE name%". If name is '', it matches everything.
        total = len(all_images)
        yield format_log(f"数据库记录总数: {total}", "info")
        await asyncio.sleep(0.01)
        
        deleted_count = 0
        # Get current Faiss UUIDs locally to speed up lookup
        uuid_set = set(faiss_manager.uuid_map.get("uuid_to_index", {}).keys())
        yield format_log(f"Faiss 索引向量数: {len(uuid_set)}", "info")
        
        for i, img in enumerate(all_images):
            uuid = img['uuid']
            
            if uuid not in uuid_set:
                yield format_log(f"!!! 发现特征缺失 [{i+1}/{total}]: UUID={uuid}", "warning")
                delete_image_by_uuid(uuid)
                yield format_log(f"  -> 数据库记录清理: 成功", "success")
                
                # Physical Delete
                rel_path = img.get('relative_path')
                if rel_path:
                    try:
                        minio_client.delete_file(rel_path)
                        yield format_log(f"  -> 物理图片清理: 成功", "success")
                        
                        p = Path(rel_path)
                        json_path = str(p.parent / p.stem) + ".json"
                        minio_client.delete_file(json_path)
                        yield format_log(f"  -> 物理JSON清理: 成功", "success")
                    except Exception as e:
                         yield format_log(f"  -> 物理清理失败: {e}", "error")
                    
                deleted_count += 1
            else:
                 if i % 50 == 0:
                     yield format_log(f"记录审计通过 [{i+1}/{total}]: 向量正常", "progress")
            
            await asyncio.sleep(0.01)
                
        yield format_log(f"审计完成，共清理 {deleted_count} 条无特征记录", "success")
        
        for log in _sync_all_to_minio_gen():
            yield log
            await asyncio.sleep(0.01)
            
        yield format_log("任务全部完成", "done")
        
    except Exception as e:
        yield format_log(f"审计崩溃: {e}", "error")

@router.post("/check-features")
async def check_features_endpoint():
    return StreamingResponse(check_features_generator(), media_type="application/x-ndjson")


class ReextractTagsRequest(BaseModel):
    limit: int = 2000
    model: str = "gemini"  # gemini | qwen | codex


async def reextract_tags_generator(limit: int, model: str):
    """调用 scripts/reextract_missing_tags_gemini.py 进行缺失标签补齐"""
    global CURRENT_REEXTRACT_TASK

    # 如果已有任务在运行，则拒绝重复启动
    if CURRENT_REEXTRACT_TASK.get("running"):
        yield format_log("已有缺失标签补齐任务正在运行，禁止重复启动。", "warning")
        yield format_log("任务结束", "done")
        return

    project_root = Path(__file__).parent.parent.parent
    model_normalized = (model or "").strip().lower()
    script_name_by_model = {
        "gemini": "reextract_missing_tags_gemini.py",
        "qwen": "reextract_missing_tags_gemini.py",
        "codex": "demo_codex_api.py",
    }
    script_name = script_name_by_model.get(model_normalized)
    if not script_name:
        yield format_log(f"不支持的模型: {model}", "error")
        yield format_log("任务结束", "done")
        return

    script_path = project_root / "scripts" / script_name
    
    if not script_path.exists():
        msg = f"脚本文件不存在: {script_path}"
        yield format_log(msg, "error")
        yield format_log("任务结束", "done")
        return
    
    # 初始化任务状态与日志文件
    CURRENT_REEXTRACT_TASK = {
        "running": True,  # 初始认为在跑，/status 会用 PID 重新校验
        "model": model,
        "limit": limit,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "pid": None,
    }
    try:
        REEXTRACT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REEXTRACT_LOG_PATH.open("w", encoding="utf-8") as f:
            f.write("")
    except Exception as e:
        logger.warning(f"初始化缺失标签补齐日志文件失败: {e}")

    start_msg = f"任务启动: 补齐缺失标签 (最新 {limit} 张, 模型: {model_normalized})"
    start_line = format_log(start_msg, "start")
    yield start_line
    try:
        with REEXTRACT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(start_line)
    except Exception:
        pass

    await asyncio.sleep(0.01)
    
    # 确定工作目录和 Python 解释器
    venv_python = project_root / "backend" / "venv" / "bin" / "python"
    
    # 如果 venv 不存在，使用系统 python3
    if not venv_python.exists():
        python_cmd = "python3"
    else:
        python_cmd = str(venv_python)
    
    # 构建命令
    env = os.environ.copy()
    env["REEXTRACT_MODE"] = "batch"
    env["REEXTRACT_LIMIT"] = str(limit)
    if model_normalized == "gemini":
        env["GEMINI_MODEL"] = "gemini-3-flash-preview"
    
    try:
        # 启动子进程
        process = subprocess.Popen(
            [python_cmd, "-u", str(script_path)],
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # 行缓冲
            env=env
        )

        # 记录子进程 PID，供 /status 查询
        CURRENT_REEXTRACT_TASK["pid"] = process.pid
        
        # 实时读取输出
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                line = line.strip()
                if line:
                    # 根据输出内容判断日志类型
                    log_type = "info"
                    if "失败" in line or "错误" in line or "Error" in line:
                        log_type = "error"
                    elif "成功" in line or "完成" in line or "✓" in line:
                        log_type = "success"
                    elif "警告" in line or "Warning" in line:
                        log_type = "warning"
                    elif "任务启动" in line or "Initializing" in line:
                        log_type = "start"
                    elif "任务结束" in line or "任务全部完成" in line or "补齐完成" in line:
                        log_type = "done"
                    
                    log_line = format_log(line, log_type)
                    # 写前端
                    yield log_line
                    # 追加到日志文件
                    try:
                        with REEXTRACT_LOG_PATH.open("a", encoding="utf-8") as f:
                            f.write(log_line)
                    except Exception:
                        pass

                    await asyncio.sleep(0.01)  # 避免阻塞
        
        # 等待进程结束
        return_code = process.wait()
        
        if return_code == 0:
            end_msg = "任务全部完成"
            end_line = format_log(end_msg, "done")
            yield end_line
            try:
                with REEXTRACT_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(end_line)
            except Exception:
                pass
        else:
            err_msg = f"任务异常退出，返回码: {return_code}"
            err_line = format_log(err_msg, "error")
            yield err_line
            end_line = format_log("任务结束", "done")
            yield end_line
            try:
                with REEXTRACT_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(err_line)
                    f.write(end_line)
            except Exception:
                pass
            
    except Exception as e:
        err_msg = f"执行脚本时出错: {e}"
        err_line = format_log(err_msg, "error")
        yield err_line
        end_line = format_log("任务结束", "done")
        yield end_line
        try:
            with REEXTRACT_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(err_line)
                f.write(end_line)
        except Exception:
            pass
    finally:
        # 不在这里直接把 running 置为 False，而是交给 /status 根据 PID 实时判断；
        # 这样即便前端断开连接、生成器提前结束，脚本在后台继续跑时，/status 仍能识别为运行中。
        pass


@router.post("/reextract-tags")
async def reextract_tags_endpoint(req: ReextractTagsRequest):
    """调用 reextract_missing_tags_gemini.py 脚本进行缺失标签补齐"""
    return StreamingResponse(
        reextract_tags_generator(req.limit, req.model),
        media_type="application/x-ndjson"
    )


@router.get("/reextract-tags/status")
async def reextract_tags_status():
    """查询缺失标签补齐任务当前状态"""
    data = CURRENT_REEXTRACT_TASK.copy()

    pid = data.get("pid")
    if not pid:
        data["running"] = False
        return data

    # 通过检查 PID 是否存在来判断脚本是否仍在运行
    try:
        # 向进程发送 0 信号不会真正杀死进程，但会在不存在时抛出异常
        os.kill(pid, 0)  # type: ignore[arg-type]
        still_running = True
    except OSError:
        still_running = False

    data["running"] = still_running

    # 如果已经不在运行，则清理一下内存中的状态（下次会被当成无任务）
    if not still_running:
        CURRENT_REEXTRACT_TASK.update({
            "running": False,
            "model": None,
            "limit": None,
            "started_at": None,
            "pid": None,
        })

    return data


async def reextract_tags_log_stream_generator():
    """从当前时间开始追踪缺失标签补齐日志（如果已有日志文件则从文件尾部开始）"""
    if not REEXTRACT_LOG_PATH.exists():
        # 没有日志文件时给一个友好提示
        yield format_log("当前暂无缺失标签补齐任务日志。", "info")
        yield format_log("日志流结束", "done")
        return

    try:
        with REEXTRACT_LOG_PATH.open("r", encoding="utf-8") as f:
            # 只读取“连接之后”的新日志
            f.seek(0, os.SEEK_END)
            while True:
                position = f.tell()
                line = f.readline()
                if not line:
                    # 如果任务已经结束且没有新日志，则退出
                    if not CURRENT_REEXTRACT_TASK.get("running"):
                        await asyncio.sleep(0.5)
                        break
                    await asyncio.sleep(0.5)
                    f.seek(position)
                    continue

                # 文件中已经是 NDJSON，直接透传给前端
                yield line
                await asyncio.sleep(0.01)

        # 结束标记
        yield format_log("日志流结束", "done")

    except Exception as e:
        yield format_log(f"读取日志时出错: {e}", "error")
        yield format_log("日志流结束", "done")


@router.get("/reextract-tags/log-stream")
async def reextract_tags_log_stream():
    """重新打开日志窗口时，追踪当前缺失标签补齐任务的输出"""
    return StreamingResponse(
        reextract_tags_log_stream_generator(),
        media_type="application/x-ndjson"
    )
