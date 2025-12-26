# -*- coding: utf-8 -*-
import os
import json
import time
import base64
import argparse
import mimetypes
import concurrent.futures
from threading import Lock
from datetime import datetime
from openai import OpenAI

# 默认配置
DEFAULT_MODEL = "qwen-vl-flash"
# 北京地域的兼容Endpoint
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


# V5.1 交通视频全景分析提示词
SYSTEM_PROMPT = """
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

# 线程锁，用于安全的控制台打印
print_lock = Lock()

def get_image_files(directory):
    """获取目录下的所有图片文件"""
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.heic'}
    image_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if os.path.splitext(file)[1].lower() in image_extensions:
                image_files.append(os.path.join(root, file))
    return image_files

def image_to_data_uri(image_path):
    """将本地图片文件转换为Base64 Data URI"""
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type or not mime_type.startswith('image'):
        raise ValueError(f"无法确定文件类型或文件不是图片: {image_path}")
    
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    
    return f"data:{mime_type};base64,{encoded_string}"


def call_qwen_api(api_key, image_path, model):
    """调用通义千问多模态API (OpenAI兼容模式)"""
    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    
    try:
        data_uri = image_to_data_uri(image_path)
        
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": SYSTEM_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
            top_p=0.8
        )
        return completion

    except Exception as e:
        with print_lock:
            print(f"Error calling API for {image_path}: {e}")
        return None

def process_single_image(img_path, api_key, model, idx, total):
    """处理单个图片，包括API调用和结果保存"""
    file_name = os.path.basename(img_path)
    with print_lock:
        print(f"[{idx}/{total}] Starting analysis: {file_name}")
    
    start_time = time.time()
    
    result = call_qwen_api(api_key, img_path, model)

    end_time = time.time()
    
    if result and result.choices:
        try:
            content_text = result.choices[0].message.content
            
            # 清理返回的文本，提取纯JSON
            if "```json" in content_text:
                content_text = content_text.split("```json")[1].split("```")[0]
            
            parsed_json = json.loads(content_text.strip())
            
            usage_metadata = result.usage
            
            final_output = {
                "file_name": file_name,
                "file_path": img_path,
                "analysis_result": parsed_json,
                "metadata": {
                    "model": result.model,
                    "api": "qwen-openai-compatible",
                    "created_at": datetime.now().isoformat(),
                    "processing_time_seconds": round(end_time - start_time, 2),
                    "token_usage": {
                        "prompt_tokens": usage_metadata.prompt_tokens if usage_metadata else 0,
                        "response_tokens": usage_metadata.completion_tokens if usage_metadata else 0,
                        "total_tokens": usage_metadata.total_tokens if usage_metadata else 0,
                    },
                    "request_id": result.id
                }
            }
            
            json_path = os.path.splitext(img_path)[0] + ".json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(final_output, f, ensure_ascii=False, indent=2)
            
            with print_lock:
                print(f"  -> ✅ Saved: {os.path.basename(json_path)} ({round(end_time - start_time, 1)}s)")
            return True
            
        except (json.JSONDecodeError, KeyError, IndexError, AttributeError) as e:
            with print_lock:
                print(f"  -> ❌ JSON/Parsing Error for {file_name}: {e}")
                if 'content_text' in locals():
                    print(f"     Raw response: {content_text}")
            return False
    else:
        with print_lock:
            print(f"  -> ❌ Failed: {file_name}")
            if result:
                print(f"     API Response: {result}")
        return False

def process_images(input_path, api_key, limit=None, model=DEFAULT_MODEL, workers=4):
    """并发处理图片目录或单个文件"""
    if os.path.isfile(input_path):
        image_files = [input_path]
        print(f"Processing single file: {input_path}...")
    else:
        image_files = get_image_files(input_path)
        if limit:
            image_files = image_files[:limit]
            print(f"Processing {limit} images from {input_path}...")
        else:
            print(f"Processing all {len(image_files)} images from {input_path}...")

    if not image_files:
        print("No image files found.")
        return

    print(f"🚀 Starting concurrent processing with {workers} workers using model: {model}...")
    
    success_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_file = {
            executor.submit(process_single_image, img_path, api_key, model, i+1, len(image_files)): img_path 
            for i, img_path in enumerate(image_files)
        }
        
        for future in concurrent.futures.as_completed(future_to_file):
            try:
                if future.result():
                    success_count += 1
            except Exception as exc:
                with print_lock:
                    print(f'  -> ❌ Generated an exception: {exc}')

    print(f"\nDone! Successfully processed {success_count}/{len(image_files)} images.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch process images with Alibaba Qwen (DashScope) API using OpenAI compatible mode.")
    parser.add_argument("input_path", help="Path to the image directory or a single image file")
    parser.add_argument("--key", required=False, help="Alibaba DashScope API Key. Can also be set via DASHSCOPE_API_KEY environment variable.")
    parser.add_argument("--limit", type=int, help="Number of images to process")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model name. Default: {DEFAULT_MODEL}")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent threads (default: 4)")
    
    args = parser.parse_args()
    
    api_key = args.key or os.getenv("DASHSCOPE_API_KEY")

    if not api_key or api_key == "11111":
        print("Error: API key not provided or is default. Use --key argument or set DASHSCOPE_API_KEY environment variable.")
    elif not os.path.exists(args.input_path):
        print(f"Error: Path '{args.input_path}' not found.")
    else:
        # 自动安装依赖
        try:
            import openai
        except ImportError:
            print("openai library not found. Installing...")
            import subprocess
            import sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", "openai"])
            print("openai installed successfully.")

        process_images(args.input_path, api_key, args.limit, args.model, args.workers)

    