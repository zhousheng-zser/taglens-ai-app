# -*- coding: utf-8 -*-
import os
import uvicorn
import json
import asyncio
import time
import base64
import uuid
import threading
import traceback
import threading
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import Response
import mimetypes
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
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
    update_project_stop_time_db
)
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
from routers import management_api
from services.business_structure_manager import get_business_manager_for_project

# 加载环境变量
load_dotenv()

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

# --- BGE 向量化模型初始化 ---
BGE_MODEL_NAME = "BAAI/bge-base-zh-v1.5"
BGE_MODEL_CACHE_DIR = Path(__file__).parent / "model"  # 模型存放路径: ./backend/model
_bge_tokenizer = None
_bge_model = None
_bge_device = None  # 存储模型使用的设备

def get_bge_model():
    """获取BGE模型（懒加载，优先使用本地缓存）"""
    global _bge_tokenizer, _bge_model, _bge_device
    if _bge_tokenizer is None or _bge_model is None:
        import time
        load_start = time.time()
        
        # 确保模型目录存在
        BGE_MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # 临时清除代理环境变量，确保BGE模型加载时不使用代理
        # transformers库会自动读取环境变量中的代理设置
        original_http_proxy = os.environ.pop('HTTP_PROXY', None)
        original_https_proxy = os.environ.pop('HTTPS_PROXY', None)
        original_http_proxy_lower = os.environ.pop('http_proxy', None)
        original_https_proxy_lower = os.environ.pop('https_proxy', None)
        
        try:
            print("正在加载BGE向量化模型...")
            print(f"  模型名称: {BGE_MODEL_NAME}")
            print(f"  模型存放路径: {BGE_MODEL_CACHE_DIR}")
            
            # 检查模型是否已存在于本地缓存
            # transformers库的缓存路径格式: cache_dir/models--ORG--MODEL_NAME/snapshots/HASH/
            model_exists = False
            try:
                import glob
                # 检查是否存在模型快照目录
                cache_pattern = str(BGE_MODEL_CACHE_DIR / "models--*" / "snapshots" / "*")
                cache_dirs = glob.glob(cache_pattern)
                if cache_dirs:
                    # 进一步检查关键文件是否存在
                    snapshot_dir = cache_dirs[0]
                    required_files = ['config.json', 'tokenizer_config.json']
                    if all((Path(snapshot_dir) / f).exists() for f in required_files):
                        model_exists = True
                        print(f"  检测到本地模型缓存，将使用离线模式（不访问网络）")
                    else:
                        print(f"  警告: 模型目录存在但文件不完整，可能需要重新下载")
                else:
                    print(f"  未检测到本地模型缓存，将尝试从网络下载")
            except Exception as e:
                print(f"  检查模型缓存时出错: {e}")
                # 如果检查出错，假设模型不存在，尝试在线加载
            
            # 如果模型已存在，使用local_files_only=True强制离线模式
            # 如果模型不存在，会尝试下载（但此时网络可能不可用）
            try:
                _bge_tokenizer = AutoTokenizer.from_pretrained(
                    BGE_MODEL_NAME,
                    cache_dir=str(BGE_MODEL_CACHE_DIR),
                    local_files_only=model_exists  # 如果模型存在，强制离线模式
                )
                _bge_model = AutoModel.from_pretrained(
                    BGE_MODEL_NAME,
                    cache_dir=str(BGE_MODEL_CACHE_DIR),
                    local_files_only=model_exists  # 如果模型存在，强制离线模式
                )
                
                # 自动检测并使用GPU（如果可用）
                if torch.cuda.is_available():
                    _bge_device = torch.device("cuda")
                    _bge_model = _bge_model.to(_bge_device)
                    print(f"  检测到GPU: {torch.cuda.get_device_name(0)}，将使用GPU加速")
                else:
                    _bge_device = torch.device("cpu")
                    print(f"  未检测到GPU，将使用CPU")
                
                _bge_model.eval()  # 设置为评估模式
                
                load_time = time.time() - load_start
                mode_str = "离线模式" if model_exists else "在线模式"
                device_str = "GPU" if _bge_device.type == "cuda" else "CPU"
                print(f"✓ BGE向量化模型加载完成（{mode_str},{device_str}）,耗时 {load_time:.2f}秒")
            except Exception as e:
                if "not found" in str(e).lower() or "local_files_only" in str(e).lower():
                    print(f"  错误: 本地模型文件不存在,需要从网络下载")
                    print(f"  如果网络不可用,请先下载模型到: {BGE_MODEL_CACHE_DIR}")
                    raise
                else:
                    raise
        finally:
            # 恢复代理环境变量
            if original_http_proxy:
                os.environ['HTTP_PROXY'] = original_http_proxy
            if original_https_proxy:
                os.environ['HTTPS_PROXY'] = original_https_proxy
            if original_http_proxy_lower:
                os.environ['http_proxy'] = original_http_proxy_lower
            if original_https_proxy_lower:
                os.environ['https_proxy'] = original_https_proxy_lower
    return _bge_tokenizer, _bge_model, _bge_device

def encode_text_to_vector(text: str) -> bytes:
    """
    使用BGE模型将文本编码为768维向量
    
    参数:
        text: 要编码的文本
    
    返回:
        bytes: 768维float32向量的二进制表示
    """
    tokenizer, model, device = get_bge_model()
    
    # 对文本进行编码
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    
    # 将输入移动到模型所在的设备（GPU或CPU）
    inputs = {k: v.to(device) for k, v in inputs.items()}
    
    # 生成向量
    with torch.no_grad():
        output = model(**inputs)
        embedding = output.last_hidden_state[:, 0]  # 使用CLS token
        embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)  # L2归一化
    
    # 转换为numpy数组并确保是float32（需要先移到CPU）
    embedding_np = embedding.cpu().numpy().astype(np.float32)
    
    # 转换为bytes
    return embedding_np.tobytes()

