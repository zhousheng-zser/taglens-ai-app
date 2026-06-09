# -*- coding: utf-8 -*-
import os
import uvicorn
import json
import asyncio
import time
import base64
import uuid
import shlex
import shutil
import subprocess
import tempfile
import threading
import traceback
import threading
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, UploadFile, File, Form, Request, Request
from fastapi.responses import Response, StreamingResponse, FileResponse
import mimetypes
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")
from openai import OpenAI
import httpx
import requests
import numpy as np
import torch
from transformers import AutoTokenizer, AutoModel
from core.database import (
    init_database,
    save_image_to_db,
    search_images,
    get_all_images,
    get_db_connection,
    get_all_projects_db,
    add_project_db,
    delete_project_db,
    update_project_db,
    update_project_model_db,
    update_project_probability_db,
    update_project_stop_time_db,
    update_project_status_by_script_db,
    delete_image_by_uuid,
)
from services.project_sync_systemd import (
    is_managed_sync_script,
    is_running as sync_script_is_running,
    log_file_for_script,
    read_log_tail,
    start_script as sync_start_script,
    stop_script as sync_stop_script,
)
from core.event_database import init_event_database
from core.manage_database import init_manage_database
from services.bulk_import_storage import (
    create_bulk_import_job,
    update_bulk_import_job_status,
    update_bulk_import_progress,
    update_bulk_import_total,
    log_bulk_import,
    delete_bulk_import_job_and_logs,
    get_bulk_import_job,
    get_bulk_import_logs,
    get_bulk_import_processed_files,
    get_active_bulk_import_job,
    get_all_bulk_import_jobs,
)
from services.image_similarity import decode_base64_image, load_image_from_path, extract_spatial_histogram_vector
from services.faiss_index_manager import get_faiss_index_manager
from core.minio_storage_client import get_storage_client
from core.sync_executor import run_blocking
from routers import management_api
from routers import dtc_api
from routers import event_api
from routers import auth_api
from routers import llm_proxy_api
from schemas.llm_schemas import SemanticSearch, TrafficAnalysisOutput, TrainingData
from services.llm_gateway_client import LLM_GATEWAY_URL, check_gateway_health, infer_traffic_image
from services.llm_prompts import PROMPT_PART_1, PROMPT_PART_2_TEMPLATE, PROMPT_PART_3, build_default_analysis_prompt
from services.text_embedding_service import encode_text_to_vector, get_bge_model
from services.search_progress import SearchProgress, SearchProgressCallback, SearchCancellation, SearchCancelledError
from services.search_images_export_service import export_search_images_zip, resolve_export_zip_path
from services.business_structure_manager import get_business_manager_for_project

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)

import numpy as np

