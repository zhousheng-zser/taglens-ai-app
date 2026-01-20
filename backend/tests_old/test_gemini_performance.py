# -*- coding: utf-8 -*-
"""
Gemini API 性能测试脚本
测试指定目录下所有图片的处理能力，记录每次请求的时间、token消耗等
"""
import os
import json
import asyncio
import time
import base64
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv
import requests
from collections import defaultdict

# 加载环境变量
load_dotenv()

# ============================================================================
# 配置参数（可在脚本中修改）
# ============================================================================
CONCURRENT_REQUESTS = 8  # 并发请求数量，可以修改这个值来测试不同并发度（建议范围：1-20）
TEST_DIRECTORY = "/opt/Traffic-LLM/zser/taglens-ai-app/data/local/11111"  # 测试图片目录
MAX_IMAGES = 1000  # 最多处理的图片数量，设为 None 或 0 表示处理所有图片
TEST_SINGLE_REQUEST = False  # 如果设为True，只测试第一张图片，用于快速验证API是否正常
# ============================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# 使用与 main.py 相同的 URL 配置
# 如果使用本地代理（推荐，速度快）：
API_URL_TEMPLATE = "http://192.168.2.65:8045/v1beta/models/gemini-3-flash:generateContent"
# 如果使用 Google 官方 API（需要网络连接）：
# API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

# 提示词（从 main.py 复制）
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
    - 禁止用"和"、"与"、"以及"、"并"、"还有"这样的连接词表述, 每句话只包含一个视觉元素,例如"左侧墙体设有检修口和金属栏杆，右侧墙面上方可见通风设备与照明设施。"
    - 保持客观、准确、详尽。

- semantic_search.keywords：从description中提取10-15个核心标签词汇。

- qwen_captions：用于Qwen-VL等多模态大模型的SFT微调，要求**任务导向**，每条为一个完整的问答对或指令响应，模拟真实用户可能的提问和模型的回答，可包含分析、推理、建议等内容。
    - **[弹性数量]**: 根据画面信息密度自动调整数量。简单的场景只需3-4句，复杂的场景可达7-8句。**宁缺毋滥，不要凑数**。
    - **[核心原则] 只描述"永远存在"的东西**: 假设这张图是该摄像机的"身份证"，只描述其永久属性。
    - **[严禁] 动态/瞬态信息**: 严禁包含天气(雨/晴)、光线(早晚)、具体车辆(黑色轿车)、交通状况(拥堵)。
    - **[必须] 背景环境**:描述远处的静态背景（高楼、树木、天空轮廓等）。**宁缺毋滥，没有就不要写**
    - **[必须] 道路结构**: 描述车道数、道路类型、车流固有流向等。**宁缺毋滥，没有就不要写**
    - **[必须] 基础设施**: 描述声屏障、龙门架、路灯、地面固定标线（导向箭头）等。**宁缺毋滥，没有就不要写**

    - **[必须] 基础设施**: 描述声屏障、龙门架、路灯、地面固定标线（导向箭头）等。**宁缺毋滥，没有就不要写**

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

# 支持的图片格式
SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

# 统计信息
request_stats = []  # 存储每次请求的统计信息


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


def load_image_as_data_uri(image_path: Path) -> str:
    """将图片文件加载为 base64 data URI"""
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    
    # 确定 MIME 类型
    ext = image_path.suffix.lower()
    mime_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp"
    }
    mime_type = mime_type_map.get(ext, "image/jpeg")
    
    # 编码为 base64
    base64_data = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{base64_data}"