# --- 模型和API定义 ---
# 从环境变量读取模型配置,如果没有则使用默认值
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-vl-max")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
TEXT_MODEL = os.getenv("QWEN_TEXT_MODEL", "qwen-plus")  # 用于文本模型测试
# 北京地域的兼容Endpoint
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# --- Pydantic 模型定义 ---
class ImageAnalysisRequest(BaseModel):
    image: str # Base64 data URI
    model: str = "qwen"  # 可选值: "qwen", "gemini", "both"

class SemanticSearch(BaseModel):
    description: str
    keywords: list[str]

class TrainingData(BaseModel):
    qwen_captions: Dict[str, Any] | List[str]
    yolo_objects: list[str]

class TrafficAnalysisOutput(BaseModel):
    semantic_search: SemanticSearch
    training_data: TrainingData

class DualAnalysisResponse(BaseModel):
    qwen: Optional[TrafficAnalysisOutput] = None
    gemini: Optional[TrafficAnalysisOutput] = None
    error: Optional[str] = None

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
    similarityThreshold: Optional[float] = 0.6  # 相似度阈值,范围0-1

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
    similarity: Optional[float] = None  # 相似度分数（0-1之间）

class SearchResponse(BaseModel):
    success: bool
    results: List[ImageSearchResult]
    total: int

