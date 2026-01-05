# -*- coding: utf-8 -*-
import os
import uvicorn
import json
import asyncio
import time
import base64
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
import requests
import numpy as np
import torch
from transformers import AutoTokenizer, AutoModel
from database import init_database, save_image_to_db, search_images, get_all_images

# 加载环境变量
load_dotenv()

# --- BGE 向量化模型初始化 ---
BGE_MODEL_NAME = "BAAI/bge-base-zh-v1.5"
BGE_MODEL_CACHE_DIR = Path(__file__).parent / "model"  # 模型存放路径: ./backend/model
_bge_tokenizer = None
_bge_model = None

def get_bge_model():
    """获取BGE模型（懒加载，优先使用本地缓存）"""
    global _bge_tokenizer, _bge_model
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
                _bge_model.eval()  # 设置为评估模式
                
                load_time = time.time() - load_start
                mode_str = "离线模式" if model_exists else "在线模式"
                print(f"✓ BGE向量化模型加载完成（{mode_str}），耗时 {load_time:.2f}秒")
            except Exception as e:
                if "not found" in str(e).lower() or "local_files_only" in str(e).lower():
                    print(f"  错误: 本地模型文件不存在，需要从网络下载")
                    print(f"  如果网络不可用，请先下载模型到: {BGE_MODEL_CACHE_DIR}")
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
    return _bge_tokenizer, _bge_model

def encode_text_to_vector(text: str) -> bytes:
    """
    使用BGE模型将文本编码为768维向量
    
    参数:
        text: 要编码的文本
    
    返回:
        bytes: 768维float32向量的二进制表示
    """
    tokenizer, model = get_bge_model()
    
    # 对文本进行编码
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    
    # 生成向量
    with torch.no_grad():
        output = model(**inputs)
        embedding = output.last_hidden_state[:, 0]  # 使用CLS token
        embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)  # L2归一化
    
    # 转换为numpy数组并确保是float32
    embedding_np = embedding.cpu().numpy().astype(np.float32)
    
    # 转换为bytes
    return embedding_np.tobytes()

# --- 模型和API定义 ---
# 从环境变量读取模型配置，如果没有则使用默认值
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-vl-max")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
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
    clip_captions: list[str]
    qwen_captions: list[str]
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
    clipCaptions: list[str] = []  # CLIP 描述
    qwenCaptions: list[str] = []  # Qwen 描述
    yoloObjects: list[str] = []  # YOLO 对象

class SaveImageResponse(BaseModel):
    success: bool
    uuid: str
    file_path: str
    relative_path: str
    message: str

class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 100
    startDate: Optional[str] = None  # ISO 格式日期时间
    endDate: Optional[str] = None    # ISO 格式日期时间
    similarityThreshold: Optional[float] = 0.3  # 相似度阈值，范围0-1

class ImageSearchResult(BaseModel):
    id: int
    uuid: str
    filePath: str
    fileName: Optional[str]
    createdAt: str
    description: str
    keywords: List[str]
    tags: List[str]
    clipCaptions: List[str]
    qwenCaptions: List[str]
    yoloObjects: List[str]
    similarity: Optional[float] = None  # 相似度分数（0-1之间）

class SearchResponse(BaseModel):
    success: bool
    results: List[ImageSearchResult]
    total: int

# 如果没有API密钥，将返回此示例数据
mock_analysis_data = {
  "semantic_search": {
    "description": "这是在傍晚拍摄的高速公路监控图像。天气晴朗，路面干燥。双向四车道，交通流量稀疏。一辆白色SUV在近处车道行驶，远处有其他车辆。道路两侧装有标准的金属护栏。(此为无API-KEY时的模拟数据)",
    "keywords": ["高速公路", "傍晚", "晴天", "交通稀疏", "白色SUV", "护栏", "模拟数据"]
  },
  "training_data": {
    "clip_captions": [
      "傍晚时分的高速公路场景",
      "一辆白色SUV在干燥的沥青路面上行驶",
      "道路交通流量不大",
      "远处可以看到地平线上的晚霞",
      "监控摄像头视角下的公路交通"
    ],
    "qwen_captions": [
      "这张监控画面显示傍晚时分的高速公路，天气晴朗，路面干燥，交通流量稀疏。",
      "一辆白色SUV在近处车道行驶，远处有其他车辆，道路两侧装有标准的金属护栏。"
    ],
    "yolo_objects": [
      "白色-SUV-行驶中",
      "金属-护栏-道路两侧",
      "沥青-路面-干燥"
    ]
  }
}