def call_gemini_api_sync(api_key: str, data_uri: str, image_name: str) -> Dict[str, Any]:
    """同步调用 Gemini API（将在异步函数中通过线程池执行）"""
    start_time = time.time()
    
    try:
        # 构建请求 URL
        # 如果 URL 模板包含 {model}，则格式化；否则直接使用
        if "{model}" in API_URL_TEMPLATE:
            url = API_URL_TEMPLATE.format(model=GEMINI_MODEL)
        else:
            url = API_URL_TEMPLATE  # 直接使用完整URL（如本地代理）
        
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
        
        # 发送请求（设置较短的超时以便快速发现问题）
        # 注意：这里不打印URL，因为可能包含敏感信息
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                proxies=proxies,
                timeout=60  # 与主程序保持一致，60秒超时
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            raise Exception(f"API请求超时（180秒），可能网络或API服务响应缓慢")
        except requests.exceptions.ConnectionError as e:
            raise Exception(f"连接错误: {str(e)}，请检查网络连接和API地址")
        except requests.exceptions.HTTPError as e:
            raise Exception(f"HTTP错误 {response.status_code}: {str(e)}")
        result = response.json()
        
        # 计算请求耗时
        elapsed_time = time.time() - start_time
        
        # 提取 token 使用信息
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        
        if "usageMetadata" in result:
            usage = result["usageMetadata"]
            prompt_tokens = usage.get("promptTokenCount", 0)
            completion_tokens = usage.get("candidatesTokenCount", 0)
            total_tokens = usage.get("totalTokenCount", 0)
        
        # 提取响应内容（用于验证）
        content_text = ""
        if "candidates" in result and len(result["candidates"]) > 0:
            content_text = result["candidates"][0]["content"]["parts"][0]["text"]
            
            # 清理返回的文本，提取纯JSON
            if content_text and "```json" in content_text:
                content_text = content_text.split("```json")[1].split("```")[0]
            elif content_text and "```" in content_text:
                parts = content_text.split("```")
                for part in parts:
                    if "{" in part and "}" in part:
                        content_text = part
                        break
        
        return {
            "success": True,
            "image_name": image_name,
            "elapsed_time": elapsed_time,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "response_length": len(content_text),
            "error": None
        }
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        return {
            "success": False,
            "image_name": image_name,
            "elapsed_time": elapsed_time,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "response_length": 0,
            "error": str(e)
        }


async def progress_reporter(total: int):
    """定期报告进度"""
    while len(request_stats) < total:
        await asyncio.sleep(30)  # 每30秒报告一次
        completed = len(request_stats)
        if completed > 0:
            successful = sum(1 for s in request_stats if s["success"])
            failed = completed - successful
            avg_time = sum(s["elapsed_time"] for s in request_stats) / completed if completed > 0 else 0
            print(f"\n[进度报告] 已完成: {completed}/{total} ({completed/total*100:.1f}%), "
                  f"成功: {successful}, 失败: {failed}, 平均耗时: {avg_time:.2f}s\n")


async def process_images_concurrently(image_files: List[Path], api_key: str, max_concurrent: int):
    """并发处理图片列表"""
    global request_stats
    request_stats = []  # 重置统计
    semaphore = asyncio.Semaphore(max_concurrent)
    total_images = len(image_files)
    
    # 启动进度报告任务
    progress_task = asyncio.create_task(progress_reporter(total_images))
    
    async def process_one_image(image_path: Path):
        async with semaphore:
            image_name = image_path.name
            start_time_local = time.time()
            current_index = len(request_stats) + 1
            total_images = len(image_files)
            
            print(f"[{current_index}/{total_images}] 开始处理: {image_name} (时间: {time.strftime('%H:%M:%S')})")
            
            try:
                # 加载图片为 data URI
                load_start = time.time()
                data_uri = load_image_as_data_uri(image_path)
                load_time = time.time() - load_start
                print(f"[{current_index}/{total_images}] 图片加载完成: {image_name} (加载耗时: {load_time:.2f}s)")
                
                # 调用 API（使用 requests 的同步版本，通过线程池执行）
                print(f"[{current_index}/{total_images}] 开始调用API: {image_name}...")
                api_start_time = time.time()
                
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    call_gemini_api_sync,
                    api_key,
                    data_uri,
                    image_name
                )
                
                # 记录统计信息
                request_stats.append(result)
                
                if result["success"]:
                    print(f"[{current_index}/{total_images}] ✓ 成功: {image_name} - 耗时: {result['elapsed_time']:.2f}s, "
                          f"Tokens: {result['total_tokens']} (输入: {result['prompt_tokens']}, "
                          f"输出: {result['completion_tokens']})")
                else:
                    print(f"[{current_index}/{total_images}] ✗ 失败: {image_name} - 错误: {result['error']}")
                    
            except Exception as e:
                error_result = {
                    "success": False,
                    "image_name": image_name,
                    "elapsed_time": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "response_length": 0,
                    "error": str(e)
                }
                request_stats.append(error_result)
                print(f"[{current_index}/{total_images}] ✗ 异常: {image_name} - 错误: {e}")
    
    # 创建所有任务
    tasks = [process_one_image(img_path) for img_path in image_files]
    
    try:
        # 并发执行
        await asyncio.gather(*tasks)
    finally:
        # 停止进度报告
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass


