from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import logging
from pathlib import Path
import os
import asyncio
import json
import time

from core.minio_storage_client import get_storage_client
from services.faiss_index_manager import get_faiss_index_manager
from core.database import (
    delete_image_by_uuid, 
    get_images_by_path_prefix, 
    get_all_image_uuids,
    get_image_by_uuid,
    force_sync_to_minio
)

router = APIRouter(prefix="/api/management", tags=["management"])
logger = logging.getLogger(__name__)

class PathRequest(BaseModel):
    path: str

def format_log(message: str, type: str = "info"):
    return json.dumps({"message": message, "type": type}, ensure_ascii=False) + "\n"

def _sync_all_to_minio_gen():
    """Generator for syncing steps"""
    try:
        yield format_log(">> 系统: 正在同步数据库到 MinIO...", "system")
        force_sync_to_minio()
        yield format_log(">> 系统: 数据库同步完成", "success")
        
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
