# -*- coding: utf-8 -*-
import os
import uvicorn
import json
import asyncio
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

# 加载环境变量
load_dotenv()

# --- 模型和API定义 ---
# 使用通义千问视觉语言模型 (兼容OpenAI API)
VISION_MODEL = "qwen-vl-max"
TEXT_MODEL = "qwen-plus"
# 北京地域的兼容Endpoint
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

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
你是一个交通视频AI分析专家。请仔细分析用户提供的图片，并严格按照我要求的JSON格式输出分析结果。JSON对象必须包含 semantic_search 和 training_data 两个键。

**输出格式示例 (严格遵循此JSON结构):**
```json
{
  "semantic_search": {
    "description": "这是一张2025年12月24日07:03拍摄的S125北青线高架桥监控画面。天气为雨天，光线较暗，沥青路面潮湿且有明显的积水反光。道路为双向六车道，交通流量中等。画面特征包括：路面上印有巨大的白色'高架'和'闭'字样导向标记，道路中央安装了绿色的连续防眩板，两侧有灰色的声屏障。左上角OSD信息显示桩号为K21+900，方向为上行。一辆黑色轿车正在中间车道行驶，尾灯亮起。",
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
    "yolo_objects": [
      "黑色-轿车-中间车道",
      "绿色-防眩板-中央",
      "白色-文字标记-路面"
    ]
  }
}
```

请根据以上规则分析图片并生成JSON。
"""

def get_qwen_client(api_key: str):
    """获取通义千问OpenAI兼容客户端"""
    return OpenAI(api_key=api_key, base_url=BASE_URL)

# --- Qwen API 调用 ---
def call_qwen_vision_api(api_key: str, data_uri: str):
    """调用通义千问视觉模型进行图片分析"""
    client = get_qwen_client(api_key)
    try:
        completion = client.chat.completions.create(
            model=VISION_MODEL,
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


def test_qwen_connection():
    """在启动时测试与通义千问的连接"""
    print("-" * 50)
    print("正在测试与通义千问 (DashScope) API 的连接...")
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key or api_key == "11111":
        print(">> 警告: 未找到或未配置有效的 DASHSCOPE_API_KEY 环境变量。")
        print(">> 后端将只能返回模拟数据。")
        print("-" * 50)
        return
    
    try:
        client = get_qwen_client(api_key)
        completion = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': '你好, 你能看见这段文字吗？'}
            ]
        )
        reply = completion.choices[0].message.content
        print(f">> 通义千问 ({TEXT_MODEL}) 连接成功！回复: \"{reply.strip()}\"")

    except Exception as e:
        print(f">> 错误: 调用通义千问 API 失败。请检查网络或API密钥。")
        print(f">> 详细信息: {e}")
    finally:
        print("-" * 50)


# --- API 路由 ---
@app.post("/analyze", response_model=TrafficAnalysisOutput)
async def analyze_image(request: ImageAnalysisRequest):
    api_key = os.getenv("DASHSCOPE_API_KEY")

    if not api_key or api_key == "11111":
        print("警告: 未找到有效的 DASHSCOPE_API_KEY，将返回模拟数据。")
        await asyncio.sleep(1) # 模拟处理时间
        return mock_analysis_data

    try:
        # 使用 to_thread 避免阻塞事件循环
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


# --- 运行服务器 ---
if __name__ == "__main__":
    test_qwen_connection()
    
    print(f"启动 TagLens AI 后端服务于 http://localhost:8000 (模型: {VISION_MODEL})")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

    