def print_statistics(wall_time: float = None):
    """打印统计信息
    
    Args:
        wall_time: 墙钟时间（实际运行时间），用于计算并发后的真实吞吐量
    """
    if not request_stats:
        print("\n没有统计数据")
        return
    
    total_requests = len(request_stats)
    successful_requests = sum(1 for s in request_stats if s["success"])
    failed_requests = total_requests - successful_requests
    
    # 计算各项统计
    total_accumulated_time = sum(s["elapsed_time"] for s in request_stats)  # 累加时间
    avg_time = total_accumulated_time / total_requests if total_requests > 0 else 0
    min_time = min((s["elapsed_time"] for s in request_stats), default=0)
    max_time = max((s["elapsed_time"] for s in request_stats), default=0)
    
    total_prompt_tokens = sum(s["prompt_tokens"] for s in request_stats)
    total_completion_tokens = sum(s["completion_tokens"] for s in request_stats)
    total_tokens = sum(s["total_tokens"] for s in request_stats)
    
    avg_prompt_tokens = total_prompt_tokens / successful_requests if successful_requests > 0 else 0
    avg_completion_tokens = total_completion_tokens / successful_requests if successful_requests > 0 else 0
    avg_total_tokens = total_tokens / successful_requests if successful_requests > 0 else 0
    
    print("\n" + "=" * 80)
    print("性能测试统计报告")
    print("=" * 80)
    print(f"测试配置:")
    print(f"  - 并发数量: {CONCURRENT_REQUESTS}")
    print(f"  - 测试目录: {TEST_DIRECTORY}")
    print(f"  - 总图片数: {total_requests}")
    print(f"  - 成功数量: {successful_requests}")
    print(f"  - 失败数量: {failed_requests}")
    print(f"  - 成功率: {successful_requests/total_requests*100:.2f}%")
    print()
    print(f"单请求时间统计（不考虑并发）:")
    print(f"  - 累加总耗时: {total_accumulated_time:.2f} 秒 ({total_accumulated_time/60:.2f} 分钟)")
    print(f"  - 平均耗时: {avg_time:.2f} 秒")
    print(f"  - 最短耗时: {min_time:.2f} 秒")
    print(f"  - 最长耗时: {max_time:.2f} 秒")
    
    # 如果有墙钟时间，显示并发后的统计
    if wall_time and wall_time > 0:
        print()
        print(f"并发执行时间统计（考虑并发分摊）:")
        print(f"  - 实际运行时间（墙钟时间）: {wall_time:.2f} 秒 ({wall_time/60:.2f} 分钟)")
        print(f"  - 并发加速比: {total_accumulated_time/wall_time:.2f}x")
        print(f"  - 理论加速比（理想）: {CONCURRENT_REQUESTS:.1f}x")
        print(f"  - 并发效率: {(total_accumulated_time/wall_time)/CONCURRENT_REQUESTS*100:.1f}%")
    
    print()
    print(f"Token 统计:")
    print(f"  - 总输入 Tokens: {total_prompt_tokens:,}")
    print(f"  - 总输出 Tokens: {total_completion_tokens:,}")
    print(f"  - 总 Tokens: {total_tokens:,}")
    print(f"  - 平均输入 Tokens/图片: {avg_prompt_tokens:.0f}")
    print(f"  - 平均输出 Tokens/图片: {avg_completion_tokens:.0f}")
    print(f"  - 平均总 Tokens/图片: {avg_total_tokens:.0f}")
    print()
    
    # 计算吞吐量（基于累加时间，不考虑并发）
    if total_accumulated_time > 0:
        images_per_second_accumulated = successful_requests / total_accumulated_time
        images_per_minute_accumulated = images_per_second_accumulated * 60
        images_per_hour_accumulated = images_per_minute_accumulated * 60
        
        print(f"吞吐量统计（基于累加时间，不考虑并发）:")
        print(f"  - 每秒处理: {images_per_second_accumulated:.2f} 张图片")
        print(f"  - 每分钟处理: {images_per_minute_accumulated:.2f} 张图片")
        print(f"  - 每小时处理: {images_per_hour_accumulated:.2f} 张图片")
    
    # 计算真实吞吐量（基于墙钟时间，考虑并发）
    if wall_time and wall_time > 0:
        images_per_second_wall = successful_requests / wall_time
        images_per_minute_wall = images_per_second_wall * 60
        images_per_hour_wall = images_per_minute_wall * 60
        
        print()
        print(f"真实吞吐量统计（基于墙钟时间，考虑并发分摊）:")
        print(f"  - 每秒处理: {images_per_second_wall:.2f} 张图片")
        print(f"  - 每分钟处理: {images_per_minute_wall:.2f} 张图片")
        print(f"  - 每小时处理: {images_per_hour_wall:.2f} 张图片 ⭐")
        print()
        print(f"  💡 这是考虑并发后的实际处理能力，即把所有并发线程看做一个线程的统计结果")
    
    print("=" * 80)
    
    # 打印失败请求详情
    if failed_requests > 0:
        print("\n失败请求详情:")
        for stat in request_stats:
            if not stat["success"]:
                print(f"  - {stat['image_name']}: {stat['error']}")


