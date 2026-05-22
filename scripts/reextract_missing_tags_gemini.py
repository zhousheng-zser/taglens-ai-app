import os
import sys
import time
import json
import base64
import sqlite3
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
import httpx
import numpy as np
import requests
import torch
from openai import OpenAI
from transformers import AutoModel, AutoTokenizer

# 项目根目录: .../taglens-ai-app
PROJECT_ROOT = Path(__file__).parent.parent

# 添加 backend 目录到路径，以便导入模块
backend_dir = PROJECT_ROOT / "backend"
sys.path.insert(0, str(backend_dir))

from core.minio_storage_client import MinIOStorageClient

# 加载环境变量（backend/.env 优先）
load_dotenv(PROJECT_ROOT / "backend" / ".env")
load_dotenv()

REEXTRACT_MODEL = os.getenv("REEXTRACT_MODEL", "gemini").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "").strip()

if REEXTRACT_MODEL == "gemini" and not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY not found in environment variables.")
    exit(1)
if REEXTRACT_MODEL == "qwen" and not DASHSCOPE_API_KEY:
    print("Error: DASHSCOPE_API_KEY not found in environment variables.")
    exit(1)
if REEXTRACT_MODEL == "mimo" and not MIMO_API_KEY:
    print("Error: MIMO_API_KEY not found in environment variables.")
    exit(1)

# Gemini 配置
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-vl-max")
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5")
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")

# 批量补齐数量（可用环境变量覆盖）
BATCH_LIMIT = int(os.getenv("REEXTRACT_LIMIT", "2000"))

BGE_MODEL_NAME = os.getenv("BGE_MODEL_NAME", "BAAI/bge-base-zh-v1.5")
_bge_tokenizer = None
_bge_model = None
_bge_device = None