class ImageSimilarityCheckRequest(BaseModel):
    image: str  # Base64 data URI
    threshold: Optional[float] = 0.8188  # 相似度阈值,默认0.8188（81.88%）
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
    threshold: Optional[float] = 0.8188  # 默认 81.88%
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
        "description": "这是一张2025年12月24日09:03拍摄的城市高架桥监控画面。天气为阴天，光线均匀，河面平静，两岸可见高层住宅与商业建筑群。道路为双向四车道，车流方向由近及远，左侧车道车流背对镜头驶离，右侧车道车流正对镜头驶来。桥体结构为混凝土梁式桥，桥面两侧设有金属护栏与绿化带。桥下河道宽约二十米，水面呈灰绿色，两岸有步道与行道树。左上角OSD信息显示地点为‘长宁桥云台’，日期为周二，时间09:03。桥面上有多辆汽车行驶，包括一辆黑色轿车在右侧车道、一辆黄色轿车在中间车道、一辆深色轿车在最右侧车道。桥体上方未见龙门架或声屏障，路面有防眩板。远处背景为密集的城市高层建筑群，部分楼体外立面为玻璃幕墙。",
        "keywords": [
            "阴天",
            "长宁桥云台",
            "双向四车道",
            "混凝土高架桥",
            "河面平静",
            "高层建筑群",
            "金属护栏",
            "绿化带",
            "09:03",
            "黑色轿车",
            "黄色轿车",
            "深色轿车",
            "城市桥梁",
            "步道行道树",
            "玻璃幕墙"
        ]
    },
    "training_data": {
        "yolo_objects": [
            "黑色-轿车-右侧车道",
            "黄色-轿车-中间车道",
            "深色-轿车-最右侧车道",
            "混凝土-高架桥-主体结构",
            "金属-护栏-桥两侧",
            "绿化带-桥面边缘",
            "河水-桥下-灰绿色",
            "高层建筑-背景-密集分布",
            "行道树-河岸-沿岸排列"
        ],
        "qwen_captions": {
            "道路结构": {
                "道路类型": "地下通道",
                "车道信息": "单向双车道、应急车道、非机动车道、潮汐车道",
                "道路构造": "两侧设有水泥护栏、中央有隔离带、路面为红色沥青材质",
                "特殊构造": "隧道段、墙体为白色面板配蓝色装饰带"
            },
            "交通设施": {
                "标志标牌": "可见路牌、出口指示牌",
                "控制设备": "红绿灯、电子显示屏、可变限速标志",
                "安全设施": "两侧水泥护栏、防撞桶、声屏障、防眩板",
                "标线标识": "导流线、导向箭头、斑马线、人行横道、自行车道标识"
            },
            "环境信息": {
                "视角": "俯视角度拍摄、镜头位于通道上方制高点",
                "图像质量": "清晰、有压缩痕迹、光线均匀、有反光现象、有偏暗现象",
                "天气与路面": "室内环境、自然光照、路面干燥、有雨雪痕迹"
            },
            "特殊场所": {
                "场景设施": "收费站、服务区、上下客区",
                "区域结构": "通道呈缓弯曲线延伸、合流/分流段",
                "特殊用途区域": "公交专用道、调头区、紧急停车带",
            },
            "图像文字信息": {
                "OSD时间": "2025-12-24 09:46:03",
                "OSD地点": "诸光路地道上层云台014",
                "路面文字": "60、80、内环高架路,中山南一路"
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
                return "/project/logs" not in record.getMessage()
        
        logging.getLogger("uvicorn.access").addFilter(PollingFilter())
    except Exception:
        pass

    # --- Startup ---
    print("正在初始化应用...")
    init_database()
    print("数据库初始化完成")

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
            
            with ThreadPoolExecutor(max_workers=1) as api_executor:
                future = api_executor.submit(call_qwen_vision_api, qwen_key, data_uri)
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

# --- 提示词 ---
PROMPT_PART_1 = """你是一个交通视频AI分析专家。请仔细分析用户提供的图片，并严格按照我要求的JSON格式输出分析结果。JSON对象必须包含 semantic_search 和 training_data 两个键。"""

PROMPT_PART_2_TEMPLATE = """
**[关键] 重要提示** 以下信息为系统已知条件，作为图像理解的上下文背景使用，必须在分析中自然融合，但不得质疑或重新判断其正确性
	- 图片来源 :由{camera_name}相机拍摄
	- 相机业态目录结构 :{camera_structure}
"""

PROMPT_PART_3 = """
**重要说明:**
- semantic_search.description：生成一段**高密度、连贯、包含所有细节**的自然语言描述,用于标签提取和语义搜索，要求**客观、正面、具体**地描述图像中存在的所有视觉元素，**避免使用否定性表述**。
    **description写作要点：**
    - **[关键] 车道信息**: 必须明确描述道路结构（如"双向六车道"、"单向三车道+应急车道"）。
    - **[关键] 综合方向**: 结合OSD信息（如"上行/下行"）和视觉特征（如"由近及远"）进行综合描述。
    - 必须自然地融合以下信息：时间(从OSD读取)、地点(路名/桩号)、天气(雨/晴/阴)、光线、路面状态(潮湿/积水)、交通流量。
    - 必须详细描述基础设施：高架桥、声屏障、防眩板(颜色)、龙门架、路面文字标记(OCR内容)。
    - 必须包含OCR信息：将读取到的OSD信息和路面/路牌文字自然地写入句子中。
    - **[关键] 车辆位置**: 描述车辆时，必须精确指出其所在车道（如"在最左侧超车道"、"在中间行车道"、"在应急车道停靠"）。
    - 目的：这段话将被向量化，用于检索任何细节（如搜"占用应急车道"或"双向八车道"）。
    - 只描述**实际存在**的物体、环境、状态。
    - 避免"没有"、"无"、"不存在"等否定表述,如果画面中没有某些元素，应省略不提，而不是说"没有"或"无"。例如，如果没有人，就不要提及"人"或"无人"。
    - 禁止用"和"、"与"、"以及"、"并"、"还有"这样的连接词表述, 每句话只包含一个视觉元素,例如"左侧墙体设有检修口和金属栏杆，右侧墙面上方可见通风设备与照明设施。"
    - 保持客观、准确、详尽。

- semantic_search.keywords: 从description中提取10-15个核心标签词汇。

- qwen_captions: 用于Qwen等多模态大模型微调,从图中分析得到, 包含以下内容。
		"道路结构": {
			"道路类型": "高架、地面道路、桥梁、隧道、匝道、立交桥、环岛、地下通道",
			"车道信息": "主路、辅路、车道数量、是否有应急车道、非机动车道、人行道、潮汐车道",
			"道路构造": "分隔带、中央隔离带、绿化带、护栏、路肩、车道分界线",
			"特殊构造": "桥梁段、隧道口、桥下通道、桥墩、涵洞"
		},
		"交通设施": {
			"标志标牌": "路牌、出口指示牌、限速牌、距离提示牌、导向标志、限高架、限宽架",
			"控制设备": "红绿灯、电子显示屏、诱导屏、可变限速标志",
			"安全设施": "龙门架、防撞桶、声屏障、防眩板、钢/水泥护栏",
			"标线标识": "导流线、导向箭头、斑马线、人行横道、自行车道标识"
		},
		"环境信息": {
			"视角": "正视、俯视、斜视、后视、制高点、全景",
			"图像质量": "清晰、模糊、压缩严重、偏暗、反光强烈"
		},
		"特殊场所": {
			"场景设施": "收费站、隧道口、服务区、停车区、上下客区",
			"区域结构": "立交桥、桥段、桥下空间、上下匝道、合流/分流段",
			"特殊用途区域": "公交专用道、潮汐车道、调头区、紧急停车带",
		"图像文字信息": {
			"包括": "路牌、标线文字、地面字样、限速信息、摄像头水印、电子屏内容、广告标语等"
		}
    - 避免"没有"、"无"、"不存在"等否定表述,如果画面中没有某些元素，应省略不提，而不是说"没有"或"无"。例如，如果没有人，就不要提及"人"或"无人"。
    - **[必须] qwen_captions**: 宁缺毋滥，没有就不要写!!

- yolo_objects:生成结构化的目标清单，格式为 "颜色-物体-状态/位置"。
     - **位置必须精确**: 使用 "第一车道/超车道"、"中间车道"、"应急车道" 等精确描述。
     - 例如: "黑色-轿车-中间行车道(背对镜头)", "黄色-工程车-应急车道(正对镜头)", "绿色-防眩板-中央隔离带"。

**输出格式示例 (严格遵循此JSON结构):**
```json

{
    "semantic_search": {
        "description": "这是一张2025年12月24日09:03拍摄的城市高架桥监控画面。天气为阴天，光线均匀，河面平静，两岸可见高层住宅与商业建筑群。道路为双向四车道，车流方向由近及远，左侧车道车流背对镜头驶离，右侧车道车流正对镜头驶来。桥体结构为混凝土梁式桥，桥面两侧设有金属护栏与绿化带。桥下河道宽约二十米，水面呈灰绿色，两岸有步道与行道树。左上角OSD信息显示地点为‘长宁桥云台’，日期为周二，时间09:03。桥面上有多辆汽车行驶，包括一辆黑色轿车在右侧车道、一辆黄色轿车在中间车道、一辆深色轿车在最右侧车道。桥体上方未见龙门架或声屏障，路面无文字标记或防眩板。远处背景为密集的城市高层建筑群，部分楼体外立面为玻璃幕墙。",
        "keywords": [
            "阴天",
            "长宁桥云台",
            "双向四车道",
            "混凝土高架桥",
            "河面平静",
            "高层建筑群",
            "金属护栏",
            "绿化带",
            "09:03",
            "黑色轿车",
            "黄色轿车",
            "深色轿车",
            "城市桥梁",
            "步道行道树",
            "玻璃幕墙"
        ]
    },
    "training_data": {
        "yolo_objects": [
            "黑色-轿车-右侧车道",
            "黄色-轿车-中间车道",
            "深色-轿车-最右侧车道",
            "混凝土-高架桥-主体结构",
            "金属-护栏-桥两侧",
            "绿化带-桥面边缘",
            "河水-桥下-灰绿色",
            "高层建筑-背景-密集分布",
            "行道树-河岸-沿岸排列"
        ],
        "qwen_captions": {
            "道路结构": {
                "道路类型": "地下通道",
                "车道信息": "单向双车道、应急车道、非机动车道、潮汐车道",
                "道路构造": "两侧设有水泥护栏、中央有隔离带、路面为红色沥青材质",
                "特殊构造": "隧道段、墙体为白色面板配蓝色装饰带"
            },
            "交通设施": {
                "标志标牌": "可见路牌、出口指示牌",
                "控制设备": "红绿灯、电子显示屏、可变限速标志",
                "安全设施": "两侧水泥护栏、防撞桶、声屏障、防眩板",
                "标线标识": "导流线、导向箭头、斑马线、人行横道、自行车道标识"
            },
            "环境信息": {
                "视角": "俯视角度拍摄、镜头位于通道上方制高点",
                "图像质量": "清晰、有压缩痕迹、光线均匀、有反光现象、有偏暗现象",
                "天气与路面": "室内环境、自然光照、路面干燥、有雨雪痕迹"
            },
            "特殊场所": {
                "场景设施": "收费站、服务区、上下客区",
                "区域结构": "通道呈缓弯曲线延伸、合流/分流段",
                "特殊用途区域": "公交专用道、调头区、紧急停车带",
            },
            "图像文字信息": {
                "OSD时间": "2025-12-24 09:46:03",
                "OSD地点": "诸光路地道上层云台014",
                "路面文字": "60、80、内环高架路,中山南一路"
            }
        }
    }
}
"""

def get_qwen_client(api_key: str):
    """获取通义千问OpenAI兼容客户端"""
    return OpenAI(
        api_key=api_key, 
        base_url=BASE_URL,
        timeout=60.0  # 设置60秒超时
    )

# --- Qwen API 调用 ---
def call_qwen_vision_api(api_key: str, data_uri: str, prompt: str):
    """调用通义千问视觉模型进行图片分析"""
    client = get_qwen_client(api_key)
    try:
        completion = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
            top_p=0.8
        )
        content_text = completion.choices[0].message.content
        # 将 Qwen 原始响应写入日志文件，便于排查
        try:
            log_path = Path(__file__).parent.parent / "B_qwen_response.txt"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*40}\nQwen response at {datetime.now().isoformat()}:\n")
                f.write((content_text or "")[:800])
                f.write("\n")
        except Exception:
            pass
        # 清理返回的文本，提取纯JSON
        if content_text and "```json" in content_text:
            content_text = content_text.split("```json")[1].split("```")[0]
        
        return json.loads(content_text.strip())

    except Exception as e:
        print(f"Error calling Qwen Vision API: {e}")
        raise HTTPException(status_code=500, detail=f"调用AI视觉模型时出错: {e}")

# --- Gemini API 调用（使用 REST API）---
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
#API_URL_TEMPLATE = "http://192.168.2.65:8045/v1beta/models/gemini-3-flash:generateContent"

def get_proxies():
    """从环境变量获取代理设置"""
    proxies = {}
    http_proxy = os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
    https_proxy = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')
    
    if http_proxy:
        proxies['http'] = http_proxy
    if https_proxy:
        proxies['https'] = https_proxy
    
    return proxies if proxies else None

def call_gemini_vision_api(api_key: str, data_uri: str, prompt: str):
    """调用 Gemini 视觉模型进行图片分析（使用 REST API）"""
    try:
        # 构建请求 URL
        url = API_URL_TEMPLATE.format(model=GEMINI_MODEL)
        
        # 设置请求头
        headers = {
            'Content-Type': 'application/json',
            'X-goog-api-key': api_key
        }
        
        # 从 data URI 提取 base64 数据
        base64_data = data_uri.split(",")[1]
        
        # 确定 MIME 类型
        mime_type = "image/jpeg"
        if data_uri.startswith("data:image/png"):
            mime_type = "image/png"
        elif data_uri.startswith("data:image/webp"):
            mime_type = "image/webp"
        elif data_uri.startswith("data:image/gif"):
            mime_type = "image/gif"
        
        # 构建请求体
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64_data
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }
        
        # 获取代理设置
        proxies = get_proxies()
        
        # 发送请求
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            proxies=proxies,
            timeout=60
        )
        
        # 无论成功或失败，先把状态码与部分响应体写入日志文件，便于排查
        try:
            log_path = Path(__file__).parent.parent / "A_gemini_response.txt"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*40}\nGemini HTTP {response.status_code} at {datetime.now().isoformat()}:\n")
                f.write(response.text[:800])
                f.write("\n")
        except Exception:
            pass

        response.raise_for_status()
        result = response.json()
        
        # 提取响应内容
        if "candidates" in result and len(result["candidates"]) > 0:
            content_text = result["candidates"][0]["content"]["parts"][0]["text"]
            
            # 清理返回的文本，提取纯JSON
            if content_text and "```json" in content_text:
                content_text = content_text.split("```json")[1].split("```")[0]
            elif content_text and "```" in content_text:
                # 处理其他格式的代码块
                parts = content_text.split("```")
                for i, part in enumerate(parts):
                    if "{" in part and "}" in part:
                        content_text = part
                        break
            
            return json.loads(content_text.strip())
        else:
            raise HTTPException(status_code=500, detail="Gemini API 返回格式异常")
    
    except requests.exceptions.RequestException as e:
        print(f"Error calling Gemini Vision API: {e}")
        raise HTTPException(status_code=500, detail=f"调用Gemini视觉模型时出错: {e}")
    except json.JSONDecodeError as e:
        print(f"Error parsing Gemini API response: {e}")
        raise HTTPException(status_code=500, detail=f"解析Gemini API响应时出错: {e}")
    except Exception as e:
        print(f"Error calling Gemini Vision API: {e}")
        raise HTTPException(status_code=500, detail=f"调用Gemini视觉模型时出错: {e}")


