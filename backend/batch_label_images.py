# -*- coding: utf-8 -*-
import os
import json
import time
import base64
import argparse
import requests
import mimetypes
import urllib.request
from datetime import datetime

# 尝试修复 SSL 代理报错 (ValueError: check_hostname requires server_hostname)
# 这是一个常见的 urllib3/requests 兼容性问题，通常发生在代理 URL 为 https:// 时
try:
    proxies = urllib.request.getproxies()
    print(f"Detected system proxies: {proxies}")
    
    # 强制将 https 代理协议改为 http，这通常能解决 SSL 握手错误且不影响翻墙
    if 'https' in proxies and proxies['https'].startswith('https://'):
        new_proxy = proxies['https'].replace('https://', 'http://')
        print(f"Applying proxy workaround: Changing HTTPS proxy from {proxies['https']} to {new_proxy}")
        os.environ['HTTPS_PROXY'] = new_proxy
        os.environ['https_proxy'] = new_proxy
except Exception as e:
    print(f"Warning: Failed to apply proxy workaround: {e}")

# 默认配置
DEFAULT_MODEL = "gemini-1.5-flash-latest" # 使用免费额度更高的模型
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# V5.1 交通视频全景分析提示词 (All-in-Vector 策略)
# 核心理念：
# 1. 语义检索 (Semantic Search): 将所有结构化信息（OCR、天气、设施）自然融合进长文本描述，利用向量检索的灵活性，不做过度结构化。
# 2. CLIP微调 (CLIP Fine-tuning): 生成精选的、低噪音的、多视角的视觉陈述句，而非冗余的流水账。
# 3. YOLO挖掘 (Object Mining): 保留结构化目标清单，用于自动化样本筛选。

SYSTEM_PROMPT = """
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

**输出格式示例 (JSON Only):**
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
"""

def get_image_files(directory):
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.heic'}
    image_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if os.path.splitext(file)[1].lower() in image_extensions:
                image_files.append(os.path.join(root, file))
    return image_files

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def call_gemini_api(api_key, image_path, model):
    url = API_URL_TEMPLATE.format(model=model)
    headers = {
        'Content-Type': 'application/json',
        'X-goog-api-key': api_key
    }
    
    mime_type = mimetypes.guess_type(image_path)[0] or 'image/jpeg'
    image_data = encode_image(image_path)
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": SYSTEM_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_data
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
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error calling API for {image_path}: {e}")
        if response is not None:
             print(f"Response content: {response.text}")
        return None

import concurrent.futures
from threading import Lock

# 线程锁，用于安全的控制台打印
print_lock = Lock()

def process_single_image(img_path, api_key, model, idx, total):
    file_name = os.path.basename(img_path)
    with print_lock:
        print(f"[{idx}/{total}] Starting analysis: {file_name}")
    
    start_time = time.time()
    # 简单的重试机制
    max_retries = 3
    result = None
    
    for attempt in range(max_retries):
        result = call_gemini_api(api_key, img_path, model)
        if result and 'candidates' in result:
            break
        elif result and 'error' in result and result['error'].get('code') == 429:
            # 遇到限流 (Rate Limit)，等待后重试
            wait_time = (attempt + 1) * 5
            with print_lock:
                print(f"  -> Rate limit hit for {file_name}, waiting {wait_time}s...")
            time.sleep(wait_time)
        else:
            # 其他错误，不重试
            break

    end_time = time.time()
    
    if result and 'candidates' in result:
        try:
            content_text = result['candidates'][0]['content']['parts'][0]['text']
            if content_text.startswith("```json"):
                content_text = content_text.replace("```json", "").replace("```", "")
            
            parsed_json = json.loads(content_text)
            
            # 提取 Token 使用情况
            usage_metadata = result.get('usageMetadata', {})
            
            final_output = {
                "file_name": file_name,
                "file_path": img_path,
                "analysis_result": parsed_json,
                "metadata": {
                    "model": model,
                    "api_version": "v1beta",
                    "created_at": datetime.now().isoformat(),
                    "processing_time_seconds": round(end_time - start_time, 2),
                    "token_usage": {
                        "prompt_tokens": usage_metadata.get('promptTokenCount', 0),
                        "response_tokens": usage_metadata.get('candidatesTokenCount', 0),
                        "total_tokens": usage_metadata.get('totalTokenCount', 0)
                    }
                }
            }
            
            json_path = os.path.splitext(img_path)[0] + ".json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(final_output, f, ensure_ascii=False, indent=2)
            
            with print_lock:
                print(f"  -> ✅ Saved: {os.path.basename(json_path)} ({round(end_time - start_time, 1)}s)")
            return True
            
        except json.JSONDecodeError:
            with print_lock:
                print(f"  -> ❌ JSON Error: {file_name}")
            return False
    else:
        with print_lock:
            print(f"  -> ❌ Failed: {file_name}")
        return False

def process_images(input_path, api_key, limit=None, model=DEFAULT_MODEL, workers=4):
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

    print(f"🚀 Starting concurrent processing with {workers} workers...")
    
    success_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        # 提交所有任务
        future_to_file = {
            executor.submit(process_single_image, img_path, api_key, model, i+1, len(image_files)): img_path 
            for i, img_path in enumerate(image_files)
        }
        
        # 等待完成
        for future in concurrent.futures.as_completed(future_to_file):
            if future.result():
                success_count += 1

    print(f"\nDone! Successfully processed {success_count}/{len(image_files)} images.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch process images with Gemini API for traffic analysis.")
    parser.add_argument("input_path", help="Path to the image directory or a single image file")
    parser.add_argument("--key", required=True, help="Google Gemini API Key")
    parser.add_argument("--limit", type=int, help="Number of images to process")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model name. Recommended: 'gemini-1.5-flash-latest', 'gemini-pro-vision'. Default: {DEFAULT_MODEL}")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent threads (default: 4)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input_path):
        print(f"Error: Path '{args.input_path}' not found.")
    else:
        process_images(args.input_path, args.key, args.limit, args.model, args.workers)


    