def clean_numpy(data):
    if isinstance(data, dict):
        return {k: clean_numpy(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_numpy(v) for v in data]
    elif hasattr(data, 'item'): # numpy scalars
        return data.item()
    elif isinstance(data, np.ndarray):
        return clean_numpy(data.tolist())
    return data


class SaveImageRequest(BaseModel):
    image: str  # Base64 data URI
    tags: list[str]
    keywords: list[str]
    description: str
    fileName: str | None = None
    qwenCaptions: Dict[str, Any] | List[str] = {}  # Qwen 描述
    yoloObjects: list[str] = []  # YOLO 对象

class SaveImageResponse(BaseModel):
    success: bool
    uuid: str
    file_path: str
    relative_path: str
    message: str

class TagWithWeight(BaseModel):
    tag: str
    weight: float  # 权重,范围0-1

class SearchRequest(BaseModel):
    query: Optional[str] = None  # 单个查询（向后兼容）
    queries: Optional[List[str]] = None  # 多个查询标签列表（向后兼容）
    tags: Optional[List[TagWithWeight]] = None  # 标签和权重列表
    limit: Optional[int] = 100  # 最大返回数量（向后兼容,建议使用pageSize）
    page: Optional[int] = 1  # 页码,从1开始
    pageSize: Optional[int] = 20  # 每页数量
    startDate: Optional[str] = None  # ISO 格式日期时间
    endDate: Optional[str] = None    # ISO 格式日期时间
    cameraName: Optional[str] = None  # 相机名模糊匹配（sz_name）
    bizCategory: Optional[str] = None  # 业态目录模糊匹配（sz_tag_ref_json）
    filePath: Optional[str] = None  # 文件路径模糊匹配（relative_path）
    descriptionKeywords: Optional[List[str]] = None  # 综合描述模糊匹配（多个关键词 AND）
    similarityThreshold: Optional[float] = 0.6  # 相似度阈值,范围0-1

class ExportImageItem(BaseModel):
    filePath: str
    uuid: Optional[str] = None
    fileName: Optional[str] = None


class ExportImagesRequest(BaseModel):
    """导出图片：优先使用 items（跳过重复搜索），否则按 search 条件重新搜索。"""
    items: Optional[List[ExportImageItem]] = None
    tags: Optional[List[TagWithWeight]] = None
    query: Optional[str] = None
    queries: Optional[List[str]] = None
    similarityThreshold: Optional[float] = 0.6
    startDate: Optional[str] = None
    endDate: Optional[str] = None
    cameraName: Optional[str] = None
    bizCategory: Optional[str] = None

class KeywordCacheLoadRequest(BaseModel):
    reload: bool = False

class ImageSearchResult(BaseModel):
    id: int
    uuid: str
    filePath: str
    fileName: Optional[str]
    createdAt: str
    description: str
    keywords: List[str]
    tags: List[str]
    qwenCaptions: Dict[str, Any] | List[str]
    yoloObjects: List[str]
    szName: Optional[str] = None
    szTagRefs: List[str] = []
    similarity: Optional[float] = None  # 相似度分数（0-1之间）

class SearchResponse(BaseModel):
    success: bool
    results: List[ImageSearchResult]
    total: int


class DeleteImageRequest(BaseModel):
    uuid: str

class ImageSimilarityCheckRequest(BaseModel):
    image: str  # Base64 data URI
    threshold: Optional[float] = 0.7409  # 相似度阈值,默认0.7409（74.09%）
    max_results: Optional[int] = 5  # 最多返回几个相似图片

class SimilarImageResult(BaseModel):
    uuid: str
    filePath: str
    fileName: Optional[str]
    createdAt: str
    similarity: float  # 相似度分数 (0-1)
    methods: Dict[str, Any]  # 各种算法的详细结果
    imageData: Optional[str] = None  # 图片的base64数据（data URI格式）,用于前端显示

class ImageSimilarityCheckResponse(BaseModel):
    is_similar: bool  # 是否找到相似图片
    max_similarity: float  # 最高相似度
    similar_images: List[SimilarImageResult]  # 相似图片列表
    message: str  # 提示信息


# --- 批量导入模型 ---
class BulkImportStartRequest(BaseModel):
    threshold: Optional[float] = 0.7409  # 默认 74.09%
    directory: Optional[str] = None  # 默认 ./data/local/img


class BulkImportActionRequest(BaseModel):
    job_id: Optional[int] = None


class BulkImportStatusResponse(BaseModel):
    success: bool
    job: Optional[Dict[str, Any]] = None


class BulkImportLogsResponse(BaseModel):
    success: bool
    logs: List[Dict[str, Any]]
    total: int


class BulkImportJobsResponse(BaseModel):
    success: bool
    jobs: List[Dict[str, Any]]

# 如果没有API密钥,将返回此示例数据
mock_analysis_data = {
    "semantic_search": {
        "description": "",
        "keywords": [
        ]
    },
    "training_data": {
        "yolo_objects": [
        ],
        "qwen_captions": {
            "道路结构": {
            },
            "交通设施": {
            },
            "环境信息": {
            },
            "特殊场所": {
            },
            "图像文字信息": {
            }
        }
    }
}


# --- FastAPI 应用设置 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化,关闭时同步数据库"""
    
    # --- 屏蔽轮询接口的访问日志 ---
    import logging
    try:
        class PollingFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                msg = record.getMessage()
                silent_paths = (
                    "/project/logs",
                    "/dtc/tasks",
                    "/dtc/image-sets",
                )
                # 静默高频轮询访问日志，减少控制台噪音
                return not any(p in msg for p in silent_paths)
        
        logging.getLogger("uvicorn.access").addFilter(PollingFilter())
    except Exception:
        pass

    # --- Startup ---
    print("正在初始化应用...")
    init_database()
    print("数据库初始化完成")
    init_event_database()
    print("事件数据库初始化完成")
    init_manage_database()
    print("管理数据库初始化完成")

    # 初始化Faiss索引管理器
    print("正在初始化Faiss LSH索引...")
    try:
        faiss_manager = get_faiss_index_manager()
        total_vectors = faiss_manager.get_total_vectors()
        print(f"✓ Faiss索引加载完成,当前索引中有 {total_vectors} 个特征向量")
    except Exception as e:
        print(f"⚠ 警告: Faiss索引加载失败: {e}")
        import traceback
        traceback.print_exc()

    # 预加载BGE模型
    print("正在预加载BGE向量化模型...")
    try:
        get_bge_model()
        print("✓ BGE向量化模型预加载完成")
    except Exception as e:
        print(f"⚠ BGE向量化模型预加载失败: {e}")

    yield
    
    # --- Shutdown ---
    print("正在关闭服务...")
    print("服务已关闭")

app = FastAPI(lifespan=lifespan)

# --- CORS 中间件 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册管理API路由
app.include_router(management_api.router)
app.include_router(dtc_api.router)
app.include_router(event_api.router)
app.include_router(auth_api.router)
app.include_router(llm_proxy_api.router)

# --- 批量导入相关常量与工具 ---
BULK_IMPORT_DEFAULT_DIR = Path(__file__).parent.parent / "data" / "local" / "img"
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_bulk_job_lock = threading.Lock()


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTS


def process_file_for_bulk_import(job_id: int, file_path: Path, threshold: float, project_root: Path, processed_files: set, qwen_key: str):
    """
    单个文件处理函数,用于并发执行
    返回: True 表示继续处理,False 表示应该停止任务（如遇到 critical error）
    """
    current_name = file_path.name
    
    # 每次处理前检查任务状态（虽然并发时不能完全实时停止,但可以尽早停止）
    job = get_bulk_import_job(job_id)
    if not job or job.get("status") in ("paused", "cancelled", "error", "completed"):
        return False
        
    # 跳过已处理文件
    if current_name in processed_files:
        return True
        
    # 更新任务状态为正在处理当前文件（并发时这个只会显示最后启动的一个,但至少有动静）
    # update_bulk_import_job_status(job_id, "running", current_file=current_name, last_error=None)
    
    # 提前生成 UUID,用于占位
    image_uuid = str(uuid.uuid4())
    
    try:
        # 计算直方图向量
        img = load_image_from_path(str(file_path))
        # 提取空间分块直方图向量
        spatial_vector = extract_spatial_histogram_vector(img)
        
        # 使用 Faiss LSH 检查相似度并尝试占位
        faiss_manager = get_faiss_index_manager()
        
        # 使用新增加的原子性检查与占位方法
        # 返回值: (是否相似, 相似度, 相似UUID, 匹配源['index'|'pending'])
        exists, max_similarity, similar_uuid, match_source = faiss_manager.check_similarity_and_reserve(
            spatial_vector, threshold, image_uuid
        )
        
        if max_similarity >= threshold:
            # 相似,跳过
            similar_file_name = None
            message_type = "skipped_similar"
            
            # 根据匹配源构建不同的提示信息
            if match_source == 'pending':
                # 匹配到了正在处理中的图片
                similar_file_name = "(正在AI分析中,尚未入库)"
                message = f"相似度 {max_similarity:.4f} >= 阈值 {threshold:.4f},与正在处理中的任务 (UUID: {similar_uuid}) 相似,跳过入库"
                # 注意：这里我们可能无法获取正在处理图片的原始文件名,除非我们在 pending_vectors 里存了文件名
                # 但这已经足够给前端提示了
                
            else:
                # 匹配到了已入库的图片
                if similar_uuid:
                    try:
                        from core.database import get_image_by_uuid
                        similar_img = get_image_by_uuid(similar_uuid)
                        if similar_img:
                            # 优先使用 fileName,如果没有则从 filePath 提取
                            similar_file_name = similar_img.get('fileName')
                            if not similar_file_name and similar_img.get('filePath'):
                                similar_file_name = Path(similar_img['filePath']).name
                            
                            message = f"相似度 {max_similarity:.4f} >= 阈值 {threshold:.4f},与已入库图片 {similar_file_name} 相似,跳过"
                        else:
                            # 数据库没查到,可能是数据不一致
                            similar_file_name = "未知图片(数据库缺失)"
                            message = f"相似度 {max_similarity:.4f} >= 阈值 {threshold:.4f},与已索引但未找到记录的图片相似,跳过"
                    except Exception as e:
                        print(f"获取相似图片信息时出错: {e}")
                        similar_file_name = "获取信息失败"
                        message = f"相似度 {max_similarity:.4f} >= 阈值 {threshold:.4f},与某张图片相似(获取详情失败),跳过"
                else:
                    message = f"相似度 {max_similarity:.4f} >= 阈值 {threshold:.4f},跳过入库"
            
            log_bulk_import(job_id, current_name, "skipped_similar", max_similarity, message, ai_json_data=None)
            update_bulk_import_progress(job_id, processed=1, skipped_similar=1, current_file=current_name)
            return True
        
        # 不相似,且已成功占位,进行AI分析
        
        try:
            relative_path = str(file_path.relative_to(project_root))
        except ValueError:
            relative_path = str(file_path.name)
        
        # 进行AI分析,生成keywords和向量（用于搜索）
        keywords = []
        description = ""
        qwen_captions = []
        yolo_objects = []
        keyword_embeddings = []
        
        try:
            # 读取图片并转换为base64 data URI
            with open(file_path, "rb") as f:
                image_bytes = f.read()
            import base64
            ext = file_path.suffix[1:] if file_path.suffix else "jpg"
            mime_type = f"image/{ext}" if ext in ["jpg", "jpeg", "png", "gif", "webp"] else "image/jpeg"
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            data_uri = f"data:{mime_type};base64,{image_base64}"
            
            # 使用concurrent.futures实现超时控制
            
            bulk_prompt = build_default_analysis_prompt()
            with ThreadPoolExecutor(max_workers=1) as api_executor:
                future = api_executor.submit(
                    lambda: infer_traffic_image("qwen", data_uri, bulk_prompt, allow_mock=True)[0]
                )
                try:
                    analysis_result = future.result(timeout=180.0)  # 3分钟超时
                except FutureTimeoutError:
                    raise Exception("AI分析超时（3分钟）")
            
            # 检查AI分析结果
            if not analysis_result:
                raise Exception("AI分析返回空结果")
            
            # 提取keywords
            if "semantic_search" in analysis_result:
                semantic_search = analysis_result["semantic_search"]
                keywords = semantic_search.get("keywords", [])
                description = semantic_search.get("description", "")
                qwen_captions = semantic_search.get("qwen_captions", [])
            
            if "training_data" in analysis_result:
                training_data = analysis_result["training_data"]
                yolo_objects = training_data.get("yolo_objects", [])
            
            # 检查是否有keywords,如果没有则入库失败
            if not keywords or len(keywords) == 0:
                raise Exception("AI分析结果中没有keywords,入库失败")
            
            # 生成keyword向量
            for keyword in keywords:
                try:
                    embedding_bytes = encode_text_to_vector(keyword)
                    keyword_embeddings.append((keyword, embedding_bytes))
                except Exception as e:
                    print(f"批量导入: 向量化keyword '{keyword}' 时出错: {e}")
                    # 向量化失败不影响入库,继续处理其他keyword
            
            if not keyword_embeddings:
                raise Exception("生成keyword向量失败,入库失败")
            
            # AI分析成功且有keywords,执行入库
            save_image_to_db(
                image_uuid=image_uuid,
                file_path=str(file_path),
                relative_path=relative_path,
                file_name=file_path.name,
                tags=keywords + yolo_objects,  # 所有标签
                keywords=keywords,
                description=description,
                qwen_captions=qwen_captions,
                yolo_objects=yolo_objects,
                keyword_embeddings=keyword_embeddings if keyword_embeddings else None
            )
            
            # 添加到 Faiss LSH 索引
            # 注意：add_vector 内部会检查是否已存在,但我们之前只是在pending里可以占位
            # 现在正式入库Faiss
            if faiss_manager.add_vector(image_uuid, spatial_vector):
                print(f"  ✓ 特征向量已添加到 Faiss LSH 索引: {current_name}")
            else:
                print(f"  ⚠ 警告: 特征向量添加到 Faiss 索引失败: {current_name}")
            
            # 入库成功后,从 pending 列表移除（因为已经正式入库了）
            faiss_manager.remove_pending_vector(image_uuid)
            
            # 记录成功日志,包含AI生成的JSON数据
            log_bulk_import(job_id, current_name, "success", None, "入库成功", ai_json_data=analysis_result)
            update_bulk_import_progress(job_id, processed=1, succeeded=1, current_file=current_name)
            return True

        except Exception as e:
            # 发生异常（如AI分析失败）,必须释放占位符
            faiss_manager = get_faiss_index_manager()
            faiss_manager.remove_pending_vector(image_uuid)
            
            # 检查是否是超时错误
            if "超时" in str(e) or "timeout" in str(e).lower() or "TimeoutError" in str(e):
                err_msg = f"AI分析超时（3分钟）: {current_name}"
            else:
                err_msg = f"AI分析失败或缺少keywords: {e}"
            log_bulk_import(job_id, current_name, "fail", None, err_msg, ai_json_data=None)
            update_bulk_import_progress(job_id, processed=1, failed=1, current_file=current_name)
            return True
    
    except Exception as e:
        # 最外层异常也要确保释放占位
        try:
             faiss_manager = get_faiss_index_manager() 
             faiss_manager.remove_pending_vector(image_uuid)
        except:
             pass
             
        err_msg = f"处理文件 {current_name} 失败: {e}"
        log_bulk_import(job_id, current_name, "fail", None, err_msg, ai_json_data=None)
        update_bulk_import_progress(job_id, processed=1, failed=1, current_file=current_name)
        traceback.print_exc()
        # 若出现特定错误（例如 API token 用尽）可中断
        if "token" in str(e).lower():
            update_bulk_import_job_status(job_id, "paused", current_file=current_name, last_error="API token 用尽,已暂停")
            return False
        return True


def run_bulk_import_job(job_id: int, directory: Path, threshold: float):
    """后台执行批量导入任务（并发版）"""
    project_root = Path(__file__).parent.parent.absolute()
    try:
        # 检查是否有正在运行的任务锁
        with _bulk_job_lock:
            update_bulk_import_job_status(job_id, "running", current_file=None, last_error=None)
        
        # 如果目录是相对路径,基于项目根目录解析
        if not directory.is_absolute():
            directory = project_root / directory
        abs_directory = directory.resolve()
        
        # 构建文件列表
        if not directory.exists():
            update_bulk_import_job_status(job_id, "error", last_error=f"目录不存在: {directory} (绝对路径: {abs_directory})")
            print(f"错误: 目录不存在 - 相对路径: {directory}, 绝对路径: {abs_directory}")
            return
        file_list = sorted([p for p in directory.rglob("*") if is_image_file(p)])
        update_bulk_import_total(job_id, len(file_list))
        
        # 已处理文件（断点续跑跳过）
        processed_files = get_bulk_import_processed_files(job_id)
        
        # 获取 Faiss 索引管理器（用于相似度检查）
        faiss_manager = get_faiss_index_manager()
        total_vectors = faiss_manager.get_total_vectors()
        print(f"Faiss索引中已有 {total_vectors} 张图片的特征向量，将用于相似度检查")
        
        # 获取 API Key
        qwen_key = os.getenv("QWEN_API_KEY")
        if not qwen_key :
             update_bulk_import_job_status(job_id, "error", last_error="未配置有效的 QWEN_API_KEY")
             return

        # 获取并发设置
        try:
            max_concurrent = int(os.getenv("CONCURRENT_REQUESTS", 8))
        except:
            max_concurrent = 4
        print(f"开始批量导入任务，并发数: {max_concurrent}")
        
        # 使用线程池并发处理
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # 提交所有任务
            future_to_file = {
                executor.submit(
                    process_file_for_bulk_import, 
                    job_id, file_path, threshold, project_root, processed_files, qwen_key
                ): file_path for file_path in file_list
            }
            
            # 处理完成的任务
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    should_continue = future.result()
                    if not should_continue:
                        # 如果需要停止（如暂停或严重错误），取消所有未执行的任务
                        print(f"任务中断信号收到，正在停止后续任务...")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                except Exception as e:
                    print(f"处理文件 {file_path.name} 时发生未捕获异常: {e}")
        
        # 检查最终状态
        final_job = get_bulk_import_job(job_id)
        if final_job and final_job.get("status") not in ("paused", "cancelled", "error"):
            update_bulk_import_job_status(job_id, "completed", current_file=None, last_error=None)
    except Exception as e:
        traceback.print_exc()
        update_bulk_import_job_status(job_id, "error", last_error=str(e))

def test_qwen_connection():
    """主后端启动时检查独立 LLM 网关是否可达。"""
    if check_gateway_health():
        print(f">> LLM 网关可用: {LLM_GATEWAY_URL}")
    else:
        print(f">> 警告: LLM 网关不可用 ({LLM_GATEWAY_URL})，图片分析/补标签将失败")
        print(">> 请启动: systemctl start taglens-llm-gateway 或 ./start_llm_gateway.sh")


# --- API 路由 ---
def _check_image_similarity_sync(request: ImageSimilarityCheckRequest) -> ImageSimilarityCheckResponse:
    """同步：Faiss 相似度检查（在线程池中执行）"""
    try:
        # 提取上传图片的空间分块直方图向量
        uploaded_img = decode_base64_image(request.image)
        query_vector = extract_spatial_histogram_vector(uploaded_img)
        
        # 获取 Faiss 索引管理器
        faiss_manager = get_faiss_index_manager()
        
        # 检查索引中是否有向量
        total_vectors = faiss_manager.get_total_vectors()
        if total_vectors == 0:
            return ImageSimilarityCheckResponse(
                is_similar=False,
                max_similarity=0.0,
                similar_images=[],
                message="索引中暂无图片，可以进行分析"
            )
        
        # 设置阈值
        threshold = request.threshold or 0.7409
        
        # 使用 Faiss LSH 快速检查是否存在相似图片（只找最相似的1个）
        exists, max_similarity, similar_uuid = faiss_manager.check_similarity_exists(query_vector, threshold)
        
        first_similar_image = None
        
        if exists and similar_uuid:
            
            # 从数据库获取图片详细信息
            from core.database import get_image_by_uuid
            db_img = get_image_by_uuid(similar_uuid)
            
            if db_img:
                # 从 MinIO 读取该图片的base64数据
                image_data_uri = None
                # get_image_by_uuid 返回的字典使用 'file_path' 作为键（映射到数据库的 relative_path 字段）
                img_path = db_img.get('file_path')
                
                if img_path:
                    try:
                        storage_client = get_storage_client(skip_bucket_check=True)
                        image_bytes = storage_client.download_file_data(img_path)
                        
                        # 根据文件扩展名确定MIME类型
                        ext = Path(img_path).suffix.lower()
                        mime_type = {
                            '.jpg': 'image/jpeg',
                            '.jpeg': 'image/jpeg',
                            '.png': 'image/png',
                            '.gif': 'image/gif',
                            '.webp': 'image/webp',
                            '.bmp': 'image/bmp'
                        }.get(ext, 'image/jpeg')
                        
                        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                        image_data_uri = f"data:{mime_type};base64,{image_base64}"
                    except Exception as e:
                        print(f"从 MinIO 读取相似图片 {similar_uuid} 时出错: {e}")
                        image_data_uri = None
                
                first_similar_image = {
                    'uuid': similar_uuid,
                    'filePath': db_img.get('filePath', ''),
                    'fileName': db_img.get('fileName'),
                    'createdAt': db_img.get('createdAt', ''),
                    'similarity': float(max_similarity),
                    'methods': {
                        'faiss_lsh': {
                            'similarity': float(max_similarity),
                            'method': 'LSH'
                        },
                        'overall_similarity': float(max_similarity),
                        'max_similarity': float(max_similarity),
                        'min_similarity': float(max_similarity)
                    },
                    'imageData': image_data_uri
                }
        
        # 判断是否找到相似图片
        is_similar = first_similar_image is not None
        
        # 转换为响应格式
        similar_images = []
        if first_similar_image:
            similar_images.append(
                SimilarImageResult(
                    uuid=first_similar_image['uuid'],
                    filePath=first_similar_image['filePath'],
                    fileName=first_similar_image['fileName'],
                    createdAt=first_similar_image['createdAt'],
                    similarity=first_similar_image['similarity'],
                    methods=first_similar_image['methods'],
                    imageData=first_similar_image['imageData']
                )
            )
        
        if is_similar:
            message = f"检测到相似图片（相似度: {max_similarity:.2%}），建议不调用大模型API以避免重复分析"
        else:
            message = f"未发现相似图片（最高相似度: {max_similarity:.2%}），可以进行分析"
        
        return ImageSimilarityCheckResponse(
            is_similar=is_similar,
            max_similarity=float(max_similarity),
            similar_images=similar_images,
            message=message
        )
        
    except Exception as e:
        print(f"检查图片相似度时出错: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"检查图片相似度失败: {str(e)}")


@app.post("/check-similarity", response_model=ImageSimilarityCheckResponse)
async def check_image_similarity(request: ImageSimilarityCheckRequest):
    """
    检查上传的图片是否与数据库中的图片相似（使用 Faiss LSH）
    如果相似度超过阈值，返回相似图片列表，建议不调用大模型API
    """
    return await run_blocking(_check_image_similarity_sync, request)


# --- 批量导入 API ---
@app.post("/bulk-import/create", response_model=BulkImportStatusResponse)
async def create_bulk_import_job_api(request: BulkImportStartRequest, background_tasks: BackgroundTasks):
    """创建新的批量导入任务并自动开始"""
    try:
        directory = request.directory if request.directory else "./data/local/img"
        threshold = request.threshold or 0.7409
        
        job = create_bulk_import_job(threshold=threshold, directory=directory)
        job_id = job.get('id')
        if not job_id:
            raise HTTPException(status_code=500, detail="创建任务失败，无法获取任务ID")
        
        # 自动开始导入
        directory_path = Path(directory)
        background_tasks.add_task(run_bulk_import_job, job_id, directory_path, threshold)
        
        return BulkImportStatusResponse(success=True, job=job)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@app.post("/bulk-import/resume", response_model=BulkImportStatusResponse)
async def resume_bulk_import(request: BulkImportActionRequest, background_tasks: BackgroundTasks):
    job_id = request.job_id
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id 不能为空")
    job = get_bulk_import_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("status") not in ("paused", "error", "completed"):
        raise HTTPException(status_code=400, detail=f"当前状态不可续传: {job.get('status')}")
    
    # 检查是否已有运行任务
    active_job = get_active_bulk_import_job()
    if active_job and active_job.get("id") != job_id:
        raise HTTPException(status_code=400, detail="已有其他任务在运行，请先暂停/取消/删除")
    
    # 设置为 pending 再拉起
    update_bulk_import_job_status(job_id, "pending", current_file=None, last_error=None)
    directory = Path(job.get("directory") or BULK_IMPORT_DEFAULT_DIR)
    threshold = job.get("threshold") or 0.7409
    background_tasks.add_task(run_bulk_import_job, job_id, directory, threshold)
    return BulkImportStatusResponse(success=True, job=get_bulk_import_job(job_id))


@app.post("/bulk-import/pause", response_model=BulkImportStatusResponse)
async def pause_bulk_import(request: BulkImportActionRequest):
    job_id = request.job_id
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id 不能为空")
    job = get_bulk_import_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    update_bulk_import_job_status(job_id, "paused")
    return BulkImportStatusResponse(success=True, job=get_bulk_import_job(job_id))


@app.post("/bulk-import/cancel", response_model=BulkImportStatusResponse)
async def cancel_bulk_import(request: BulkImportActionRequest):
    job_id = request.job_id
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id 不能为空")
    job = get_bulk_import_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    update_bulk_import_job_status(job_id, "cancelled")
    return BulkImportStatusResponse(success=True, job=get_bulk_import_job(job_id))


@app.post("/bulk-import/delete", response_model=BulkImportStatusResponse)
async def delete_bulk_import(request: BulkImportActionRequest):
    job_id = request.job_id
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id 不能为空")
    job = get_bulk_import_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    delete_bulk_import_job_and_logs(job_id)
    return BulkImportStatusResponse(success=True, job=None)


@app.get("/bulk-import/status", response_model=BulkImportStatusResponse)
async def bulk_import_status(job_id: Optional[int] = Query(None)):
    job = None
    if job_id:
        job = get_bulk_import_job(job_id)
    else:
        job = get_active_bulk_import_job()
    return BulkImportStatusResponse(success=True, job=job)


@app.get("/bulk-import/jobs", response_model=BulkImportJobsResponse)
async def get_all_bulk_import_jobs_api():
    """获取所有批量导入任务"""
    try:
        jobs = get_all_bulk_import_jobs()
        return BulkImportJobsResponse(success=True, jobs=jobs)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")


@app.get("/bulk-import/logs", response_model=BulkImportLogsResponse)
async def bulk_import_logs(
    job_id: int = Query(...),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=1000),
    status: Optional[str] = Query(None)
):
    logs, total = get_bulk_import_logs(job_id, page=page, page_size=page_size, status_filter=status)
    return BulkImportLogsResponse(success=True, logs=logs, total=total)


@app.get("/")
def read_root():
    return {"message": "欢迎使用 TagLens AI 后端服务 (Qwen-Powered)"}


@app.get("/health")
def health_check():
    return {"status": "ok"}

def extract_image_format_from_data_uri(data_uri: str) -> tuple[str, bytes]:
    """
    从 data URI 中提取图片格式和二进制数据
    返回: (格式扩展名, 图片二进制数据)
    例如: ("jpg", b"...")
    """
    # data URI 格式: data:image/jpeg;base64,/9j/4AAQSkZJRg...
    if not data_uri.startswith("data:image/"):
        raise ValueError("无效的图片 data URI 格式")
    
    # 提取 MIME 类型
    mime_type = data_uri.split(";")[0].split(":")[1]  # image/jpeg
    
    # 映射 MIME 类型到文件扩展名
    mime_to_ext = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/bmp": "bmp",
    }
    
    ext = mime_to_ext.get(mime_type, "jpg")  # 默认使用 jpg
    
    # 提取 base64 数据
    base64_data = data_uri.split(",")[1]
    image_bytes = base64.b64decode(base64_data)
    
    return ext, image_bytes