PROMPT = """你是一个交通视频AI分析专家。请仔细分析用户提供的图片，并严格按照我要求的JSON格式输出分析结果。JSON对象必须包含 semantic_search 和 training_data 两个键。

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
			"特殊用途区域": "公交专用道、潮汐车道、调头区、紧急停车带"
		},
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
        "description": "这是一张2025年12月24日09:03拍摄的城市高架桥监控画面。天气为阴天，光线均匀，河面平静，两岸可见高层住宅与商业建筑群。道路为双向四车道，车流方向由近及远，左侧车道车流背对镜头驶离，右侧车道车流正对镜头驶来。桥体结构为混凝土梁式桥，桥面两侧设有金属护栏与绿化带。桥下河道宽约二十米，水面呈灰绿色，两岸有步道与行道树。左上角OSD信息显示地点为'长宁桥云台'，日期为周二，时间09:03。桥面上有多辆汽车行驶，包括一辆黑色轿车在右侧车道、一辆黄色轿车在中间车道、一辆深色轿车在最右侧车道。桥体上方未见龙门架或声屏障，路面无文字标记或防眩板。远处背景为密集的城市高层建筑群，部分楼体外立面为玻璃幕墙。",
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
                "特殊用途区域": "公交专用道、调头区、紧急停车带"
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


def get_proxies():
    """从环境变量获取代理设置"""
    proxies = {}
    http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")

    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy

    return proxies if proxies else None


def get_bge_model() -> tuple[AutoTokenizer, AutoModel, torch.device]:
    """懒加载 BGE 文本向量模型"""
    global _bge_tokenizer, _bge_model, _bge_device
    if _bge_tokenizer is None or _bge_model is None or _bge_device is None:
        print(f"Loading BGE model: {BGE_MODEL_NAME}")
        _bge_tokenizer = AutoTokenizer.from_pretrained(BGE_MODEL_NAME)
        _bge_model = AutoModel.from_pretrained(BGE_MODEL_NAME)
        _bge_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _bge_model = _bge_model.to(_bge_device)
        _bge_model.eval()
        print(f"BGE model ready on {_bge_device}")
    return _bge_tokenizer, _bge_model, _bge_device


def encode_text_to_vector(text: str) -> bytes:
    """将 keyword 编码为 768 维 float32 向量字节"""
    tokenizer, model, device = get_bge_model()
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        output = model(**inputs)
        embedding = output.last_hidden_state[:, 0]
        embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)

    embedding_np = embedding.cpu().numpy().astype(np.float32)
    return embedding_np.tobytes()


def _parse_json_from_model_text(content_text: str) -> dict:
    text = content_text or ""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    return json.loads(text.strip())


def _resolve_mimo_endpoint() -> tuple[str, str, str]:
    if not MIMO_API_KEY:
        raise RuntimeError("未配置 MIMO_API_KEY")
    return MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL


def analyze_image_with_qwen(image_data_uri: str) -> dict:
    print(f"Sending request to Qwen ({QWEN_MODEL})...")
    client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=QWEN_BASE_URL, timeout=120.0)
    completion = client.chat.completions.create(
        model=QWEN_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                ],
            }
        ],
        top_p=0.8,
    )
    content_text = completion.choices[0].message.content or ""
    return _parse_json_from_model_text(content_text)


def analyze_image_with_mimo(image_data_uri: str) -> dict:
    vision_key, base_url, vision_model = _resolve_mimo_endpoint()
    url = f"{base_url.rstrip('/')}/chat/completions"
    print(f"Sending request to MiMo ({vision_model})...")
    payload = {
        "model": vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                ],
            }
        ],
        "max_completion_tokens": 4096,
        "temperature": 1.0,
        "top_p": 0.95,
        "stream": False,
    }
    headers = {"api-key": vision_key, "Content-Type": "application/json"}
    with httpx.Client(trust_env=False, timeout=120.0) as client:
        response = client.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        try:
            err_body = response.json()
            err_msg = err_body.get("error", {}).get("message", response.text)
        except Exception:
            err_msg = response.text
        raise RuntimeError(f"MiMo API 错误 ({response.status_code}): {err_msg}")
    result = response.json()
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("MiMo API 返回格式异常：无 choices")
    content_text = choices[0].get("message", {}).get("content") or ""
    return _parse_json_from_model_text(content_text)


def analyze_image_with_gemini(image_data_uri: str) -> dict:
    """调用 Gemini API 分析图片，返回解析后的 JSON 结果"""
    print(f"Sending request to Gemini ({GEMINI_MODEL})...")

    start_time = time.time()
    try:
        url = API_URL_TEMPLATE.format(model=GEMINI_MODEL)

        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": GEMINI_API_KEY,
        }

        base64_data = image_data_uri.split(",")[1]
        mime_type = image_data_uri.split(";")[0].split(":")[1]

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64_data,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {"response_mime_type": "application/json"},
        }

        proxies = get_proxies()

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            proxies=proxies,
            timeout=120,
        )
        response.raise_for_status()
        result = response.json()

        elapsed = time.time() - start_time
        print(f"Analysis complete in {elapsed:.2f} seconds.")

        content_text = ""
        if "candidates" in result and len(result["candidates"]) > 0:
            content_text = result["candidates"][0]["content"]["parts"][0]["text"]

        text = content_text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        return _parse_json_from_model_text(text)

    except Exception as e:
        print(f"API Error: {e}")
        if "response" in locals() and hasattr(response, "text"):
            print(f"Response content: {response.text}")
        raise


def analyze_image(image_data_uri: str) -> dict:
    if REEXTRACT_MODEL == "qwen":
        return analyze_image_with_qwen(image_data_uri)
    if REEXTRACT_MODEL == "mimo":
        return analyze_image_with_mimo(image_data_uri)
    return analyze_image_with_gemini(image_data_uri)


def update_database_with_analysis(
    image_id: int, analysis_result: dict, minio_client: MinIOStorageClient | None = None
) -> None:
    """将分析结果更新到数据库（只更新 analysis_results 和 tags，不更新向量），并上传 JSON 到 MinIO"""

    semantic = analysis_result.get("semantic_search", {})
    training = analysis_result.get("training_data", {})

    description = semantic.get("description", "")
    keywords = semantic.get("keywords", [])
    qwen_captions = training.get("qwen_captions", {})
    yolo_objects = training.get("yolo_objects", [])

    if not isinstance(keywords, list) or len(keywords) == 0:
        raise ValueError("AI 分析结果 keywords 为空，跳过写入")
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    if len(keywords) == 0:
        raise ValueError("AI 分析结果 keywords 清洗后为空，跳过写入")

    now = datetime.now().isoformat()

    # 相对路径: 项目根目录 / data / taglens.db
    db_path = PROJECT_ROOT / "data" / "taglens.db"

    relative_path = None
    image_uuid = None
    file_name = None

    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT relative_path, uuid, file_name FROM images WHERE id = ?",
            (image_id,),
        )
        img_row = cursor.fetchone()
        if img_row:
            relative_path = img_row["relative_path"]
            image_uuid = img_row["uuid"]
            file_name = img_row["file_name"]
        else:
            raise ValueError(f"图片 ID {image_id} 不存在于数据库中")

        cursor.execute(
            "SELECT id FROM analysis_results WHERE image_id = ?", (image_id,)
        )
        existing = cursor.fetchone()

        keywords_json_str = json.dumps(keywords, ensure_ascii=False)
        qwen_captions_json_str = json.dumps(qwen_captions, ensure_ascii=False)
        yolo_objects_json_str = json.dumps(yolo_objects, ensure_ascii=False)

        if existing:
            cursor.execute(
                """
                UPDATE analysis_results
                SET description = ?, keywords_json = ?, qwen_captions_json = ?, yolo_objects_json = ?, created_at = ?
                WHERE image_id = ?
            """,
                (
                    description or "",
                    keywords_json_str,
                    qwen_captions_json_str,
                    yolo_objects_json_str,
                    now,
                    image_id,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO analysis_results (image_id, description, keywords_json, qwen_captions_json, yolo_objects_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    image_id,
                    description or "",
                    keywords_json_str,
                    qwen_captions_json_str,
                    yolo_objects_json_str,
                    now,
                ),
            )

        # 重建关键词向量：删除旧的再插入新的
        cursor.execute("DELETE FROM keyword_embeddings WHERE image_id = ?", (image_id,))
        embedding_inserted = 0
        for k in keywords:
            try:
                embedding_bytes = encode_text_to_vector(k)
                cursor.execute(
                    """
                    INSERT INTO keyword_embeddings (image_id, keyword, embedding, created_at)
                    VALUES (?, ?, ?, ?)
                """,
                    (image_id, k, embedding_bytes, now),
                )
                embedding_inserted += 1
            except Exception as e:
                print(f"  -> 警告: keyword 向量化失败 keyword='{k}' err={e}")

        if embedding_inserted == 0:
            raise ValueError("所有 keyword 向量化都失败，跳过写入")

        cursor.execute("DELETE FROM tags WHERE image_id = ?", (image_id,))
        tags_inserted = 0
        for k in keywords:
            try:
                cursor.execute(
                    "INSERT INTO tags (image_id, tag, tag_type) VALUES (?, ?, ?)",
                    (image_id, k, "keyword"),
                )
                tags_inserted += 1
            except sqlite3.IntegrityError:
                pass
        for o in yolo_objects:
            try:
                cursor.execute(
                    "INSERT INTO tags (image_id, tag, tag_type) VALUES (?, ?, ?)",
                    (image_id, o, "yolo_object"),
                )
                tags_inserted += 1
            except sqlite3.IntegrityError:
                pass

        conn.commit()
        print(
            f"  -> 成功: 已提交到数据库 keywords={len(keywords)} embeddings={embedding_inserted} tags={tags_inserted}"
        )

        verify_cursor = conn.cursor()
        verify_cursor.execute(
            """
            SELECT image_id, keywords_json
            FROM analysis_results
            WHERE image_id = ?
        """,
            (image_id,),
        )
        verify_row = verify_cursor.fetchone()
        if verify_row:
            verify_keywords = json.loads(verify_row["keywords_json"] or "[]")
            print(
                f"  -> [验证] 查询成功: image_id={verify_row['image_id']}, keywords数量={len(verify_keywords)}"
            )
        else:
            print(
                f"  -> [错误] 验证失败: 查询不到 image_id={image_id} 的记录"
            )

    except Exception as e:
        conn.rollback()
        print(f"  -> [错误] 数据库操作失败: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        conn.close()

    if minio_client and relative_path:
        try:
            json_path = relative_path + ".json"

            ai_analysis_json = {
                "semantic_search": {
                    "description": description,
                    "keywords": keywords,
                },
                "training_data": {
                    "qwen_captions": qwen_captions,
                    "yolo_objects": yolo_objects,
                },
                "metadata": {
                    "uuid": image_uuid or "",
                    "file_name": file_name,
                    "created_at": now,
                    "image_path": relative_path,
                },
            }

            json_bytes = json.dumps(
                ai_analysis_json, ensure_ascii=False, indent=2
            ).encode("utf-8")

            minio_client.upload_file_data(json_bytes, json_path, "application/json")
            print(f"  -> 成功: JSON 文件已上传到 MinIO: {json_path}")
        except Exception as e:
            print(f"  -> 警告: JSON 文件上传到 MinIO 失败: {e}")


def get_images_missing_keywords(limit: int = 2000) -> list[dict]:
    """查询 keywords_json 为空的最新图片列表（直接连接数据库，避免触发 MinIO 同步）"""

    db_path = PROJECT_ROOT / "data" / "taglens.db"
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                i.id,
                i.uuid,
                i.relative_path,
                i.file_name,
                i.created_at,
                ar.keywords_json
            FROM images i
            LEFT JOIN analysis_results ar ON i.id = ar.image_id
            WHERE ar.keywords_json IS NULL OR TRIM(ar.keywords_json) = '[]'
            ORDER BY i.created_at DESC
            LIMIT ?
        """,
            (limit,),
        )
        results = [dict(row) for row in cursor.fetchall()]
        return results
    finally:
        conn.close()