def save_detailed_report():
    """保存详细报告到文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"gemini_performance_report_{timestamp}.json"
    
    report = {
        "test_config": {
            "concurrent_requests": CONCURRENT_REQUESTS,
            "test_directory": TEST_DIRECTORY,
            "gemini_model": GEMINI_MODEL,
            "timestamp": timestamp
        },
        "statistics": {
            "total_requests": len(request_stats),
            "successful_requests": sum(1 for s in request_stats if s["success"]),
            "failed_requests": sum(1 for s in request_stats if not s["success"]),
            "total_time": sum(s["elapsed_time"] for s in request_stats),
            "total_tokens": sum(s["total_tokens"] for s in request_stats),
            "total_prompt_tokens": sum(s["prompt_tokens"] for s in request_stats),
            "total_completion_tokens": sum(s["completion_tokens"] for s in request_stats)
        },
        "detailed_results": request_stats
    }
    
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n详细报告已保存到: {report_file}")


async def main():
    """主函数"""
    print("=" * 80)
    print("Gemini API 性能测试脚本")
    print("=" * 80)
    print(f"配置:")
    print(f"  - 并发数量: {CONCURRENT_REQUESTS}")
    print(f"  - 测试目录: {TEST_DIRECTORY}")
    print(f"  - Gemini 模型: {GEMINI_MODEL}")
    print()
    
    # 检查 API Key
    if not GEMINI_API_KEY or GEMINI_API_KEY == "11111":
        print("错误: 未找到有效的 GEMINI_API_KEY 环境变量")
        return
    
    # 检查测试目录
    test_dir = Path(TEST_DIRECTORY)
    if not test_dir.exists():
        print(f"错误: 测试目录不存在: {TEST_DIRECTORY}")
        return
    
    # 获取所有图片文件并按文件名排序（确保两个脚本选择相同的图片）
    all_image_files = [
        p for p in test_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS
    ]
    
    if not all_image_files:
        print(f"错误: 在目录 {TEST_DIRECTORY} 中未找到图片文件")
        return
    
    # 按文件名排序（确保顺序一致）
    image_files = sorted(all_image_files, key=lambda x: x.name)
    original_count = len(image_files)
    
    # 如果设置了测试单个请求，只处理第一张图片
    if TEST_SINGLE_REQUEST:
        print("⚠️  测试模式：只处理第一张图片")
        image_files = image_files[:1]
    # 如果设置了最大图片数量，限制处理数量（排序后再取前N张）
    elif MAX_IMAGES and MAX_IMAGES > 0:
        image_files = image_files[:MAX_IMAGES]
        print(f"⚠️  限制模式：只处理前 {MAX_IMAGES} 张图片（共找到 {original_count} 张，已排序）")
        # 显示前几张图片的文件名，用于验证
        if len(image_files) > 0:
            print(f"  前3张图片: {', '.join([f.name for f in image_files[:3]])}")
    else:
        print(f"将处理所有 {original_count} 张图片（已排序）")
    
    print(f"将处理 {len(image_files)} 张图片")
    print(f"开始测试...\n")
    
    # 记录开始时间
    start_time = time.time()
    
    # 并发处理所有图片
    await process_images_concurrently(image_files, GEMINI_API_KEY, CONCURRENT_REQUESTS)
    
    # 记录结束时间
    end_time = time.time()
    total_wall_time = end_time - start_time
    
    print(f"\n所有图片处理完成！")
    print(f"总运行时间（墙钟时间）: {total_wall_time:.2f} 秒 ({total_wall_time/60:.2f} 分钟)")
    
    # 打印统计信息（传入墙钟时间）
    print_statistics(wall_time=total_wall_time)
    
    # 保存详细报告
    save_detailed_report()


if __name__ == "__main__":
    asyncio.run(main())