def _save_image_sync(request: SaveImageRequest) -> SaveImageResponse:
    """同步：保存图片（在线程池中执行）"""
    try:
        # 获取当前日期 (YYYY-MM-DD)
        date_str = datetime.now().strftime("%Y-%m-%d")
        
        # 生成 UUID
        image_uuid = str(uuid.uuid4())
        
        # 从 data URI 提取图片格式和数据
        ext, image_bytes = extract_image_format_from_data_uri(request.image)
        
        # 构建 MinIO 对象路径
        filename = f"{image_uuid}.{ext}"
        minio_object_path = f"project_data/default/{date_str}/{filename}"
        storage_client = get_storage_client(skip_bucket_check=True)
        
        # 确定内容类型
        content_type_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'bmp': 'image/bmp'
        }
        content_type = content_type_map.get(ext.lower(), 'image/jpeg')
        storage_client.upload_file_data(image_bytes, minio_object_path, content_type)
        
        # MinIO 路径作为相对路径存储到数据库
        relative_path = minio_object_path
        
        # 对每个keyword分别进行向量化
        keyword_embeddings = []
        if request.keywords and len(request.keywords) > 0:
            for keyword in request.keywords:
                try:
                    embedding_bytes = encode_text_to_vector(keyword)
                    keyword_embeddings.append((keyword, embedding_bytes))
                except Exception:
                    pass
        
        # 计算空间分块直方图向量并保存到 Faiss LSH
        spatial_vector = None
        try:
            uploaded_img = decode_base64_image(request.image)
            spatial_vector = extract_spatial_histogram_vector(uploaded_img)
            
            # 添加到 Faiss LSH 索引
            faiss_manager = get_faiss_index_manager()
            if faiss_manager.add_vector(image_uuid, spatial_vector):
                faiss_manager.save_index()
        except Exception as e:
            # 即使特征向量计算失败，也继续保存图片，但打印错误日志
            print(f"⚠ [save-image] 计算特征向量或添加到Faiss失败: {e}")
            import traceback
            traceback.print_exc()
            pass
        
        # 保存到数据库
        all_tags = list(set(request.tags + request.keywords + request.yoloObjects))
        image_id = save_image_to_db(
            image_uuid=image_uuid,
            file_path=relative_path,  # MinIO 路径
            relative_path=relative_path,  # MinIO 路径
            file_name=request.fileName,
            tags=all_tags,  # 所有标签，用于搜索
            keywords=request.keywords,
            description=request.description,
            qwen_captions=request.qwenCaptions,
            yolo_objects=request.yoloObjects,
            keyword_embeddings=keyword_embeddings if keyword_embeddings else None
        )
        # 构建 AI 分析结果的 JSON 数据
        ai_analysis_json = {
            "semantic_search": {
                "description": request.description,
                "keywords": request.keywords
            },
            "training_data": {
                "qwen_captions": request.qwenCaptions,
                "yolo_objects": request.yoloObjects
            },
            "metadata": {
                "uuid": image_uuid,
                "file_name": request.fileName,
                "created_at": datetime.now().isoformat(),
                "image_path": minio_object_path
            }
        }
        
        # 将 JSON 数据上传到 MinIO（和图片在同一路径下，文件名加 tag_ 前缀）
        json_filename = f"tag_{image_uuid}.json"
        json_object_path = f"project_data/default/{date_str}/{json_filename}"
        json_bytes = json.dumps(ai_analysis_json, ensure_ascii=False, indent=2).encode('utf-8')
        storage_client.upload_file_data(json_bytes, json_object_path, 'application/json')
        
        return SaveImageResponse(
            success=True,
            uuid=image_uuid,
            file_path=relative_path,  # MinIO 路径
            relative_path=relative_path,  # MinIO 路径
            message="图片保存成功"
        )
        
    except Exception as e:
        print(f"[save-image] 保存图片时发生错误: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"保存图片失败: {str(e)}")


@app.post("/save-image", response_model=SaveImageResponse)
async def save_image(request: SaveImageRequest):
    """保存图片到 MinIO 和数据库"""
    return await run_blocking(_save_image_sync, request)


# --- 搜索 API ---
def _search_images_sync(
    request: SearchRequest,
    progress_callback: Optional[SearchProgressCallback] = None,
    cancellation: Optional[SearchCancellation] = None,
) -> SearchResponse:
    """同步：向量搜索（在线程池中执行）"""
    progress = SearchProgress(progress_callback, cancellation)
    print("=" * 60)
    print("收到搜索请求!")
    
    # 确定查询列表和权重（优先使用tags，否则使用queries，最后使用query）
    tags_with_weights = []
    if request.tags and len(request.tags) > 0:
        # 使用新的tags格式（带权重）
        tags_with_weights = [(tag.tag.strip(), tag.weight) for tag in request.tags if tag.tag.strip()]
        # 验证权重之和是否为1
        total_weight = sum(weight for _, weight in tags_with_weights)
        if abs(total_weight - 1.0) > 0.001:
            raise HTTPException(
                status_code=400,
                detail=f"所有标签的权重之和必须等于1，当前为 {total_weight:.3f}"
            )
    elif request.queries and len(request.queries) > 0:
        # 向后兼容：使用queries，平均分配权重
        queries = [q.strip() for q in request.queries if q.strip()]
        weight_per_tag = 1.0 / len(queries) if queries else 0
        tags_with_weights = [(q, weight_per_tag) for q in queries]
    elif request.query and request.query.strip():
        # 向后兼容：使用单个query，权重为1
        tags_with_weights = [(request.query.strip(), 1.0)]
    
    queries = [tag for tag, _ in tags_with_weights]
    weights = [weight for _, weight in tags_with_weights]
    
    print(f"请求内容: tags={tags_with_weights}, threshold={request.similarityThreshold}, limit={request.limit}")
    print("=" * 60)
    try:
        progress.report("encode", 1, "正在准备搜索…")
        # 对每个查询标签进行向量化
        query_embeddings = []
        if queries:
            try:
                for idx, query in enumerate(queries):
                    progress.check_cancelled()
                    progress.report(
                        "encode",
                        2 + (idx / max(len(queries), 1)) * 8,
                        f"正在向量化标签「{query}」…",
                    )
                    embedding = encode_text_to_vector(query)
                    query_embeddings.append(embedding)
                    print(f"已生成查询向量: '{query}' (维度: {len(embedding) // 4})")
                progress.report("encode", 10, "查询标签向量化完成")
            except SearchCancelledError:
                raise
            except Exception as e:
                print(f"向量化查询文本时出错: {e}")
                import traceback
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"向量化查询文本失败: {str(e)}")
        else:
            # 如果查询为空，返回所有图片（不使用向量搜索）
            print("查询关键词为空，将依赖时间范围或返回最新图片。")
        
        # 验证相似度阈值
        similarity_threshold = request.similarityThreshold or 0.6
        if not 0 <= similarity_threshold <= 1:
            similarity_threshold = 0.6
        
        # 确定分页参数
        page = request.page or 1
        page_size = request.pageSize or 20
        
        # 如果没有指定分页参数，使用limit（向后兼容）
        use_limit = request.limit if request.page is None and request.pageSize is None else None
        
        print(f"搜索参数: tags={tags_with_weights}, threshold={similarity_threshold}, page={page}, pageSize={page_size}, limit={use_limit}")
        
        results, total_count = search_images(
            query=queries[0] if queries else '',  # 向后兼容，传递第一个查询
            limit=use_limit if use_limit else 10000,  # 如果使用分页，limit设为较大值以获取所有结果用于分页
            start_date=request.startDate,
            end_date=request.endDate,
            camera_name=request.cameraName,
            biz_category=request.bizCategory,
            file_path=request.filePath,
            description_keywords=request.descriptionKeywords,
            query_embeddings=query_embeddings if query_embeddings else None,  # 传递多个向量
            query_tags=queries if queries else None,
            query_weights=weights if weights else None,  # 传递权重列表
            similarity_threshold=similarity_threshold,
            page=page if use_limit is None else None,  # 如果使用limit，则不使用分页
            page_size=page_size if use_limit is None else None,
            on_progress=progress,
        )
        
        print(f"搜索结果数量: {len(results)}, 总数: {total_count}")
        
        # 调试：打印第一个结果的键
        if results and len(results) > 0:
            print(f"第一个结果的键: {list(results[0].keys())}")
            print(f"第一个结果的similarity值: {results[0].get('similarity')}")
        
        # 转换为响应模型
        image_results = []
        for r in results:
            similarity_value = r.get('similarity')
            print(f"处理结果 ID={r.get('id')}, similarity={similarity_value}")
            image_results.append(
                ImageSearchResult(
                    id=r['id'],
                    uuid=r['uuid'],
                    filePath=r['filePath'],
                    fileName=r['fileName'],
                    createdAt=r['createdAt'],
                    description=r['description'],
                    keywords=r['keywords'],
                    tags=r['tags'],

                    qwenCaptions=r['qwenCaptions'],
                    yoloObjects=r['yoloObjects'],
                    szName=r.get('szName'),
                    szTagRefs=r.get('szTagRefs') or [],
                    similarity=similarity_value  # 添加相似度字段
                )
            )
        
        return SearchResponse(
            success=True,
            results=image_results,
            total=total_count  # 返回总数，而不是当前页的数量
        )
    except SearchCancelledError:
        print("搜索已被用户取消")
        raise
    except HTTPException as e:
        print(f"搜索图片时发生HTTP异常: {e}")
        raise e
    except Exception as e:
        from services.keyword_search_cache import KeywordCacheNotLoadedError

        if isinstance(e, KeywordCacheNotLoadedError):
            raise HTTPException(status_code=400, detail=str(e))
        print(f"搜索图片时发生错误: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@app.post("/search", response_model=SearchResponse)
async def search_images_api(request: SearchRequest):
    return await run_blocking(_search_images_sync, request)


@app.post("/search/stream")
async def search_images_stream_api(request: SearchRequest, http_request: Request):
    """流式搜索：NDJSON 推送进度，最后一行 type=result 为完整搜索结果。"""
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    cancellation = SearchCancellation()

    def progress_callback(event: dict) -> None:
        if cancellation.is_cancelled():
            return
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def worker() -> None:
        try:
            result = await run_blocking(
                _search_images_sync,
                request,
                progress_callback,
                cancellation,
            )
            if cancellation.is_cancelled():
                return
            await queue.put({"type": "result", **result.model_dump()})
        except SearchCancelledError:
            print("[search/stream] 客户端中断搜索")
        except HTTPException as exc:
            if not cancellation.is_cancelled():
                await queue.put({"type": "error", "message": exc.detail, "status": exc.status_code})
        except Exception as exc:
            if not cancellation.is_cancelled():
                await queue.put({"type": "error", "message": str(exc), "status": 500})
        finally:
            await queue.put(None)

    worker_task = asyncio.create_task(worker())

    async def generate():
        try:
            while True:
                if await http_request.is_disconnected():
                    cancellation.cancel()
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if item is None:
                    break
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            cancellation.cancel()
            if not worker_task.done():
                worker_task.cancel()

    return StreamingResponse(generate(), media_type="application/x-ndjson")


def _load_keyword_cache_sync(
    reload: bool,
    progress_callback: Optional[SearchProgressCallback] = None,
    cancellation: Optional[SearchCancellation] = None,
) -> Dict[str, Any]:
    from services.keyword_search_cache import (
        KeywordCacheAlreadyLoadedError,
        KeywordCacheLoadingError,
        get_keyword_cache_status,
        load_keyword_vectors,
    )

    progress = SearchProgress(progress_callback, cancellation)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        count = load_keyword_vectors(cursor, force_reload=reload, progress=progress)
    status = get_keyword_cache_status()
    return {"success": True, "keywordCount": count, **status}


@app.get("/keyword-cache/status")
async def keyword_cache_status_api():
    from services.keyword_search_cache import get_keyword_cache_status

    return get_keyword_cache_status()


@app.post("/keyword-cache/release")
async def keyword_cache_release_api():
    from services.keyword_search_cache import KeywordCacheLoadingError, get_keyword_cache_status, release_keyword_cache

    try:
        return release_keyword_cache()
    except KeywordCacheLoadingError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/keyword-cache/load/stream")
async def keyword_cache_load_stream_api(request: KeywordCacheLoadRequest, http_request: Request):
    """流式加载/重载标签向量库。"""
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    cancellation = SearchCancellation()

    def progress_callback(event: dict) -> None:
        if cancellation.is_cancelled():
            return
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def worker() -> None:
        from services.keyword_search_cache import (
            KeywordCacheAlreadyLoadedError,
            KeywordCacheLoadingError,
        )

        try:
            result = await run_blocking(
                _load_keyword_cache_sync,
                request.reload,
                progress_callback,
                cancellation,
            )
            if cancellation.is_cancelled():
                return
            await queue.put({"type": "result", **result})
        except SearchCancelledError:
            print("[keyword-cache/load/stream] 客户端中断加载")
        except KeywordCacheAlreadyLoadedError as exc:
            if not cancellation.is_cancelled():
                await queue.put({"type": "error", "message": str(exc), "status": 409})
        except KeywordCacheLoadingError as exc:
            if not cancellation.is_cancelled():
                await queue.put({"type": "error", "message": str(exc), "status": 409})
        except Exception as exc:
            if not cancellation.is_cancelled():
                await queue.put({"type": "error", "message": str(exc), "status": 500})
        finally:
            await queue.put(None)

    worker_task = asyncio.create_task(worker())

    async def generate():
        try:
            while True:
                if await http_request.is_disconnected():
                    cancellation.cancel()
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if item is None:
                    break
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            cancellation.cancel()
            if not worker_task.done():
                worker_task.cancel()

    return StreamingResponse(generate(), media_type="application/x-ndjson")


def _export_search_images_sync(
    request: ExportImagesRequest,
    progress_callback: Optional[SearchProgressCallback] = None,
    cancellation: Optional[SearchCancellation] = None,
) -> Dict[str, Any]:
    progress = SearchProgress(progress_callback, cancellation)

    if request.items:
        items = [
            {
                "filePath": item.filePath,
                "uuid": item.uuid,
                "fileName": item.fileName,
            }
            for item in request.items
            if item.filePath
        ]
        progress.report("prepare", 5, f"共 {len(items)} 张图片待下载（跳过重复搜索）…")
    else:
        progress.report("search", 1, "正在获取全部搜索结果…")
        search_request = SearchRequest(
            tags=request.tags,
            query=request.query,
            queries=request.queries,
            similarityThreshold=request.similarityThreshold,
            startDate=request.startDate,
            endDate=request.endDate,
            cameraName=request.cameraName,
            bizCategory=request.bizCategory,
            page=1,
            pageSize=10000,
        )
        search_result = _search_images_sync(
            search_request,
            progress_callback=progress_callback,
            cancellation=cancellation,
        )
        items = [
            {
                "filePath": r.filePath,
                "uuid": r.uuid,
                "fileName": r.fileName,
            }
            for r in search_result.results
        ]
        progress.report("search", 5, f"共 {len(items)} 张图片待下载…")

    export_info = export_search_images_zip(items, progress=progress)
    return {
        "success": True,
        "fileName": export_info["fileName"],
        "downloadPath": f"/search/export-images/file/{export_info['fileName']}",
        "total": export_info["total"],
        "downloaded": export_info["downloaded"],
        "failed": export_info["failed"],
        "errors": export_info.get("errors") or [],
    }


@app.post("/search/export-images/stream")
async def export_search_images_stream_api(request: ExportImagesRequest, http_request: Request):
    """流式导出搜索结果图片为 zip（经 bucket-taglens HTTP 地址下载）。"""
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    cancellation = SearchCancellation()

    def progress_callback(event: dict) -> None:
        if cancellation.is_cancelled():
            return
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def worker() -> None:
        try:
            result = await run_blocking(
                _export_search_images_sync,
                request,
                progress_callback,
                cancellation,
            )
            if cancellation.is_cancelled():
                return
            await queue.put({"type": "result", **result})
        except SearchCancelledError:
            print("[search/export-images/stream] 客户端中断导出")
        except HTTPException as exc:
            if not cancellation.is_cancelled():
                await queue.put({"type": "error", "message": exc.detail, "status": exc.status_code})
        except Exception as exc:
            if not cancellation.is_cancelled():
                await queue.put({"type": "error", "message": str(exc), "status": 500})
        finally:
            await queue.put(None)

    worker_task = asyncio.create_task(worker())

    async def generate():
        try:
            while True:
                if await http_request.is_disconnected():
                    cancellation.cancel()
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if item is None:
                    break
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            cancellation.cancel()
            if not worker_task.done():
                worker_task.cancel()

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/search/export-images/file/{filename}")
async def download_search_export_zip(filename: str):
    zip_path = resolve_export_zip_path(filename)
    if not zip_path:
        raise HTTPException(status_code=404, detail="压缩包不存在或文件名无效")
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=filename,
    )


