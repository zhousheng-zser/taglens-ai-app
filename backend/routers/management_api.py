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
import queue
import threading
from datetime import datetime

from core.minio_storage_client import get_storage_client
from services.faiss_index_manager import get_faiss_index_manager
from core.database import (
    delete_image_by_uuid,
    get_images_by_path_prefix,
    get_all_image_uuids,
    get_image_by_uuid,
)
from core.event_database import (
    get_pending_event_videos_for_segmentation,
    get_pending_segments_for_ai_description,
    update_event_segmentation_result,
)
from functools import partial

from services.event_segment_ai_batch_service import (
    SegmentDescFillFatalNetworkError,
    fill_one_segment_description,
    get_batch_max_workers,
    get_batch_executor,
)
from services.event_video_segment_service import (
    ensure_ffmpeg_available,
    process_event_video_segmentation,
)
from core.sync_executor import run_blocking
from services.event_segment_ai_description_service import check_rlq_api_available
from services.segment_media_validator import is_playability_check_enabled
from services.reextract_tags_service import run_reextract_batch

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

SEGMENT_DESC_FILL_LOG_PATH = Path(__file__).parent.parent.parent / "data" / "segment_desc_fill.log"
CURRENT_SEGMENT_DESC_FILL_TASK: Dict[str, Any] = {
    "running": False,
    "limit": None,
    "eventTypeCodes": None,
    "started_at": None,
    "cancel_event": None,
}

EVENT_VIDEO_SEGMENT_LOG_PATH = Path(__file__).parent.parent.parent / "data" / "event_video_segment.log"
CURRENT_EVENT_VIDEO_SEGMENT_TASK: Dict[str, Any] = {
    "running": False,
    "limit": None,
    "eventTypeCodes": None,
    "started_at": None,
    "cancel_event": None,
}

class PathRequest(BaseModel):
    path: str

def format_log(message: str, type: str = "info"):
    return json.dumps({"message": message, "type": type}, ensure_ascii=False) + "\n"


def _append_segment_desc_fill_log_line(line: str) -> None:
    SEGMENT_DESC_FILL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SEGMENT_DESC_FILL_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


async def _log_segment_desc_fill(message: str, log_type: str = "info") -> None:
    line = format_log(message, log_type)
    await run_blocking(_append_segment_desc_fill_log_line, line)


def _append_event_video_segment_log_line(line: str) -> None:
    EVENT_VIDEO_SEGMENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_VIDEO_SEGMENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


async def _log_event_video_segment(message: str, log_type: str = "info") -> None:
    line = format_log(message, log_type)
    await run_blocking(_append_event_video_segment_log_line, line)

async def _sync_all_to_minio_gen():
    """Generator for syncing steps"""
    try:
        yield format_log(">> 系统: 正在上传 Faiss 索引...", "system")
        await run_blocking(get_faiss_index_manager()._upload_to_minio)
        yield format_log(">> 系统: Faiss 索引同步完成", "success")
    except Exception as e:
        yield format_log(f"同步失败: {e}", "error")

