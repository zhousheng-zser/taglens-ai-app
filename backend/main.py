# -*- coding: utf-8 -*-
import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import json
import requests
import base64
import asyncio

# 加载环境变量
load_dotenv()

# --- Pydantic 模型定义 ---
class ImageAnalysisRequest(BaseModel):
    image: str # Base64 data URI

class SemanticSearch(BaseModel):
    description: str
    keywords: list[str]

class TrainingData(BaseModel):
    clip_captions: list[str]
    yolo_objects: list[str]

class TrafficAnalysisOutput(BaseModel):
    semantic_search: SemanticSearch
    training_data: TrainingData

# --- 示例数据 ---
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
    "yolo_objects": [
      "白色-SUV-行驶中",
      "金属-护栏-道路两侧",
      "沥青-路面-干燥"
    ]
  }
}


# --- FastAPI 应用设置 ---
app = FastAPI()

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
你是一个交通视频AI分析专家。请分析这张图片，并输出严格的 JSON 格式数据。

请按照以下三个核心维度进行分析：

1. **semantic_search (语义检索核心)**:
   - **description**: 生成一段**高密度、连贯、包含所有细节**的自然语言描述。
     - 必须自然地融合以下信息：时间(从OSD读取)、地点(路名/桩号)、天气(雨/晴/阴)、光线、路面状态(潮湿/积水)、车道数、交通流量。
     - 必须详细描述基础设施：高架桥、声屏障、防眩板(颜色)、龙门架、路面文字标记(OCR内容)。
     - 必须包含OCR信息：将读取到的OSD信息和路面/路牌文字自然地写入句子中（例如"左上角OSD显示..."）。
     - 目的：这段话将被向量化，用于检索任何细节（如搜"有裂缝的路面"或"S125路段"）。
   - **keywords**: 提取 10-15 个核心关键词，覆盖场景、设施、天气、特定物体。

2. **training_data (模型训练数据)**:
   - **clip_captions**: 生成 5-6 条**精选的**、**独立的**视觉陈述句，用于 CLIP 模型微调。
     - 每一句都应该是一个独立的视角（整体场景、局部细节、特殊特征、动态目标）。
     - 必须是客观陈述，不要包含推测（如"可能..."）。
     - 句式要多样化，不要重复。
   - **yolo_objects**: 生成结构化的目标清单，格式为 "颜色-物体-状态/位置"。
     - 例如: "黑色-轿车-中间车道", "绿色-防眩板-中央隔离带"。

**请务必只输出 JSON 对象，不要包含任何其他文本或标记。**
"""

# --- Gemini API 调用 ---
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

def call_gemini_vision_api(api_key: str, image_b64: str, mime_type: str):
    """调用Gemini Vision模型进行图片分析"""
    model = "gemini-3-pro-preview"
    url = API_URL_TEMPLATE.format(model=model)
    headers = {
        'Content-Type': 'application/json',
        'X-goog-api-key': api_key
    }
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_b64
                        }
                    }
                ]
            }
        ],
         "generationConfig": {
            "response_mime_type": "application/json"
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        api_result = response.json()
        
        content_text = api_result['candidates'][0]['content']['parts'][0]['text']
        # 移除可能的 ```json ... ``` 包装 
        if content_text.strip().startswith("```json"):
            content_text = content_text.strip()[7:-3]

        return json.loads(content_text.strip())
        
    except requests.exceptions.RequestException as e:
        print(f"Error calling Vision API: {e}")
        if 'response' in locals() and response is not None:
             print(f"Response content: {response.text}")
        raise HTTPException(status_code=500, detail=f"调用Gemini Vision API时出错: {e}")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Error parsing Vision API response: {e}")
        if 'content_text' in locals():
            print(f"Raw response text: {content_text}")
        raise HTTPException(status_code=500, detail="解析AI模型返回的数据时出错")


def test_gemini_connection():
    """在启动时测试与Gemini的连接"""
    print("-" * 50)
    print("正在测试与 Gemini API 的连接...")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print(">> 警告: 未找到 GEMINI_API_KEY 环境变量。")
        print(">> 后端将只能返回模拟数据。")
        print("-" * 50)
        return

    model = "gemini-3-pro-preview"
    url = API_URL_TEMPLATE.format(model=model)
    headers = {
        'Content-Type': 'application/json',
        'X-goog-api-key': api_key
    }
    payload = {"contents": [{"parts": [{"text": "你好"}]}]}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        api_result = response.json()
        reply = api_result['candidates'][0]['content']['parts'][0]['text']
        print(f">> Gemini 连接成功！回复: \"{reply.strip()}\"")
    except requests.exceptions.RequestException as e:
        print(f">> 错误: 调用 Gemini API 失败。请检查网络或API密钥。")
        print(f">> 详细信息: {e}")
    except (KeyError, IndexError) as e:
        print(">> 错误: 从 Gemini 收到了意外的响应格式。")
        if 'response' in locals() and response is not None:
            print(f">> 原始响应: {response.text}")
    finally:
        print("-" * 50)


def extract_image_part(data_uri: str):
    """从Data URI中分离出MIME类型和Base64数据"""
    try:
        header, encoded = data_uri.split(",", 1)
        mime_type = header.split(";", 1)[0].split(":", 1)[1]
        return {"mime_type": mime_type, "data": encoded}
    except Exception as e:
        print(f"Error parsing data URI: {e}")
        raise HTTPException(status_code=400, detail="无效的图像Data URI格式")


# --- API 路由 ---
@app.post("/analyze", response_model=TrafficAnalysisOutput)
async def analyze_image(request: ImageAnalysisRequest):
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("警告: 未找到 GEMINI_API_KEY，将返回模拟数据。")
        return mock_analysis_data

    try:
        image_parts = extract_image_part(request.image)
        
        analysis_result = await asyncio.to_thread(
            call_gemini_vision_api, 
            api_key, 
            image_parts["data"], 
            image_parts["mime_type"]
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
    return {"message": "欢迎使用 TagLens AI 后端服务"}


# --- 运行服务器 ---
if __name__ == "__main__":
    test_gemini_connection()
    
    print("启动 TagLens AI 后端服务于 http://localhost:8000")
    # 注意: reload=True 会导致启动脚本运行两次
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

    