# --- FastAPI 应用设置 ---
app = FastAPI()

# --- 启动事件：初始化数据库和预加载BGE模型 ---
@app.on_event("startup")
async def startup_event():
    """应用启动时初始化数据库和预加载BGE模型"""
    init_database()
    print("数据库初始化完成")
    
    # 预加载BGE模型，避免首次使用时延迟
    print("正在预加载BGE向量化模型...")
    try:
        get_bge_model()
        print("✓ BGE向量化模型预加载完成")
    except Exception as e:
        print(f"⚠ BGE向量化模型预加载失败: {e}")
        print("  将在首次使用时加载")

# --- CORS 中间件 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 提示词 ---
PROMPT = """
你是一个交通视频AI分析专家。请仔细分析用户提供的图片，并严格按照我要求的JSON格式输出分析结果。JSON对象必须包含 semantic_search 和 training_data 两个键。

**重要说明：**
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
    - 保持客观、准确、详尽。

- semantic_search.keywords：从description中提取10-15个核心标签词汇。

- qwen_captions：用于Qwen-VL等多模态大模型的SFT微调，要求**任务导向**，每条为一个完整的问答对或指令响应，模拟真实用户可能的提问和模型的回答，可包含分析、推理、建议等内容。
    - **[弹性数量]**: 根据画面信息密度自动调整数量。简单的场景只需3-4句，复杂的场景可达7-8句。**宁缺毋滥，不要凑数**。
    - **[核心原则] 只描述"永远存在"的东西**: 假设这张图是该摄像机的"身份证"，只描述其永久属性。
    - **[严禁] 动态/瞬态信息**: 严禁包含天气(雨/晴)、光线(早晚)、具体车辆(黑色轿车)、交通状况(拥堵)。
    - **[必须] 背景环境**:描述远处的静态背景（高楼、树木、天空轮廓等）。**宁缺毋滥，没有就不要写**
    - **[必须] 道路结构**: 描述车道数、道路类型、车流固有流向等。**宁缺毋滥，没有就不要写**
    - **[必须] 基础设施**: 描述声屏障、龙门架、路灯、地面固定标线（导向箭头）等。**宁缺毋滥，没有就不要写**

- clip_captions：生成 **3-8 条**精选的、纯静态的场景特征描述，用于CLIP模型训练的图文对齐微调，要求**简短、客观、通用**，描述图像中的基本视觉元素，适合检索和分类任务。
    - **[弹性数量]**: 根据画面信息密度自动调整数量。简单的场景（如隧道）只需3-4句，复杂的场景（如立交桥枢纽）可达7-8句。**宁缺毋滥，不要凑数**。
    - **[核心原则] 只描述"永远存在"的东西**: 假设这张图是该摄像机的"身份证"，只描述其永久属性。
    - **[严禁] 动态/瞬态信息**: 严禁包含天气(雨/晴)、光线(早晚)、具体车辆(黑色轿车)、交通状况(拥堵)。
    - **[必须] 道路结构**: 描述车道数、道路类型、车流固有流向（如"右侧车道车流背对镜头驶离"）。例如: "一条双向六车道的城市高架快速路", "路面中央设有绿色的连续防眩板"。
    - **[必须] 基础设施**: 描述声屏障、龙门架、路灯、地面固定标线（导向箭头）。例如: "道路两侧安装了灰色的金属声屏障", "路面上印有白色的直行导向箭头"。
    - **[必须] 背景环境**: 描述远处的静态背景（高楼、树木、天空轮廓）。例如: "画面背景是密集的城市高层住宅楼"。
    - 句式要客观、独立，不要重复。

- yolo_objects:生成结构化的目标清单，格式为 "颜色-物体-状态/位置"。
     - **位置必须精确**: 使用 "第一车道/超车道"、"中间车道"、"应急车道" 等精确描述。
     - 例如: "黑色-轿车-中间行车道(背对镜头)", "黄色-工程车-应急车道(正对镜头)", "绿色-防眩板-中央隔离带"。

**输出格式示例 (严格遵循此JSON结构):**
```json
{
  "semantic_search": {
    "description": "这是一张2025年12月24日07:03拍摄的S125北青线高架桥监控画面。天气为雨天，光线较暗，沥青路面潮湿且有明显的积水反光。道路为双向六车道，交通流量中等。路面上印有巨大的白色'高架'和'闭'字样导向标记，道路中央安装了绿色的连续防眩板，两侧有灰色的声屏障。左上角OSD信息显示桩号为K21+900，方向为上行。一辆黑色轿车正在中间车道行驶，尾灯亮起。",
    "keywords": ["雨天", "S125", "高架桥", "防眩板", "路面文字", "K21+900", "声屏障", "沥青路面", "黑色轿车"]
  },
  "training_data": {
    "clip_captions": [
      "一张雨天的高架桥道路监控图片",
      "路面上印有巨大的白色文字标记",
      "道路中央安装了绿色的防眩板",
      "沥青路面潮湿并反射着车灯",
      "高架桥两侧安装了声屏障",
      "一辆黑色轿车在中间车道行驶"
    ],
    "qwen_captions": [
      "这张监控画面显示雨天清晨的S125高架桥，路面湿滑存在安全隐患，建议驾驶员降低车速并保持安全距离。",
      "路面上的白色'高架'和'闭'字标识是重要的交通指引，提醒驾驶员即将进入高架路段并注意车道变化。",
      "绿色防眩板的设置有效减少了夜间对向车灯造成的视觉干扰，提升了行车安全系数。"
    ],
    "yolo_objects": [
      "黑色-轿车-中间车道",
      "绿色-防眩板-中央",
      "白色-文字标记-路面"
    ]
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
def call_qwen_vision_api(api_key: str, data_uri: str):
    """调用通义千问视觉模型进行图片分析"""
    client = get_qwen_client(api_key)
    try:
        completion = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
            top_p=0.8
        )
        content_text = completion.choices[0].message.content
        # 清理返回的文本，提取纯JSON
        if content_text and "```json" in content_text:
            content_text = content_text.split("```json")[1].split("```")[0]
        
        return json.loads(content_text.strip())

    except Exception as e:
        print(f"Error calling Qwen Vision API: {e}")
        raise HTTPException(status_code=500, detail=f"调用AI视觉模型时出错: {e}")

# --- Gemini API 调用（使用 REST API）---
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

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

def call_gemini_vision_api(api_key: str, data_uri: str):
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
                        {"text": PROMPT},
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
    if not api_key or api_key == "11111":
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
@app.post("/analyze")
async def analyze_image(request: ImageAnalysisRequest):
    """分析图片，支持选择 Qwen、Gemini 或两者"""
    model = request.model.lower()
    
    # 如果选择 both，返回 DualAnalysisResponse
    if model == "both":
        qwen_key = os.getenv("QWEN_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        
        result = DualAnalysisResponse()
        
        # 并行调用两个 API
        async def call_qwen():
            if not qwen_key or qwen_key == "11111":
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
            if not gemini_key or gemini_key == "11111":
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
        if not api_key or api_key == "11111":
            print("警告: 未找到有效的 GEMINI_API_KEY，将返回模拟数据。")
            await asyncio.sleep(1)
            return mock_analysis_data
        
        try:
            analysis_result = await asyncio.to_thread(
                call_gemini_vision_api, 
                api_key, 
                request.image
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
        if not api_key or api_key == "11111":
            print("警告: 未找到有效的 QWEN_API_KEY，将返回模拟数据。")
            await asyncio.sleep(1)
            return mock_analysis_data

        try:
            analysis_result = await asyncio.to_thread(
                call_qwen_vision_api, 
                api_key, 
                request.image
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
    保存图片到文件系统和数据库
    路径格式: data/YYYYMMDD/0/uuid.ext
    """
    try:
        # 获取项目根目录
        project_root = Path(__file__).parent.parent.absolute()
        data_dir = project_root / "data"
        
        # 获取当前日期 (YYYYMMDD)
        date_str = datetime.now().strftime("%Y%m%d")
        
        # 创建目录结构: data/日期/0/
        save_dir = data_dir / date_str / "0"
        save_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成 UUID
        image_uuid = str(uuid.uuid4())
        
        # 从 data URI 提取图片格式和数据
        ext, image_bytes = extract_image_format_from_data_uri(request.image)
        
        # 构建文件路径
        filename = f"{image_uuid}.{ext}"
        file_path = save_dir / filename
        
        # 保存文件
        with open(file_path, "wb") as f:
            f.write(image_bytes)
        
        # 构建相对路径 (相对于项目根目录)
        relative_path = f"data/{date_str}/0/{filename}"
        
        # 对每个keyword分别进行向量化
        keyword_embeddings = []
        if request.keywords and len(request.keywords) > 0:
            import time
            vectorization_start = time.time()
            print(f"开始向量化 {len(request.keywords)} 个keywords...")
            
            for i, keyword in enumerate(request.keywords, 1):
                try:
                    # 对每个keyword单独向量化
                    embedding_bytes = encode_text_to_vector(keyword)
                    keyword_embeddings.append((keyword, embedding_bytes))
                    if i <= 3 or i == len(request.keywords):  # 只打印前3个和最后一个
                        print(f"  [{i}/{len(request.keywords)}] 已生成keyword向量: '{keyword}'")
                except Exception as e:
                    print(f"向量化keyword '{keyword}' 时出错: {e}")
                    # 即使某个keyword向量化失败，也继续处理其他keyword
            
            vectorization_time = time.time() - vectorization_start
            print(f"✓ 总共生成了 {len(keyword_embeddings)} 个keyword向量，耗时 {vectorization_time:.2f}秒")
        
        # 保存到数据库
        # tags 参数用于存储所有标签（用于搜索），但实际保存时会区分 keywords 和 yolo_objects
        all_tags = list(set(request.tags + request.keywords + request.yoloObjects))
        
        image_id = save_image_to_db(
            image_uuid=image_uuid,
            file_path=str(file_path),
            relative_path=relative_path,
            file_name=request.fileName,
            tags=all_tags,  # 所有标签，用于搜索
            keywords=request.keywords,
            description=request.description,
            clip_captions=request.clipCaptions,
            qwen_captions=request.qwenCaptions,
            yolo_objects=request.yoloObjects,
            keyword_embeddings=keyword_embeddings if keyword_embeddings else None
        )
        
        print(f"图片已保存: {file_path} (数据库 ID: {image_id})")
        
        return SaveImageResponse(
            success=True,
            uuid=image_uuid,
            file_path=str(file_path),
            relative_path=relative_path,
            message="图片保存成功"
        )
        
    except Exception as e:
        print(f"保存图片时发生错误: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"保存图片失败: {str(e)}")


# --- 搜索 API ---
@app.post("/search", response_model=SearchResponse)
async def search_images_api(request: SearchRequest):
    """从数据库搜索图片（使用向量相似度搜索）"""
    print("=" * 60)
    print("收到搜索请求!")
    print(f"请求内容: query='{request.query}', threshold={request.similarityThreshold}, limit={request.limit}")
    print("=" * 60)
    try:
        # 对查询文本进行向量化
        query_embedding = None
        if request.query and request.query.strip():
            try:
                query_embedding = encode_text_to_vector(request.query.strip())
                print(f"已生成查询向量，维度: {len(query_embedding) // 4}, 查询文本: {request.query[:50]}...")
            except Exception as e:
                print(f"向量化查询文本时出错: {e}")
                import traceback
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"向量化查询文本失败: {str(e)}")
        else:
            # 如果查询为空，返回所有图片（不使用向量搜索）
            print("查询文本为空，返回所有图片")
        
        # 验证相似度阈值
        similarity_threshold = request.similarityThreshold or 0.3
        if not 0 <= similarity_threshold <= 1:
            similarity_threshold = 0.3
        
        print(f"搜索参数: query='{request.query}', threshold={similarity_threshold}, limit={request.limit or 100}")
        
        results = search_images(
            request.query or '', 
            request.limit or 100,
            request.startDate,
            request.endDate,
            query_embedding=query_embedding,
            similarity_threshold=similarity_threshold
        )
        
        print(f"搜索结果数量: {len(results)}")
        
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
                    clipCaptions=r['clipCaptions'],
                    qwenCaptions=r['qwenCaptions'],
                    yoloObjects=r['yoloObjects'],
                    similarity=similarity_value  # 添加相似度字段
                )
            )
        
        return SearchResponse(
            success=True,
            results=image_results,
            total=len(image_results)
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
                clipCaptions=r['clipCaptions'],
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

# --- 运行服务器 ---
if __name__ == "__main__":
    # 初始化数据库
    init_database()
    
    test_qwen_connection()
    
    print(f"启动 TagLens AI 后端服务于 http://localhost:8000")
    print(f"  - Qwen 模型: {QWEN_MODEL}")
    print(f"  - Gemini 模型: {GEMINI_MODEL}")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

    