async def delete_path_generator(prefix: str):
    yield format_log(f"任务启动: 目标前缀 '{prefix}'", "start")
    await asyncio.sleep(0.01) # Force flush
    
    try:
        yield format_log("正在初始化 MinIO 客户端...", "system")
        minio_client = await run_blocking(get_storage_client, skip_bucket_check=True)
        yield format_log("MinIO 客户端连接成功", "success")
        await asyncio.sleep(0.01)

        yield format_log("正在加载 Faiss 索引管理器...", "system")
        faiss_manager = await run_blocking(get_faiss_index_manager)
        yield format_log("Faiss 管理器加载成功", "success")
        await asyncio.sleep(0.01)
        
        
        # 1. Delete from DB and Faiss
        yield format_log("正在查询关联数据库记录 (可能需要几秒钟)...", "info")
        await asyncio.sleep(0.01) # Force Flush
        
        db_images = await run_blocking(get_images_by_path_prefix, prefix)
        total_db = len(db_images)
        yield format_log(f"数据库查询完毕: 发现 {total_db} 条相关记录", "info" if total_db > 0 else "warning")
        
        deleted_db_count = 0
        for i, img in enumerate(db_images):
            uuid = img['uuid']
            rel_path = img.get('relative_path', '未知路径')
            yield format_log(f"处理记录 [{i+1}/{total_db}]: {rel_path}", "info")
            
            try:
                await run_blocking(delete_image_by_uuid, uuid)
                yield format_log(f"  -> SQLite 删除: 成功", "success")
            except Exception as e:
                yield format_log(f"  -> SQLite 删除: 失败 ({e})", "error")
                
            try:
                await run_blocking(faiss_manager.remove_vector, uuid)
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
            objects = await run_blocking(
                lambda: list(minio_client.client.list_objects(minio_client.bucket, prefix=prefix, recursive=True))
            )
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
        async for log in _sync_all_to_minio_gen():
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
        minio_client = await run_blocking(get_storage_client, skip_bucket_check=True)
        yield format_log("MinIO 客户端连接成功", "success")
        
        yield format_log("正在获取 MinIO 文件列表...", "system")
        objects = await run_blocking(
            lambda: list(minio_client.client.list_objects(minio_client.bucket, prefix=prefix, recursive=True))
        )
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
        
        async for log in _sync_all_to_minio_gen():
            yield log
            await asyncio.sleep(0.01)
            
        yield format_log("任务全部完成", "done")
        
    except Exception as e:
        yield format_log(f"检查出错: {e}", "error")

@router.post("/check-pairs")
async def check_pairs_endpoint(req: PathRequest):
    return StreamingResponse(check_pairs_generator(req.path), media_type="application/x-ndjson")


async def check_features_generator():
    yield format_log("任务启动: 全库特征向量审计", "start")
    await asyncio.sleep(0.01)
    
    try:
        faiss_manager = await run_blocking(get_faiss_index_manager)
        minio_client = await run_blocking(get_storage_client, skip_bucket_check=True)
        yield format_log("引擎初始化成功", "success")
        
        yield format_log("正在获取全量数据库记录...", "system")
        all_images = await run_blocking(get_images_by_path_prefix, '')
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
                await run_blocking(delete_image_by_uuid, uuid)
                yield format_log(f"  -> 数据库记录清理: 成功", "success")
                
                # Physical Delete
                rel_path = img.get('relative_path')
                if rel_path:
                    try:
                        await run_blocking(minio_client.delete_file, rel_path)
                        yield format_log(f"  -> 物理图片清理: 成功", "success")
                        
                        p = Path(rel_path)
                        json_path = str(p.parent / p.stem) + ".json"
                        await run_blocking(minio_client.delete_file, json_path)
                        yield format_log(f"  -> 物理JSON清理: 成功", "success")
                    except Exception as e:
                         yield format_log(f"  -> 物理清理失败: {e}", "error")
                    
                deleted_count += 1
            else:
                 if i % 50 == 0:
                     yield format_log(f"记录审计通过 [{i+1}/{total}]: 向量正常", "progress")
            
            await asyncio.sleep(0.01)
                
        yield format_log(f"审计完成，共清理 {deleted_count} 条无特征记录", "success")
        
        async for log in _sync_all_to_minio_gen():
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
    model: str = "gemini"  # gemini | qwen | codex | mimo


class EventVideoSegmentRequest(BaseModel):
    limit: int = 10
    eventTypeCodes: List[str] = []


class EventSegmentDescFillRequest(BaseModel):
    limit: int = 10
    eventTypeCodes: List[str] = []


def _segment_and_persist_one_event(minio_client, row: Dict[str, Any]) -> Dict[str, Any]:
    """单条事件视频分块并写库（同步，在线程池中执行，避免阻塞 asyncio 事件循环）。"""
    video_path = str(row["video_path"] or "").strip()
    result = process_event_video_segmentation(minio_client=minio_client, video_path=video_path)
    update_event_segmentation_result(
        event_id=str(row["event_id"]),
        project_id=str(row["project_id"]),
        event_type_corrected=str(row.get("event_type_corrected") or ""),
        segment_paths=result["segment_paths"],
        segment_descriptions=result["segment_descriptions"],
        segment_statuses=result["segment_statuses"],
    )
    return result