def _get_all_images_sync(limit: int) -> SearchResponse:
    results = get_all_images(limit)
    image_results = [
        ImageSearchResult(
            id=r['id'],
            uuid=r['uuid'],
            filePath=r['filePath'],
            fileName=r['fileName'],
            createdAt=r['createdAt'],
            description=r['description'],
            keywords=r['keywords'],
            tags=r['tags'],
            qwenCaptions=r['qwenCaptions'],
            yoloObjects=r['yoloObjects'],
        )
        for r in results
    ]
    return SearchResponse(
        success=True,
        results=image_results,
        total=len(image_results),
    )


@app.get("/images", response_model=SearchResponse)
async def get_all_images_api(limit: int = Query(100, ge=1, le=1000)):
    try:
        return await run_blocking(_get_all_images_sync, limit)
    except Exception as e:
        print(f"获取图片列表时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"获取图片列表失败: {str(e)}")


def _delete_image_sync(image_uuid: str) -> Dict[str, Any]:
    api_start = time.time()
    print(f"[images/delete] start uuid={image_uuid}")
    db_start = time.time()
    deleted = delete_image_by_uuid(image_uuid)
    print(f"[images/delete] db delete finished cost={time.time()-db_start:.3f}s deleted={deleted}")
    if not deleted:
        raise HTTPException(status_code=404, detail="图片记录不存在")
    try:
        faiss_start = time.time()
        faiss_manager = get_faiss_index_manager()
        removed = faiss_manager.remove_vector(image_uuid)
        print(f"[images/delete] faiss remove finished removed={removed} cost={time.time()-faiss_start:.3f}s")
    except Exception as faiss_exc:
        print(f"删除 Faiss 向量失败 uuid={image_uuid}: {faiss_exc}")
    print(f"[images/delete] done uuid={image_uuid} total_cost={time.time()-api_start:.3f}s")
    return {"success": True, "uuid": image_uuid}


@app.post("/images/delete")
async def delete_image_api(request: DeleteImageRequest):
    """删除标签查询图片：数据库关联记录 + Faiss 向量。"""
    image_uuid = (request.uuid or "").strip()
    if not image_uuid:
        raise HTTPException(status_code=400, detail="uuid 不能为空")
    try:
        return await run_blocking(_delete_image_sync, image_uuid)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除图片失败: {str(e)}")

# --- 直接读取文件系统图片接口 ---
def _get_image_direct_sync(path: str) -> Response:
    """同步：从本地 MinIO 数据目录读图"""
    # MinIO 数据目录的常见路径
    possible_dirs = [
        "/var/lib/minio/data",
        "/data/minio/data",
        "/opt/minio/data",
        "/usr/local/minio/data",
        "/root/minio/data",
    ]
    
    # MinIO bucket 名称
    bucket_name = "bucket-taglens"
    
    # 尝试从文件系统直接读取
    file_path = None
    tried_paths = []
    for data_dir in possible_dirs:
        full_path = Path(data_dir) / bucket_name / path
        tried_paths.append(str(full_path))
        if full_path.exists() and full_path.is_file():
            file_path = full_path
            break
    
    if not file_path:
        # 如果文件系统找不到，直接返回错误，不回退到 MinIO 客户端
        error_msg = f"图片文件不存在。尝试的路径：{', '.join(tried_paths)}"
        print(f"[警告] {error_msg}")
        raise HTTPException(status_code=404, detail=error_msg)
    
    try:
        # 从文件系统读取
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        # 获取 Content-Type
        ext = file_path.suffix.lower()
        content_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp',
        }
        content_type = content_type_map.get(ext, 'image/jpeg')
        
        return Response(
            content=file_data,
            media_type=content_type,
            headers={"Content-Disposition": f'inline; filename="{file_path.name}"'}
        )
    except Exception as e:
        error_msg = f"读取图片文件失败: {str(e)}，文件路径: {file_path}"
        print(f"[警告] {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/api/images/direct")