def test_qwen_connection():
    """在启动时测试与通义千问的连接"""
    print("-" * 50)
    print("正在测试与通义千问 (DashScope) API 的连接...")
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key :
        print(">> 警告: 未找到或未配置有效的 QWEN_API_KEY 环境变量。")
        print(">> 后端将只能返回模拟数据。")
        print("-" * 50)
        return
    
    # 检查所有可能的代理设置（包括系统环境变量）
    http_proxy = os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
    https_proxy = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')
    
    # 检查系统环境变量（可能从shell或其他地方设置）
    import sys
    if hasattr(sys, 'environ'):
        sys_http_proxy = sys.environ.get('HTTP_PROXY') or sys.environ.get('http_proxy')
        sys_https_proxy = sys.environ.get('HTTPS_PROXY') or sys.environ.get('https_proxy')
        if sys_http_proxy and not http_proxy:
            http_proxy = sys_http_proxy
        if sys_https_proxy and not https_proxy:
            https_proxy = sys_https_proxy
    
    if http_proxy or https_proxy:
        print(f">> 检测到代理设置: HTTP_PROXY={http_proxy}, HTTPS_PROXY={https_proxy}")
        print(">> 注意: 如果代理未开启，可能会导致连接超时")
        print(">> 建议: 如果不需要代理，请确保系统环境变量和.env文件中都没有代理设置")
    else:
        print(">> 未检测到代理设置，将直接连接API")
    
    try:
        import time
        start_time = time.time()
        print(f">> 正在连接 DashScope API (base_url: {BASE_URL})...")
        
        client = get_qwen_client(api_key)
        completion = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': '你好'}
            ],
            timeout=30.0  # 测试连接使用30秒超时
        )
        elapsed_time = time.time() - start_time
        reply = completion.choices[0].message.content
        print(f">> ✓ 通义千问 ({TEXT_MODEL}) 连接成功！耗时 {elapsed_time:.2f}秒")
        print(f">> 回复: \"{reply.strip()}\"")

    except Exception as e:
        error_msg = str(e)
        print(f">> ✗ 错误: 调用通义千问 API 失败。")
        print(f">> 详细信息: {error_msg}")
        
        # 提供更具体的错误提示
        if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            print(">> 可能原因:")
            print(">>   1. 网络连接问题（无法访问 dashscope.aliyuncs.com）")
            if http_proxy or https_proxy:
                print(">>   2. 代理服务器未开启或无法连接（检测到代理设置但代理不可用）")
                print(">>   3. 建议: 临时清除代理环境变量测试: unset HTTP_PROXY HTTPS_PROXY")
            print(">>   4. API服务暂时不可用")
        elif "api" in error_msg.lower() and "key" in error_msg.lower():
            print(">> 可能原因: API密钥无效或未配置")
        elif "proxy" in error_msg.lower():
            print(">> 可能原因: 代理设置有问题，请检查代理服务器是否正常运行")
        elif "connection" in error_msg.lower() or "connect" in error_msg.lower():
            print(">> 可能原因: 网络连接失败，请检查:")
            print(">>   1. 网络是否正常")
            print(">>   2. 防火墙设置")
            if http_proxy or https_proxy:
                print(">>   3. 代理服务器状态")
    finally:
        print("-" * 50)