async def _run_event_video_segment_job(
    limit: int,
    event_type_codes: Optional[List[str]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    global CURRENT_EVENT_VIDEO_SEGMENT_TASK

    def stop_requested() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    safe_limit = max(int(limit or 0), 1)
    normalized_codes = [item.strip() for item in (event_type_codes or []) if item and item.strip()]
    scope_text = "全部事件类型" if not normalized_codes else f"事件类型={','.join(normalized_codes)}"
    try:
        await _log_event_video_segment(
            f"任务启动: 事件视频分块 (处理数量: {safe_limit}, {scope_text})",
            "start",
        )
        await asyncio.to_thread(ensure_ffmpeg_available)
        await _log_event_video_segment("FFmpeg 环境检查通过", "success")
    except Exception as exc:
        await _log_event_video_segment(f"FFmpeg 环境检查失败: {exc}", "error")
        await _log_event_video_segment("任务结束", "done")
        return

    try:
        minio_client = get_storage_client(skip_bucket_check=True)
        await _log_event_video_segment("MinIO 客户端初始化成功", "success")
    except Exception as exc:
        await _log_event_video_segment(f"MinIO 客户端初始化失败: {exc}", "error")
        await _log_event_video_segment("任务结束", "done")
        return

    rows = await asyncio.to_thread(
        get_pending_event_videos_for_segmentation,
        safe_limit,
        normalized_codes,
    )
    total = len(rows)
    if total <= 0:
        await _log_event_video_segment(
            "未找到可处理视频（仅处理未分块、video_path 非空且符合事件类型筛选的记录）",
            "warning",
        )
        await _log_event_video_segment("任务结束", "done")
        return

    await _log_event_video_segment(f"待处理记录数: {total}（按 start_time 倒序）", "info")

    success_count = 0
    failed_count = 0
    skipped_count = 0
    skipped_not_started = 0

    for idx, row in enumerate(rows, start=1):
        if stop_requested():
            skipped_not_started = total - idx + 1
            await _log_event_video_segment(
                "收到停止请求：已停止提交新视频，等待当前处理结束后退出。",
                "warning",
            )
            break
        event_id = str(row["event_id"])
        video_path = str(row["video_path"] or "").strip()
        if not video_path:
            skipped_count += 1
            await _log_event_video_segment(
                f"[{idx}/{total}] event_id={event_id} 跳过: video_path 为空",
                "warning",
            )
            continue

        await _log_event_video_segment(f"[{idx}/{total}] 开始处理 event_id={event_id}", "info")
        await _log_event_video_segment(f"  -> 源视频: {video_path}", "progress")
        await _log_event_video_segment("  -> 后台执行: 下载 / FFmpeg 分块 / 上传 MinIO ...", "progress")
        try:
            result = await asyncio.to_thread(_segment_and_persist_one_event, minio_client, row)
            success_count += 1
            await _log_event_video_segment(
                f"  -> 分块成功: 共 {len(result['segment_paths'])} 段",
                "success",
            )
        except Exception as exc:
            failed_count += 1
            await _log_event_video_segment(f"  -> 分块失败: {exc}", "error")

    await _log_event_video_segment(
        f"任务完成: 成功 {success_count} 条, 跳过 {skipped_count} 条"
        f"（含未启动 {skipped_not_started}）, 失败 {failed_count} 条",
        "done",
    )


async def _event_video_segment_log_follow_generator(from_start: bool = False):
    """跟踪事件视频分块日志文件（启动任务时从头读；重连时从尾部读）。"""
    if not EVENT_VIDEO_SEGMENT_LOG_PATH.exists():
        yield format_log("当前暂无事件视频分块任务日志。", "info")
        yield format_log("日志流结束", "done")
        return

    position = 0 if from_start else EVENT_VIDEO_SEGMENT_LOG_PATH.stat().st_size
    idle_rounds = 0

    try:
        while True:
            got_new = False
            with EVENT_VIDEO_SEGMENT_LOG_PATH.open("r", encoding="utf-8") as f:
                f.seek(position)
                while True:
                    line = f.readline()
                    if not line:
                        position = f.tell()
                        break
                    if line.strip():
                        yield line
                        got_new = True
                    position = f.tell()

            if CURRENT_EVENT_VIDEO_SEGMENT_TASK.get("running"):
                idle_rounds = 0
                await asyncio.sleep(0.2)
                continue

            if got_new:
                idle_rounds = 0
                await asyncio.sleep(0.2)
                continue

            idle_rounds += 1
            if idle_rounds >= 2:
                break
            await asyncio.sleep(0.2)

        yield format_log("日志流结束", "done")
    except Exception as exc:
        yield format_log(f"读取日志时出错: {exc}", "error")
        yield format_log("日志流结束", "done")


async def event_video_segment_generator(limit: int, event_type_codes: Optional[List[str]] = None):
    global CURRENT_EVENT_VIDEO_SEGMENT_TASK

    if CURRENT_EVENT_VIDEO_SEGMENT_TASK.get("running"):
        async def reject_stream():
            yield format_log("已有事件视频分块任务正在运行，禁止重复启动。", "warning")
            yield format_log("任务结束", "done")
        return StreamingResponse(reject_stream(), media_type="application/x-ndjson")

    try:
        EVENT_VIDEO_SEGMENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_VIDEO_SEGMENT_LOG_PATH.open("w", encoding="utf-8") as f:
            f.write("")
    except Exception as exc:
        logger.warning(f"初始化事件视频分块日志文件失败: {exc}")

    cancel_event = threading.Event()
    CURRENT_EVENT_VIDEO_SEGMENT_TASK = {
        "running": True,
        "limit": limit,
        "eventTypeCodes": list(event_type_codes or []),
        "started_at": datetime.utcnow().isoformat() + "Z",
        "cancel_event": cancel_event,
    }

    async def _job_wrapper() -> None:
        try:
            await _run_event_video_segment_job(limit, event_type_codes, cancel_event=cancel_event)
        except Exception as exc:
            await _log_event_video_segment(f"任务异常: {exc}", "error")
            await _log_event_video_segment("任务结束", "done")
        finally:
            CURRENT_EVENT_VIDEO_SEGMENT_TASK["running"] = False
            try:
                ev = CURRENT_EVENT_VIDEO_SEGMENT_TASK.get("cancel_event")
                if isinstance(ev, threading.Event):
                    ev.clear()
            except Exception:
                pass

    asyncio.create_task(_job_wrapper())

    return StreamingResponse(
        _event_video_segment_log_follow_generator(from_start=True),
        media_type="application/x-ndjson",
    )


@router.post("/event-video-segment")
async def event_video_segment_endpoint(req: EventVideoSegmentRequest):
    return await event_video_segment_generator(req.limit, req.eventTypeCodes)


@router.get("/event-video-segment/status")
async def event_video_segment_status():
    """查询事件视频分块任务是否在运行（关页后仍可探测）。"""
    data = CURRENT_EVENT_VIDEO_SEGMENT_TASK.copy()
    data.pop("cancel_event", None)
    return data


@router.post("/event-video-segment/stop")
async def event_video_segment_stop():
    """停止事件视频分块：停止提交新视频，等待进行中的视频处理完成后退出。"""
    running = bool(CURRENT_EVENT_VIDEO_SEGMENT_TASK.get("running"))
    cancel_event = CURRENT_EVENT_VIDEO_SEGMENT_TASK.get("cancel_event")
    if running and isinstance(cancel_event, threading.Event):
        cancel_event.set()
        return {"success": True, "running": True}
    return {"success": False, "running": running, "reason": "no running task"}


@router.get("/event-video-segment/log-stream")
async def event_video_segment_log_stream(from_start: bool = True):
    """重新打开日志窗口：默认从头回放日志并继续跟踪新输出。"""
    return StreamingResponse(
        _event_video_segment_log_follow_generator(from_start=from_start),
        media_type="application/x-ndjson",
    )


async def _run_segment_desc_fill_job(
    limit: int,
    event_type_codes: Optional[List[str]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    """后台任务：与 HTTP 连接解耦，日志写入文件；执行阶段使用专用线程池并行补齐。"""
    global CURRENT_SEGMENT_DESC_FILL_TASK

    def stop_requested() -> bool:
        return bool(cancel_event and cancel_event.is_set())
    safe_limit = max(int(limit or 0), 1)
    normalized_codes = [item.strip() for item in (event_type_codes or []) if item and item.strip()]
    scope_text = "全部事件类型" if not normalized_codes else f"事件类型={','.join(normalized_codes)}"
    workers = get_batch_max_workers()

    try:
        await _log_segment_desc_fill(
            f"任务启动: 事件分段描述补齐 (处理分段数: {safe_limit}, {scope_text}, 并行度: {workers})",
            "start",
        )
        if is_playability_check_enabled():
            await _log_segment_desc_fill(
                "已启用送模型前视频损坏检测（ffmpeg）；损坏分段将跳过，不调用 AI",
                "info",
            )
        else:
            await _log_segment_desc_fill(
                "未启用视频损坏检测（需安装 ffmpeg/ffprobe 且 EVENT_SEGMENT_VALIDATE_PLAYABLE=true）",
                "warning",
            )

        rlq_err = await run_blocking(check_rlq_api_available)
        if rlq_err:
            await _log_segment_desc_fill(
                f"RLQ 服务探测失败（将继续处理 {safe_limit} 段：损坏视频跳过，其余逐段尝试调用模型）: {rlq_err}",
                "warning",
            )
        else:
            await _log_segment_desc_fill(
                f"RLQ 服务可用: {os.getenv('EVENT_SEGMENT_AI_BASE_URL', '')}",
                "info",
            )

        items = await run_blocking(
            get_pending_segments_for_ai_description,
            safe_limit,
            normalized_codes,
        )
        total = len(items)
        if total <= 0:
            await _log_segment_desc_fill(
                "未找到待补齐分段（segment_paths_json 须有有效 mp4、描述为空，且符合事件类型筛选）",
                "warning",
            )
            await _log_segment_desc_fill("任务结束", "done")
            return

        await _log_segment_desc_fill(
            f"待处理分段数: {total}（按事件 start_time 倒序，最多 {workers} 路并行）",
            "info",
        )

        loop = asyncio.get_running_loop()
        batch_executor = get_batch_executor()
        success_count = 0
        failed_count = 0
        skipped_count = 0
        count_lock = asyncio.Lock()
        work_sem = asyncio.Semaphore(workers)

        async def _run_one(seq: int, item: Dict[str, Any]) -> None:
            nonlocal success_count, failed_count, skipped_count
            async with work_sem:
                event_id = str(item["event_id"])
                seg_label = str(int(item["segment_index"])).zfill(3)

                await _log_segment_desc_fill(
                    f"[{seq}/{total}] 开始处理 event_id={event_id} 分段 {seg_label}",
                    "info",
                )
                await _log_segment_desc_fill(f"  -> 视频: {item['segment_media_path']}", "progress")
                if item.get("overlay_media_path"):
                    await _log_segment_desc_fill(f"  -> 叠框图: {item['overlay_media_path']}", "progress")
                else:
                    await _log_segment_desc_fill("  -> 叠框图: 无（仅视频）", "progress")

                log_sink: list[tuple[str, str]] = []
                try:
                    result = await loop.run_in_executor(
                        batch_executor,
                        partial(fill_one_segment_description, item, log_sink),
                    )
                except SegmentDescFillFatalNetworkError:
                    for msg, typ in log_sink:
                        await _log_segment_desc_fill(msg, typ)
                    raise
                except Exception as exc:
                    for msg, typ in log_sink:
                        await _log_segment_desc_fill(msg, typ)
                    async with count_lock:
                        failed_count += 1
                    await _log_segment_desc_fill(f"  -> 补齐失败: {exc}", "error")
                    return

                for msg, typ in log_sink:
                    await _log_segment_desc_fill(msg, typ)

                if result.damage_log:
                    await _log_segment_desc_fill(f"  -> 视频检测: {result.damage_log}", "info")

                if getattr(result, "skipped", False):
                    async with count_lock:
                        skipped_count += 1
                    await _log_segment_desc_fill(f"  -> 已跳过（视频损坏）: {result.error}", "warning")
                elif result.success:
                    async with count_lock:
                        success_count += 1
                    preview = (
                        (result.description[:120] + "…")
                        if len(result.description) > 120
                        else result.description
                    )
                    await _log_segment_desc_fill(f"  -> 补齐成功: {preview}", "success")
                else:
                    async with count_lock:
                        failed_count += 1
                    if "RLQ" in (result.error or "") or "404" in (result.error or ""):
                        await _log_segment_desc_fill(
                            f"  -> 补齐失败（RLQ API，视频已通过损坏检测）: {result.error}",
                            "error",
                        )
                    else:
                        await _log_segment_desc_fill(f"  -> 补齐失败: {result.error}", "error")

        if stop_requested():
            await _log_segment_desc_fill(
                "检测到已请求停止：不再提交新分段，等待进行中的分段处理完成后退出。",
                "warning",
            )

        next_pos = 0
        active: set[asyncio.Task] = set()
        skipped_not_started = 0
        fatal_network_abort = False

        while next_pos < total or active:
            while (
                next_pos < total
                and len(active) < workers
                and not stop_requested()
            ):
                seq = next_pos + 1
                item = items[next_pos]
                next_pos += 1
                active.add(asyncio.create_task(_run_one(seq, item)))

            if not active:
                if stop_requested() and next_pos < total:
                    skipped_not_started = total - next_pos
                break

            done, active = await asyncio.wait(
                active, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                try:
                    task.result()
                except SegmentDescFillFatalNetworkError as exc:
                    if stop_requested():
                        await _log_segment_desc_fill(
                            f"  -> 网络异常已触发致命错误（但已请求停止）：{exc}",
                            "warning",
                        )
                    else:
                        await _log_segment_desc_fill(f"\n任务中止: {exc}", "error")
                        for pending in active:
                            pending.cancel()
                        fatal_network_abort = True
                except Exception as exc:
                    await _log_segment_desc_fill(f"  -> 分段任务异常: {exc}", "error")

            if fatal_network_abort:
                active.clear()
                break

        if stop_requested():
            skipped_not_started = total - next_pos
            await _log_segment_desc_fill(
                "收到停止请求：已停止提交新分段，等待进行中的分段处理完成后退出。",
                "warning",
            )

        await _log_segment_desc_fill(
            f"任务完成: 成功 {success_count} 段, 跳过 {skipped_count} 段"
            f"（含未启动 {skipped_not_started}）, 失败 {failed_count} 段（并行度 {workers}）",
            "done",
        )
    except Exception as exc:
        await _log_segment_desc_fill(f"任务异常: {exc}", "error")
        await _log_segment_desc_fill("任务结束", "done")
    finally:
        CURRENT_SEGMENT_DESC_FILL_TASK["running"] = False
        try:
            ev = CURRENT_SEGMENT_DESC_FILL_TASK.get("cancel_event")
            if isinstance(ev, threading.Event):
                ev.clear()
        except Exception:
            pass


async def _segment_desc_fill_log_follow_generator(from_start: bool = False):
    """跟踪分段描述补齐日志文件（启动任务时从头读；重连时从尾部读）。"""
    if not SEGMENT_DESC_FILL_LOG_PATH.exists():
        yield format_log("当前暂无事件分段描述补齐任务日志。", "info")
        yield format_log("日志流结束", "done")
        return

    position = 0 if from_start else SEGMENT_DESC_FILL_LOG_PATH.stat().st_size
    idle_rounds = 0

    try:
        while True:
            got_new = False
            with SEGMENT_DESC_FILL_LOG_PATH.open("r", encoding="utf-8") as f:
                f.seek(position)
                while True:
                    line = f.readline()
                    if not line:
                        position = f.tell()
                        break
                    if line.strip():
                        yield line
                        got_new = True
                    position = f.tell()

            if CURRENT_SEGMENT_DESC_FILL_TASK.get("running"):
                idle_rounds = 0
                await asyncio.sleep(0.2)
                continue

            if got_new:
                idle_rounds = 0
                await asyncio.sleep(0.2)
                continue

            idle_rounds += 1
            if idle_rounds >= 2:
                break
            await asyncio.sleep(0.2)

        yield format_log("日志流结束", "done")
    except Exception as exc:
        yield format_log(f"读取日志时出错: {exc}", "error")
        yield format_log("日志流结束", "done")


@router.post("/event-segment-desc-fill")
async def event_segment_desc_fill_endpoint(req: EventSegmentDescFillRequest):
    global CURRENT_SEGMENT_DESC_FILL_TASK

    if CURRENT_SEGMENT_DESC_FILL_TASK.get("running"):
        async def reject_stream():
            yield format_log("已有事件分段描述补齐任务正在运行，禁止重复启动。", "warning")
            yield format_log("任务结束", "done")

        return StreamingResponse(reject_stream(), media_type="application/x-ndjson")

    try:
        SEGMENT_DESC_FILL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SEGMENT_DESC_FILL_LOG_PATH.open("w", encoding="utf-8") as f:
            f.write("")
    except Exception as exc:
        logger.warning(f"初始化分段描述补齐日志文件失败: {exc}")

    cancel_event = threading.Event()
    CURRENT_SEGMENT_DESC_FILL_TASK = {
        "running": True,
        "limit": req.limit,
        "eventTypeCodes": list(req.eventTypeCodes or []),
        "started_at": datetime.utcnow().isoformat() + "Z",
        "cancel_event": cancel_event,
    }
    asyncio.create_task(
        _run_segment_desc_fill_job(req.limit, req.eventTypeCodes, cancel_event=cancel_event)
    )

    return StreamingResponse(
        _segment_desc_fill_log_follow_generator(from_start=True),
        media_type="application/x-ndjson",
    )


@router.get("/event-segment-desc-fill/status")
async def event_segment_desc_fill_status():
    """查询事件分段描述补齐任务是否在运行（关页后仍可探测）。"""
    data = CURRENT_SEGMENT_DESC_FILL_TASK.copy()
    data.pop("cancel_event", None)
    return data


@router.post("/event-segment-desc-fill/stop")
async def event_segment_desc_fill_stop():
    """停止事件分段描述补齐：停止提交新分段，等待进行中的分段结束后退出。"""
    running = bool(CURRENT_SEGMENT_DESC_FILL_TASK.get("running"))
    cancel_event = CURRENT_SEGMENT_DESC_FILL_TASK.get("cancel_event")
    if running and isinstance(cancel_event, threading.Event):
        cancel_event.set()
        return {"success": True, "running": True}
    return {"success": False, "running": running, "reason": "no running task"}


@router.get("/event-segment-desc-fill/log-stream")
async def event_segment_desc_fill_log_stream(from_start: bool = True):
    """重新打开日志窗口：默认从头回放日志并继续跟踪新输出。"""
    return StreamingResponse(
        _segment_desc_fill_log_follow_generator(from_start=from_start),
        media_type="application/x-ndjson",
    )


async def reextract_tags_generator(limit: int, model: str):
    """通过统一 LLM 网关批量补齐缺失标签。"""
    global CURRENT_REEXTRACT_TASK

    if CURRENT_REEXTRACT_TASK.get("running"):
        yield format_log("已有缺失标签补齐任务正在运行，禁止重复启动。", "warning")
        yield format_log("任务结束", "done")
        return

    model_normalized = (model or "").strip().lower()
    if model_normalized not in ("qwen", "gemini", "codex", "mimo"):
        yield format_log(f"不支持的模型: {model}", "error")
        yield format_log("任务结束", "done")
        return

    cancel_event = threading.Event()
    CURRENT_REEXTRACT_TASK = {
        "running": True,
        "model": model_normalized,
        "limit": limit,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "pid": None,
        "thread": None,
        "cancel_event": cancel_event,
    }
    try:
        REEXTRACT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REEXTRACT_LOG_PATH.open("w", encoding="utf-8") as f:
            f.write("")
    except Exception as e:
        logger.warning(f"初始化缺失标签补齐日志文件失败: {e}")

    log_queue: queue.Queue = queue.Queue()
    done_event = threading.Event()

    def log_cb(message: str, log_type: str = "info") -> None:
        log_queue.put(format_log(message, log_type))

    def worker() -> None:
        try:
            run_reextract_batch(
                limit,
                model_normalized,
                log=log_cb,
                stop_event=cancel_event,
            )
        except Exception as exc:
            log_cb(f"任务异常: {exc}", "error")
            log_cb("任务结束", "done")
        finally:
            log_queue.put(None)
            done_event.set()
            CURRENT_REEXTRACT_TASK["running"] = False
            # 释放取消事件引用，避免后续误用
            try:
                CURRENT_REEXTRACT_TASK["cancel_event"].clear()
            except Exception:
                pass

    thread = threading.Thread(target=worker, name="reextract-tags", daemon=True)
    thread.start()
    CURRENT_REEXTRACT_TASK["thread"] = thread

    while True:
        item = None
        while True:
            try:
                item = log_queue.get_nowait()
                break
            except queue.Empty:
                break
        if item is None:
            if done_event.is_set():
                while True:
                    try:
                        tail = log_queue.get_nowait()
                    except queue.Empty:
                        break
                    if tail is None:
                        continue
                    yield tail
                break
            await asyncio.sleep(0.2)
            continue
        if item is None:
            break
        yield item
        try:
            def _append_log(ln: str = item) -> None:
                with REEXTRACT_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(ln)

            await run_blocking(_append_log)
        except Exception:
            pass
        await asyncio.sleep(0.01)

    thread.join(timeout=5)


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

    thread = data.get("thread")
    still_running = bool(thread and isinstance(thread, threading.Thread) and thread.is_alive())
    data["running"] = still_running

    if not still_running:
        CURRENT_REEXTRACT_TASK.update({
            "running": False,
            "model": None,
            "limit": None,
            "started_at": None,
            "pid": None,
            "thread": None,
            "cancel_event": None,
        })

    # 避免返回 threading 对象导致序列化失败
    data.pop("thread", None)
    data.pop("cancel_event", None)
    return data


@router.post("/reextract-tags/stop")
async def reextract_tags_stop():
    """停止缺失标签补齐：停止提交新图片，等待正在处理的图片结束后退出。"""
    running = bool(CURRENT_REEXTRACT_TASK.get("running"))
    cancel_event = CURRENT_REEXTRACT_TASK.get("cancel_event")
    if running and isinstance(cancel_event, threading.Event):
        cancel_event.set()
        return {"success": True, "running": True}
    return {"success": False, "running": running, "reason": "no running task"}


def _reextract_task_is_running() -> bool:
    """与 /status 一致：以工作线程是否存活为准。"""
    thread = CURRENT_REEXTRACT_TASK.get("thread")
    if thread and isinstance(thread, threading.Thread) and thread.is_alive():
        return True
    return bool(CURRENT_REEXTRACT_TASK.get("running"))


async def _reextract_log_follow_generator(from_start: bool = False):
    """
    跟踪缺失标签补齐日志文件。
    - 首次 POST 任务：由 reextract_tags_generator 直接推送队列日志；
    - 重连 GET log-stream：默认 from_start=True，先回放已有日志再 tail 新行。
    """
    if not REEXTRACT_LOG_PATH.exists():
        yield format_log("当前暂无缺失标签补齐任务日志。", "info")
        yield format_log("日志流结束", "done")
        return

    position = 0 if from_start else REEXTRACT_LOG_PATH.stat().st_size
    idle_rounds = 0

    try:
        while True:
            got_new = False
            with REEXTRACT_LOG_PATH.open("r", encoding="utf-8") as f:
                f.seek(position)
                while True:
                    line = f.readline()
                    if not line:
                        position = f.tell()
                        break
                    if line.strip():
                        yield line
                        got_new = True
                    position = f.tell()

            if _reextract_task_is_running():
                idle_rounds = 0
                await asyncio.sleep(0.2)
                continue

            if got_new:
                idle_rounds = 0
                await asyncio.sleep(0.2)
                continue

            idle_rounds += 1
            if idle_rounds >= 2:
                break
            await asyncio.sleep(0.2)

        yield format_log("日志流结束", "done")
    except Exception as exc:
        yield format_log(f"读取日志时出错: {exc}", "error")
        yield format_log("日志流结束", "done")


@router.get("/reextract-tags/log-stream")
async def reextract_tags_log_stream(from_start: bool = True):
    """重新打开日志窗口：默认从头回放日志文件并继续跟踪新输出。"""
    return StreamingResponse(
        _reextract_log_follow_generator(from_start=from_start),
        media_type="application/x-ndjson",
    )