async def get_image_direct(
    path: str = Query(..., description="图片路径（MinIO 对象路径）"),
):
    return await run_blocking(_get_image_direct_sync, path)


def _download_image_sync(object_name: str) -> Response:
    storage_client = get_storage_client(skip_bucket_check=True)
    if not storage_client.file_exists(object_name):
        raise HTTPException(status_code=404, detail="图片不存在")
    file_data = storage_client.download_file_data(object_name)
    filename = os.path.basename(object_name)
    content_type, _ = mimetypes.guess_type(object_name)
    if content_type is None or not content_type.startswith("image/"):
        content_type = "image/jpeg"
    return Response(
        content=file_data,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# --- MinIO 图片下载接口 ---
@app.get("/api/minio/download/image")
async def download_image_api(
    object_name: str = Query(..., description="MinIO 中的对象名称（路径）"),
):
    """从 MinIO 下载图片"""
    try:
        return await run_blocking(_download_image_sync, object_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


# --- MinIO 通用文件下载接口（图片/视频等） ---
@app.get("/api/minio/download/file")
async def download_file_api(
    request: Request,
    object_name: str = Query(..., description="MinIO 中的对象名称（路径）")
):
    """从 MinIO 下载任意文件（用于视频、图片等资源直链）"""
    try:
        storage_client = get_storage_client(skip_bucket_check=True)
        if not storage_client.file_exists(object_name):
            raise HTTPException(status_code=404, detail="文件不存在")

        stat = storage_client.client.stat_object(storage_client.bucket, object_name)
        total_size = int(getattr(stat, "size", 0) or 0)
        range_header = request.headers.get("range")

        # 默认返回整个文件；若客户端传了 Range，则返回 206 分段内容
        offset = 0
        length: Optional[int] = None
        status_code = 200
        content_range = None
        if range_header and range_header.startswith("bytes=") and total_size > 0:
            byte_range = range_header[len("bytes="):].strip()
            start_str, _, end_str = byte_range.partition("-")
            if start_str.isdigit():
                start = int(start_str)
                if start >= total_size:
                    raise HTTPException(status_code=416, detail="Range Not Satisfiable")
                end = total_size - 1
                if end_str.isdigit():
                    end = min(int(end_str), total_size - 1)
                if end < start:
                    raise HTTPException(status_code=416, detail="Range Not Satisfiable")
                offset = start
                length = end - start + 1
                status_code = 206
                content_range = f"bytes {start}-{end}/{total_size}"

        response_obj = storage_client.client.get_object(
            storage_client.bucket,
            object_name,
            offset=offset,
            length=length,
        )
        file_data = response_obj.read()
        response_obj.close()
        response_obj.release_conn()
        filename = os.path.basename(object_name)
        content_type, _ = mimetypes.guess_type(object_name)
        if content_type is None:
            content_type = "application/octet-stream"

        headers = {
            "Content-Disposition": f'inline; filename="{filename}"',
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(file_data)),
        }
        if content_range:
            headers["Content-Range"] = content_range

        return Response(
            content=file_data,
            media_type=content_type,
            headers=headers,
            status_code=status_code,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


# --- 图片上传处理接口 (Project Sync用) ---
def _process_uploaded_image_sync(
    image_bytes: bytes,
    file_name: Optional[str],
    content_type: str,
    project_name: str,
    timestamp: Optional[str],
    camera_id: Optional[str],
    sz_name: Optional[str],
    threshold: float,
) -> Dict[str, Any]:
    """同步：项目同步上传处理（在线程池中执行，含 AI 调用）"""
    ai_error_message: Optional[str] = None
    temp_uuid = str(uuid.uuid4())
    try:
        # 将 image_bytes 转为 PIL Image 以计算特征向量
        from io import BytesIO
        from PIL import Image
        try:
            pil_image = Image.open(BytesIO(image_bytes))
            # 兼容性处理：转换为RGB
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
        except Exception as e:
            return {"status": "error", "message": f"无效的图片文件: {e}"}

        # 2. 计算特征向量并去重
        spatial_vector = extract_spatial_histogram_vector(pil_image)
        
        faiss_manager = get_faiss_index_manager()
        
        # 原子性检查与占位
        exists, max_similarity, similar_uuid, match_source = faiss_manager.check_similarity_and_reserve(
            spatial_vector, threshold, temp_uuid
        )
        
        if max_similarity >= threshold:
            # 发现重复，跳过
            faiss_manager.remove_pending_vector(temp_uuid) # 释放占位 (其实check_similarity_and_reserve在重复时不会占位，但为了安全调用一下无妨，或者检查exists)
             # check_similarity_and_reserve implementation: if similar, it returns True and DOES NOT add to pending.
             # So we don't need to remove.
            
            return {
                "status": "skipped",
                "reason": "duplicate",
                "similarity": float(max_similarity),
                "similar_to": similar_uuid,
                "message": f"图片与 {similar_uuid} 高度相似 ({max_similarity:.4f})，已跳过"
            }


        # 3. 没重复，开始处理
        # 3.1 上传到 MinIO
        storage_client = get_storage_client()
        # 构建 MinIO 路径: project_data/{project_name}/{date}/{filename}
        date_str = datetime.now().strftime("%Y-%m-%d")
        minio_path = f"project_data/{project_name}/{date_str}/{file_name}" # 使用原始文件名，可能需要在后端加UUID前缀避免同名覆盖，这里暂且相信文件名唯一或直接使用
        # 建议加 UUID 前缀确保唯一性
        final_file_name = f"{temp_uuid}_{file_name}"
        minio_path = f"project_data/{project_name}/{date_str}/{final_file_name}"

        storage_client.upload_file_data(image_bytes, minio_path, content_type)

        # 3.2 AI 分析 preparation
        import base64
        import random
        
        base64_str = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = content_type or "image/jpeg"
        data_uri = f"data:{mime_type};base64,{base64_str}"
        
        # 确定使用的模型和概率
        projects = get_all_projects_db()
        target_project = next((p for p in projects if p['name'] == project_name), None)
        
        use_model = 'gemini'
        api_prob = 1.0
        
        if target_project:
             use_model = target_project.get('ai_model', 'gemini')
             api_prob = target_project.get('api_probability', 1.0)
             if api_prob is None: api_prob = 1.0
        
        should_call_api = random.random() < api_prob
        
        analysis_result = None
        
        camera_name_ctx = None
        camera_structure_ctx = None
        if camera_id:
            try:
                bm = get_business_manager_for_project(project_name)
                camera_name_ctx, camera_structure_ctx = bm.get_camera_info(camera_id)
            except Exception as e:
                print(f"构造动态Prompt失败: {e}")

        if should_call_api:
            try:
                analysis_result, _is_mock = infer_traffic_image(
                    use_model,
                    data_uri,
                    allow_mock=True,
                    camera_name=camera_name_ctx,
                    camera_structure=camera_structure_ctx,
                )
            except Exception as ai_e:
                analysis_result = None
                ai_error_message = str(getattr(ai_e, "message", ai_e))
        else:
            print(f"[DEBUG] 跳过 AI 分析 (概率 {api_prob:.2f}): {file_name}")

        # 3.3 入库 (无论是否有 analysis_result)
        keywords = []
        description = ""
        qwen_captions = []
        yolo_objects = []
        keyword_embeddings = []
        
        if analysis_result:
             # 提取数据
            semantic = analysis_result.get("semantic_search", {})
            training = analysis_result.get("training_data", {})
            
            keywords = semantic.get("keywords", [])
            description = semantic.get("description", "")
            qwen_captions = training.get("qwen_captions", [])
            yolo_objects = training.get("yolo_objects", [])
            
            # 提取 Keyword 向量
            for k in keywords:
                try:
                    vec = encode_text_to_vector(k)
                    keyword_embeddings.append((k, vec))
                except:
                    pass

        final_camera_id = (camera_id or "").strip() or None
        client_sz = (sz_name or "").strip()
        bm_name: Optional[str] = None
        tag_refs: List[str] = []
        if final_camera_id:
            try:
                bm_meta = get_business_manager_for_project(project_name)
                bm_name, tag_refs = bm_meta.get_camera_sz_and_tag_refs(final_camera_id)
            except Exception as meta_e:
                print(f"业务结构元数据解析失败: {meta_e}")

        final_sz_name = client_sz if client_sz else bm_name
        if final_sz_name is not None and not str(final_sz_name).strip():
            final_sz_name = None
        sz_tag_ref_json_str = json.dumps(tag_refs, ensure_ascii=False) if tag_refs else None

        # 保存到 SQLite
        save_image_to_db(
            image_uuid=temp_uuid,
            file_path=minio_path, # 记录 MinIO 路径
            relative_path=minio_path, 
            file_name=final_file_name,
            tags=keywords + yolo_objects,
            keywords=keywords,
            description=description,
            qwen_captions=qwen_captions,
            yolo_objects=yolo_objects,
            keyword_embeddings=keyword_embeddings,
            camera_id=final_camera_id,
            sz_name=final_sz_name,
            sz_tag_ref_json=sz_tag_ref_json_str,
        )
        
        # 3.4 正式添加到 Faiss Index
        try:
             faiss_manager.add_vector(temp_uuid, spatial_vector)
        except Exception as fe:
             print(f"Faiss 添加失败: {fe}")
             
        faiss_manager.remove_pending_vector(temp_uuid) # 移除待处理状态
        
        # 3.5 保存 AI 原始 JSON 到 MinIO (可选)
        if analysis_result:
            try:
                json_path = minio_path + ".json"
                storage_client.upload_file_data(
                    json.dumps(analysis_result, ensure_ascii=False).encode('utf-8'),
                    json_path,
                    "application/json"
                )
            except Exception as je:
                print(f"JSON 上传失败: {je}")

        return {
            "status": "success",
            "uuid": temp_uuid,
            "minio_path": minio_path,
            "ai_result": clean_numpy(analysis_result) if analysis_result else None,
            "ai_skipped": not should_call_api or analysis_result is None,
            "ai_error": ai_error_message
        }

    except Exception as e:
        print(f"上传接口异常: {e}")
        traceback.print_exc()
        # 即使这里出错，如果是 Faiss 或 DB 步骤，可能数据已经部分写入。
        # 但如果是 image read error, return error.
        # User wants 'fail open' behavior, but catch-all here handles critical crashes.
        # If we failed before DB save, image is lost (but in MinIO maybe).
        try:
            get_faiss_index_manager().remove_pending_vector(temp_uuid) # Cleanup
        except:
            pass
        return {"status": "error", "message": str(e)}


@app.post("/upload-image-for-processing")
async def process_uploaded_image_api(
    file: UploadFile = File(...),
    project_name: str = Form(...),
    timestamp: Optional[str] = Form(None),
    camera_id: Optional[str] = Form(None),
    sz_name: Optional[str] = Form(None),
    threshold: float = Form(0.7409),
):
    """接收上传的图片，执行完整处理流程（在线程池中运行，不阻塞事件循环）"""
    image_bytes = await file.read()
    return await run_blocking(
        _process_uploaded_image_sync,
        image_bytes,
        file.filename,
        file.content_type or "image/jpeg",
        project_name,
        timestamp,
        camera_id,
        sz_name,
        threshold,
    )


# --- 项目脚本执行管理 ---
import collections
import threading
import os
import signal
from typing import Dict, Any

# 存储正在运行的进程信息 (辅助用，实际以 OS 进程为准)
process_store: Dict[str, Any] = {}
process_store_lock = threading.Lock()

@app.post("/project/run")
async def run_project_script_api(
    script_path: str = Form(...),
    project_name: str = Form(...)
):
    """执行指定的 Python 脚本（sync_task_01~04 经 systemd 独立单元）"""
    print(f"[DEBUG] Received run request for: {script_path}, project: {project_name}")

    if not script_path.endswith('.py') and not script_path.endswith('.sh'):
        return {"success": False, "message": "仅支持 .py 或 .sh 脚本"}

    if ".." in script_path:
        return {"success": False, "message": "非法脚本路径"}

    cwd = PROJECT_ROOT
    running, _ = sync_script_is_running(script_path)
    if running:
        return {"success": False, "message": "该脚本正在运行中", "running": True}

    if is_managed_sync_script(script_path):
        ok, msg = sync_start_script(cwd, script_path)
        if not ok:
            return {"success": False, "message": msg}
        update_project_status_by_script_db(script_path, "running")
        return {"success": True, "message": msg}

    log_file = log_file_for_script(cwd, script_path)
    try:
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"\n{'='*30}\n")
            f.write(f"[{datetime.now()}] 启动脚本: {script_path}\n")

        f_out = open(log_file, 'a')
        venv_python = os.path.join(cwd, "backend", "venv", "bin", "python")
        if not os.path.exists(venv_python):
            return {"success": False, "message": f"未找到虚拟环境解释器: {venv_python}"}
        run_cmd = f"exec {shlex.quote(venv_python)} -u {shlex.quote(script_path)}"
        process = subprocess.Popen(
            ["bash", "-c", run_cmd],
            cwd=cwd,
            stdout=f_out,
            stderr=f_out,
            preexec_fn=os.setsid,
        )
        pid = process.pid
        with process_store_lock:
            process_store[script_path] = {
                'pid': pid,
                'log_file': log_file,
                'start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        update_project_status_by_script_db(script_path, "running")
        return {"success": True, "message": "脚本启动成功", "pid": pid}
    except Exception as e:
        return {"success": False, "message": f"启动失败: {str(e)}"}
    finally:
        try:
            if 'f_out' in locals() and not f_out.closed:
                f_out.close()
        except Exception:
            pass


@app.post("/project/update_model")
async def update_project_model_api(
    project_id: str = Form(...),
    model: str = Form(...)
):
    try:
        update_project_model_db(project_id, model)
        return {"success": True}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/project/update_probability")
async def update_project_probability_api(
    project_id: str = Form(...),
    api_probability: float = Form(...)
):
    try:
        update_project_probability_db(project_id, api_probability)
        return {"success": True}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/project/stop")
async def stop_project_script_api(
    script_path: str = Form(...)
):
    """停止指定的脚本（sync 单元用 systemctl stop）"""
    cwd = PROJECT_ROOT
    try:
        if is_managed_sync_script(script_path):
            ok, msg = sync_stop_script(cwd, script_path)
            update_project_stop_time_db(script_path)
            return {"success": ok, "message": msg}

        cmd = ["pkill", "-9", "-f", f"python.*{os.path.basename(script_path)}"]
        subprocess.check_call(cmd)
        log_file = log_file_for_script(cwd, script_path)
        if os.path.exists(log_file):
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(
                    f"\n[{datetime.now().strftime('%H:%M:%S')}] "
                    f"用户请求停止脚本 (backend API)\n"
                )
        update_project_stop_time_db(script_path)
        return {"success": True, "message": "已发送停止信号"}
    except subprocess.CalledProcessError:
        update_project_stop_time_db(script_path)
        return {"success": True, "message": "进程已停止 (更新了停止时间)"}
    except Exception as e:
        return {"success": False, "message": f"停止错误: {e}"}


@app.get("/project/logs")
async def get_project_logs_api(script_path: str = Query(...)):
    """获取脚本日志"""
    cwd = PROJECT_ROOT
    running, _ = sync_script_is_running(script_path)
    status = "running" if running else "idle"
    logs = read_log_tail(cwd, script_path)
    return {
        "success": True,
        "logs": logs,
        "status": status
    }


# --- 脚本文件检查与预览 ---

@app.get("/project/check_script")
async def check_script_api(script_path: str = Query(...)):
    """检查脚本文件是否存在"""
    # 路径安全校验
    if ".." in script_path or script_path.startswith("/"):
        abs_path = os.path.abspath(script_path)
        # 简单检查
        if not abs_path.startswith(os.path.abspath(PROJECT_ROOT)):
             return {"exists": False, "message": "非法路径"}
    
    cwd = PROJECT_ROOT
    
    # 确保是相对路径拼接
    if script_path.startswith("/"):
        script_path = script_path.lstrip("/")
        
    full_path = os.path.join(cwd, script_path)
    
    if os.path.exists(full_path) and os.path.isfile(full_path):
        return {"exists": True, "message": "脚本存在"}
    else:
        return {"exists": False, "message": f"未找到文件: {script_path}"}


@app.get("/project/read_script")
async def read_script_api(script_path: str = Query(...)):
    """读取脚本内容 (只读预览)"""
    # 仅允许读取特定类型
    if not (script_path.endswith('.py') or script_path.endswith('.sh')):
         return {"success": False, "message": "不支持的文件类型"}

    cwd = PROJECT_ROOT
    
    if script_path.startswith("/"):
        script_path = script_path.lstrip("/")
        
    full_path = os.path.join(cwd, script_path)
    
    if os.path.exists(full_path) and os.path.isfile(full_path):
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return {"success": True, "content": content}
        except Exception as e:
            return {"success": False, "message": f"读取失败: {e}"}
    else:
        return {"success": False, "message": "文件不存在"}


# --- 项目 API ---

@app.get("/projects")
async def get_projects_api():
    """获取所有项目"""
    projects = get_all_projects_db()
    
    # 检查脚本是否存在
    cwd = PROJECT_ROOT
            
    final_list = []
    for p in projects:
        script_path = p['script_path']
        if script_path.startswith('/'): script_path = script_path.lstrip('/')
        full_path = os.path.join(cwd, script_path)
        
        script_exists = os.path.exists(full_path) and os.path.isfile(full_path)
        
        running, _ = sync_script_is_running(p['script_path'])
        real_status = 'running' if running else 'idle'

        # 转换 naming convention
        item = {
            "id": str(p['id']), # 转换为字符串，避免前端 === 比较失败
            "name": p['name'],
            "scriptPath": p['script_path'],
            "scheduleEnabled": bool(p['schedule_enabled']),
            "scheduleInterval": p['schedule_interval'],
            "lastRun": p['last_run'],
            "status": real_status, # 使用实时状态
            "createdAt": p['created_at'],
            "scriptExists": script_exists,
            "aiModel": p.get('ai_model', 'gemini'),
            "apiProbability": p.get('api_probability', 1.0),
            "lastStoppedAt": p.get('last_stopped_at')
        }
        final_list.append(item)
        
    return final_list

@app.post("/projects/add")
async def add_project_api(
    name: str = Form(...),
    script_path: str = Form(...)
):
    project_id = str(uuid.uuid4())
    add_project_db(project_id, name, script_path)
    return {
        "success": True, 
        "project": {
            "id": project_id,
            "name": name,
            "scriptPath": script_path,
            "scheduleEnabled": False,
            "scheduleInterval": 1,
            "lastRun": None,
            "status": 'idle',
            "createdAt": datetime.now().isoformat(),
            "scriptExists": True
        }
    }

@app.post("/projects/delete")
async def delete_project_api(project_id: str = Form(...)):
    delete_project_db(project_id)
    return {"success": True}

@app.post("/projects/update")
async def update_project_api(
    project_id: str = Form(...),
    name: Optional[str] = Form(None),
    schedule_enabled: Optional[bool] = Form(None),
    schedule_interval: Optional[int] = Form(None)
):
    updates = {}
    if name is not None: updates['name'] = name
    if schedule_enabled is not None: updates['schedule_enabled'] = schedule_enabled
    if schedule_interval is not None: updates['schedule_interval'] = schedule_interval
    
    if updates:
        update_project_db(project_id, updates)
        
    return {"success": True}



# --- 运行服务器 ---
if __name__ == "__main__":
    # 初始化数据库
    init_database()
    init_manage_database()
    
    test_qwen_connection()
    
    host = os.getenv("UVICORN_HOST", "0.0.0.0")
    port = int(os.getenv("UVICORN_PORT", "8000"))
    workers = int(os.getenv("UVICORN_WORKERS", "1"))
    reload = os.getenv("UVICORN_RELOAD", "true").lower() in ("1", "true", "yes")
    if reload and workers > 1:
        print(">> UVICORN_RELOAD=true 时仅使用 1 个 worker")
        workers = 1

    print(f"启动 TagLens AI 后端服务于 http://{host}:{port}")
    print(f"  - Qwen 模型: {os.getenv('QWEN_MODEL', 'qwen-vl-max')}")
    print(f"  - Gemini 模型: {os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview')}")
    print(f"  - LLM 网关: {LLM_GATEWAY_URL}（主后端代理 POST /llm/infer）")
    print(f"  - workers: {workers}, reload: {reload}")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        workers=workers,
        reload=reload,
    )

    