def batch_reextract_missing_tags() -> None:
    """批量补齐缺失标签"""
    model_label = {
        "gemini": GEMINI_MODEL,
        "qwen": QWEN_MODEL,
        "mimo": MIMO_MODEL,
    }.get(REEXTRACT_MODEL, REEXTRACT_MODEL)
    print(
        f"任务启动: 补齐缺失标签 (最新 {BATCH_LIMIT} 张, 模型: {REEXTRACT_MODEL}/{model_label})"
    )

    print("正在初始化 MinIO 客户端...")
    try:
        minio_client = MinIOStorageClient(skip_bucket_check=True)
        print("MinIO 客户端连接成功")
    except Exception as e:
        print(f"MinIO 客户端初始化失败: {e}")
        return

    print("正在查询缺失标签的最新图片列表...")
    candidates = get_images_missing_keywords(limit=BATCH_LIMIT)
    total = len(candidates)

    if total == 0:
        print("没有找到 keywords_json 为空的记录，任务无需执行")
        return

    print(f"待补齐记录数: {total}")

    def process_one(index: int, img: dict) -> tuple[bool, int]:
        """在线程中处理单张图片"""
        image_id = img["id"]
        rel_path = img.get("relative_path") or ""
        uuid = img.get("uuid") or ""

        print(
            f"\n[{index+1}/{total}] 处理图片: id={image_id} uuid={uuid} path={rel_path}"
        )

        if not rel_path:
            print("  -> 失败: relative_path 为空")
            return False, image_id

        try:
            print("  -> 正在从 MinIO 下载图片...")
            img_bytes = minio_client.download_file_data(rel_path)

            mime_type = "image/jpeg"
            if rel_path.lower().endswith(".png"):
                mime_type = "image/png"
            elif rel_path.lower().endswith(".webp"):
                mime_type = "image/webp"

            data_uri = (
                f"data:{mime_type};base64,"
                f"{base64.b64encode(img_bytes).decode('utf-8')}"
            )

            print(f"  -> 正在调用 {REEXTRACT_MODEL} API...")
            analysis_result = analyze_image(data_uri)

            print("  -> 正在更新数据库...")
            update_database_with_analysis(image_id, analysis_result, minio_client)

            return True, image_id
        except Exception as e:
            print(f"  -> 失败: {e}")
            return False, image_id

    ok = 0
    fail = 0

    # 使用 5 个线程并行处理
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_index: dict = {}
        for i, img in enumerate(candidates):
            future = executor.submit(process_one, i, img)
            future_to_index[future] = i

        for future in as_completed(future_to_index):
            success, _image_id = future.result()
            if success:
                ok += 1
            else:
                fail += 1

    print(f"\n补齐完成: 成功 {ok}，失败 {fail}")


if __name__ == "__main__":
    batch_reextract_missing_tags()