# --- API 路由 ---
@app.post("/check-similarity", response_model=ImageSimilarityCheckResponse)
async def check_image_similarity(request: ImageSimilarityCheckRequest):
    """
    检查上传的图片是否与数据库中的图片相似（使用 Faiss LSH）
    如果相似度超过阈值，返回相似图片列表，建议不调用大模型API
    """
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
        threshold = request.threshold or 0.8188
        
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


# --- 批量导入 API ---
@app.post("/bulk-import/create", response_model=BulkImportStatusResponse)
async def create_bulk_import_job_api(request: BulkImportStartRequest, background_tasks: BackgroundTasks):
    """创建新的批量导入任务并自动开始"""
    try:
        directory = request.directory if request.directory else "./data/local/img"
        threshold = request.threshold or 0.8188
        
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
    threshold = job.get("threshold") or 0.8188
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

@app.post("/analyze")
async def analyze_image(request: ImageAnalysisRequest):
    """分析图片，支持选择 Qwen、Gemini 或两者"""
    # 日志：记录调用来源的关键特征，方便对比前端“图片标签”和管理任务的请求形态
    raw_model = (request.model or "gemini") if hasattr(request, "model") else "gemini"
    img_str = request.image if hasattr(request, "image") and request.image else ""
    try:
        print("=" * 60)
        print(f"[/analyze] Incoming request - model={raw_model}")
        print(f"[/analyze] image_length={len(img_str)}, prefix={img_str[:80]!r}")
    except Exception:
        # 日志失败不影响主流程
        pass

    model = raw_model.lower()
    
    # 如果选择 both，返回 DualAnalysisResponse
    if model == "both":
        qwen_key = os.getenv("QWEN_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        
        result = DualAnalysisResponse()
        
        # 并行调用两个 API
        async def call_qwen():
            if not qwen_key :
                return None
            try:
                analysis_result = await asyncio.to_thread(
                    call_qwen_vision_api, 
                    qwen_key, 
                    request.image
                )
                return TrafficAnalysisOutput(**analysis_result)
            except Exception as e:
                print(f"Qwen API 调用失败: {e}")
                return None
        
        async def call_gemini():
            if not gemini_key :
                return None
            try:
                analysis_result = await asyncio.to_thread(
                    call_gemini_vision_api, 
                    gemini_key, 
                    request.image
                )
                return TrafficAnalysisOutput(**analysis_result)
            except Exception as e:
                print(f"Gemini API 调用失败: {e}")
                return None
        
        # 并行执行
        qwen_result, gemini_result = await asyncio.gather(
            call_qwen(),
            call_gemini(),
            return_exceptions=True
        )
        
        if isinstance(qwen_result, Exception):
            result.error = f"Qwen API 错误: {str(qwen_result)}"
        else:
            result.qwen = qwen_result
        
        if isinstance(gemini_result, Exception):
            if result.error:
                result.error += f"; Gemini API 错误: {str(gemini_result)}"
            else:
                result.error = f"Gemini API 错误: {str(gemini_result)}"
        else:
            result.gemini = gemini_result
        
        if not result.qwen and not result.gemini:
            raise HTTPException(status_code=500, detail=result.error or "两个 API 都调用失败")
        
        return result
    
    # 单个模型调用
    elif model == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key :
            print("警告: 未找到有效的 GEMINI_API_KEY，将返回模拟数据。")
            await asyncio.sleep(1)
            return mock_analysis_data
        
        # 构造默认Prompt
        default_prompt = PROMPT_PART_1 + "\n" + PROMPT_PART_3
        try:
            analysis_result = await asyncio.to_thread(
                call_gemini_vision_api, 
                api_key, 
                request.image,
                default_prompt
            )
            validated_result = TrafficAnalysisOutput(**analysis_result)
            return validated_result
        except HTTPException as e:
            raise e
        except Exception as e:
            print(f"处理图片时发生错误: {e}")
            raise HTTPException(status_code=500, detail=f"AI分析失败: {str(e)}")
    
    else:  # 默认使用 qwen
        api_key = os.getenv("QWEN_API_KEY")
        if not api_key :
            print("警告: 未找到有效的 QWEN_API_KEY，将返回模拟数据。")
            await asyncio.sleep(1)
            return mock_analysis_data

        # 构造默认Prompt
        default_prompt = PROMPT_PART_1 + "\n" + PROMPT_PART_3
        try:
            analysis_result = await asyncio.to_thread(
                call_qwen_vision_api, 
                api_key, 
                request.image,
                default_prompt
            )
            validated_result = TrafficAnalysisOutput(**analysis_result)
            return validated_result
        except HTTPException as e:
            raise e
        except Exception as e:
            print(f"处理图片时发生错误: {e}")
            raise HTTPException(status_code=500, detail=f"AI分析失败: {str(e)}")

@app.get("/")
def read_root():
    return {"message": "欢迎使用 TagLens AI 后端服务 (Qwen-Powered)"}

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

@app.post("/save-image", response_model=SaveImageResponse)
async def save_image(request: SaveImageRequest):
    """
    保存图片到 MinIO 和数据库
    路径格式: project_data/default/YYYY-MM-DD/uuid.ext
    """
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


# --- 搜索 API ---
@app.post("/search", response_model=SearchResponse)
async def search_images_api(request: SearchRequest):
    """从数据库搜索图片（使用向量相似度搜索，支持多标签和权重）"""
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
        # 对每个查询标签进行向量化
        query_embeddings = []
        if queries:
            try:
                for query in queries:
                    embedding = encode_text_to_vector(query)
                    query_embeddings.append(embedding)
                    print(f"已生成查询向量: '{query}' (维度: {len(embedding) // 4})")
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
            query_embeddings=query_embeddings if query_embeddings else None,  # 传递多个向量
            query_weights=weights if weights else None,  # 传递权重列表
            similarity_threshold=similarity_threshold,
            page=page if use_limit is None else None,  # 如果使用limit，则不使用分页
            page_size=page_size if use_limit is None else None
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
                    similarity=similarity_value  # 添加相似度字段
                )
            )
        
        return SearchResponse(
            success=True,
            results=image_results,
            total=total_count  # 返回总数，而不是当前页的数量
        )
    except HTTPException as e:
        print(f"搜索图片时发生HTTP异常: {e}")
        raise e
    except Exception as e:
        print(f"搜索图片时发生错误: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")

@app.get("/images", response_model=SearchResponse)
async def get_all_images_api(limit: int = Query(100, ge=1, le=1000)):
    """获取所有图片"""
    try:
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
                yoloObjects=r['yoloObjects']
            )
            for r in results
        ]
        
        return SearchResponse(
            success=True,
            results=image_results,
            total=len(image_results)
        )
    except Exception as e:
        print(f"获取图片列表时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"获取图片列表失败: {str(e)}")

# --- 直接读取文件系统图片接口 ---
@app.get("/api/images/direct")
async def get_image_direct(
    path: str = Query(..., description="图片路径（MinIO 对象路径）")
):
    """直接从文件系统读取图片（不通过 MinIO 客户端）"""
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


# --- MinIO 图片下载接口 ---
@app.get("/api/minio/download/image")
async def download_image_api(
    object_name: str = Query(..., description="MinIO 中的对象名称（路径）")
):
    """从 MinIO 下载图片"""
    try:
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
            headers={"Content-Disposition": f'inline; filename="{filename}"'}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


# --- 图片上传处理接口 (Project Sync用) ---
@app.post("/upload-image-for-processing")
async def process_uploaded_image_api(
    file: UploadFile = File(...),
    project_name: str = Form(...),
    timestamp: Optional[str] = Form(None),
    camera_id: Optional[str] = Form(None),
    threshold: float = Form(0.8188)
):
    """
    接收上传的图片，执行完整处理流程：
    1. 去重 (Faiss)
    2. 上传 MinIO
    3. AI 分析 (Qwen)
    4. 入库 (MySQL/SQLite)
    """
    try:
        # 1. 读取图片数据
        image_bytes = await file.read()
        file_name = file.filename
        
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
        
        # 生成一个临时UUID用于去重检查
        temp_uuid = str(uuid.uuid4())
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

        storage_client.upload_file_data(image_bytes, minio_path, file.content_type or "image/jpeg")

        # 3.2 AI 分析 preparation
        import base64
        import random
        
        base64_str = base64.b64encode(image_bytes).decode('utf-8')
        mime_type = file.content_type or "image/jpeg"
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
        
        # 构造动态 Prompt
        final_prompt = PROMPT_PART_1 + "\n" + PROMPT_PART_3
        if camera_id:
            try:
                bm = get_business_manager_for_project(project_name)
                c_name, c_struct = bm.get_camera_info(camera_id)
                # 只有当能获取到有效信息时才添加上下文
                if c_struct and c_struct != "未知区域":
                    part2 = PROMPT_PART_2_TEMPLATE.format(camera_name=c_name, camera_structure=c_struct)
                    final_prompt = PROMPT_PART_1 + "\n" + part2 + "\n" + PROMPT_PART_3
            except Exception as e:
                print(f"构造动态Prompt失败: {e}")

        if should_call_api:
            # 异步调用 AI (Run in thread pool)
            try:
                loop = asyncio.get_event_loop()
                
                if use_model == 'qwen':
                    qwen_key = os.getenv("QWEN_API_KEY")
                    print(f"[DEBUG] Qwen API Key configured: {'Yes' if qwen_key else 'No'}")
                    if not qwen_key :
                        print("服务端未配置 QWEN_API_KEY，跳过 AI 分析")
                        analysis_result = None
                    else:
                        analysis_result = await loop.run_in_executor(
                            None, 
                            call_qwen_vision_api, 
                            qwen_key, 
                            data_uri,
                            final_prompt
                        )
                else:
                    # Default to Gemini
                    gemini_key = os.getenv("GEMINI_API_KEY")
                    if not gemini_key:
                        print("服务端未配置 GEMINI_API_KEY，跳过 AI 分析")
                        analysis_result = None
                    else:
                        analysis_result = await loop.run_in_executor(
                            None, 
                            call_gemini_vision_api, 
                            gemini_key, 
                            data_uri,
                            final_prompt
                        )
            except Exception as ai_e:
                analysis_result = None
                ai_error_message = str(ai_e)
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
            keyword_embeddings=keyword_embeddings
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
            "ai_error": ai_error_message if 'ai_error_message' in locals() else None
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


# --- 项目脚本执行管理 ---
import subprocess
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
    """执行指定的 Python 脚本"""
    print(f"[DEBUG] Received run request for: {script_path}, project: {project_name}")
    
    if not script_path.endswith('.py') and not script_path.endswith('.sh'):
        return {"success": False, "message": "仅支持 .py 或 .sh 脚本"}
    
    if ".." in script_path or script_path.startswith("/"):
        abs_path = os.path.abspath(script_path)
        project_root = os.path.abspath(os.getcwd())
        if not abs_path.startswith(project_root):
             if not abs_path.startswith("/opt/Traffic-LLM/zser/taglens-ai-app"):
                  return {"success": False, "message": "非法脚本路径"}
    
    # 1. 确定工作目录
    cwd = os.getcwd()
    if "/opt/Traffic-LLM/zser/taglens-ai-app" not in cwd:
            cwd = "/opt/Traffic-LLM/zser/taglens-ai-app"
    
    # 2. 准备日志文件
    log_dir = os.path.join(cwd, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{os.path.basename(script_path)}.log")
    
    # 3. 检查是否已经在运行
    check_cmd = ["pgrep", "-f", f"python.*{os.path.basename(script_path)}"]
    try:
        subprocess.check_output(check_cmd)
        return {"success": False, "message": "该脚本正在运行中", "running": True}
    except subprocess.CalledProcessError:
        pass
        
    # 4. 构建命令 (使用 nohup 后台运行)
    # 这里的关键是 'python -u' 确保无缓冲输出，以便日志实时写入
    # 4. 启动进程 (使用 subprocess.Popen 接管输出)
    try:
        # 确保日志文件可写，先写入启动头 (使用 'w' 模式清空旧日志)
        with open(log_file, 'w') as f:
            f.write(f"\n{'='*30}\n")
            f.write(f"[{datetime.now()}] 启动脚本: {script_path}\n")
        
        # 打开文件句柄传递给子进程
        f_out = open(log_file, 'a')
        
        # 构建命令
        # 使用 exec 确保 python 进程替换 bash，这样 PID 才是 python 的，方便 pkill
        activate_cmd = "source backend/venv/bin/activate"
        run_cmd = f"{activate_cmd} && exec python3 -u {script_path}"
        
        process = subprocess.Popen(
            ["bash", "-c", run_cmd],
            cwd=cwd,
            stdout=f_out,
            stderr=f_out,  # stderr 也重定向到同一个日志
            preexec_fn=os.setsid, # 关键：开启新会话，即使后端关闭，脚本仍运行
        )
        
        pid = process.pid
        
        # 不等待子进程，直接记录并返回
        # 父进程可以安全关闭文件句柄，子进程已经继承
        # f_out.close() # 可以在 finally 中关闭
        
        with process_store_lock:
            process_store[script_path] = {
                'pid': pid,
                'log_file': log_file,
                'start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
        return {"success": True, "message": "脚本启动成功", "pid": pid}
        
    except Exception as e:
        return {"success": False, "message": f"启动失败: {str(e)}"}
    finally:
        # 尝试关闭文件句柄 (如果是局部变量需要检查是否存在)
        try:
            if 'f_out' in locals() and not f_out.closed:
                f_out.close()
        except:
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
    """停止指定的脚本"""
    # 直接使用 pkill 匹配命令行查杀，简单粗暴且有效
    # 匹配 'python -u {script_path}'
    try:
        # pkill -f Returns 0 if at least one process matched and was signaled
        # 使用 -9 强制终止，防止脚本挂起或捕获信号后不退出
        cmd = ["pkill", "-9", "-f", f"python.*{os.path.basename(script_path)}"]
        subprocess.check_call(cmd)
        
        # 记录停止操作到日志（如果可能）
        cwd = os.getcwd()
        if "/opt/Traffic-LLM/zser/taglens-ai-app" not in cwd:
             cwd = "/opt/Traffic-LLM/zser/taglens-ai-app"
        log_file = os.path.join(cwd, "logs", f"{os.path.basename(script_path)}.log")
        if os.path.exists(log_file):
            with open(log_file, "a") as f:
                f.write(f"\n[{datetime.now().strftime('%H:%M:%S')}] 用户请求停止脚本 (backend API)\n")
        
        # 记录停止时间
        update_project_stop_time_db(script_path)
                
        return {"success": True, "message": "已发送停止信号"}
    except subprocess.CalledProcessError:
        # 即使进程未找到（可能已自行退出），我们也视为“停止”，更新时间
        update_project_stop_time_db(script_path)
        return {"success": True, "message": "进程已停止 (更新了停止时间)"}
    except Exception as e:
        return {"success": False, "message": f"停止错误: {e}"}


@app.get("/project/logs")
async def get_project_logs_api(script_path: str = Query(...)):
    """获取脚本日志"""
    
    # 1. 确定日志路径
    cwd = os.getcwd()
    if "/opt/Traffic-LLM/zser/taglens-ai-app" not in cwd:
            cwd = "/opt/Traffic-LLM/zser/taglens-ai-app"
    log_file = os.path.join(cwd, "logs", f"{os.path.basename(script_path)}.log")
    
    # 2. 检查进程状态
    # 修复：不使用 shell=True，避免 pgrep 匹配到 shell 命令本身
    check_cmd = ["pgrep", "-a", "-f", f"python.*{os.path.basename(script_path)}"]
    status = "idle"
    try:
        output = subprocess.check_output(check_cmd).decode().strip()
        if output:
            # 再次检查，确保不是编辑器或无关进程
            status = "running"
            # print(f"[DEBUG] 发现进程: {output}")
    except subprocess.CalledProcessError:
        status = "idle"
        
    # 3. 读取日志
    logs = []
    if os.path.exists(log_file):
        try:
            # 读取最后 300 行
            # 使用 tail 命令可能更高效，避免读取整个大文件
            tail_cmd = f"tail -n 300 {log_file}"
            log_output = subprocess.check_output(tail_cmd, shell=True).decode('utf-8', errors='replace')
            logs = log_output.splitlines()
        except Exception as e:
            logs = [f"读取日志错误: {e}"]
    else:
        logs = ["等待日志生成..."]

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
        if not abs_path.startswith("/opt/Traffic-LLM/zser/taglens-ai-app"):
             return {"exists": False, "message": "非法路径"}
    
    cwd = os.getcwd()
    if "/opt/Traffic-LLM/zser/taglens-ai-app" not in cwd:
         cwd = "/opt/Traffic-LLM/zser/taglens-ai-app"
    
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

    cwd = os.getcwd()
    if "/opt/Traffic-LLM/zser/taglens-ai-app" not in cwd:
         cwd = "/opt/Traffic-LLM/zser/taglens-ai-app"
    
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
    cwd = os.getcwd()
    if "/opt/Traffic-LLM/zser/taglens-ai-app" not in cwd:
         cwd = "/opt/Traffic-LLM/zser/taglens-ai-app"
            
    final_list = []
    for p in projects:
        script_path = p['script_path']
        if script_path.startswith('/'): script_path = script_path.lstrip('/')
        full_path = os.path.join(cwd, script_path)
        
        script_exists = os.path.exists(full_path) and os.path.isfile(full_path)
        
        # 实时检查进程状态
        real_status = 'idle'
        try:
             # 我们在 run 接口启动时用的是 exec python3 -u {script_path}
             # 为了稳健，使用 script_path 的文件名进行模糊匹配，不使用 shell=True 以避免自匹配
             check_cmd = ["pgrep", "-f", f"python.*{os.path.basename(p['script_path'])}"]
             subprocess.check_output(check_cmd)
             real_status = 'running'
        except subprocess.CalledProcessError:
             real_status = 'idle'

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
    
    test_qwen_connection()
    
    print(f"启动 TagLens AI 后端服务于 http://localhost:8000")
    print(f"  - Qwen 模型: {QWEN_MODEL}")
    print(f"  - Gemini 模型: {GEMINI_MODEL}")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

    
