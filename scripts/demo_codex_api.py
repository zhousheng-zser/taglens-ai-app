"""
仿造 reextract_missing_tags_gemini.py 的缺失标签补齐脚本（Codex 通道版）

说明：
- 逻辑流程与 Gemini 版保持一致：查缺失 -> MinIO 取图 -> AI 分析 -> 写回数据库/MinIO
- AI 调用方式：在本机执行 codex 指令（不再走远端 ssh/scp）
- 已支持并发处理（每张图对应一个本地 codex 进程）
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import uuid
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from dotenv import load_dotenv
from transformers import AutoModel, AutoTokenizer

PROJECT_ROOT = Path(__file__).parent.parent
backend_dir = PROJECT_ROOT / "backend"
sys.path.insert(0, str(backend_dir))

from core.database import get_images_missing_keywords, update_image_analysis_with_embeddings
from core.minio_storage_client import MinIOStorageClient
from services.business_structure_manager import get_business_manager_for_project

load_dotenv(PROJECT_ROOT / "backend" / ".env")
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()
# 强制行缓冲，确保日志实时输出到管理页流式窗口
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

BATCH_LIMIT = int(os.getenv("REEXTRACT_LIMIT", "2000"))
MAX_WORKERS = 5
BGE_MODEL_NAME = os.getenv("BGE_MODEL_NAME", "BAAI/bge-base-zh-v1.5")

_bge_tokenizer = None
_bge_model = None
_bge_device = None

# ===== 本地 Codex 配置 =====
# 在该目录执行 codex，并保存执行期间的临时图片/输出文件
LOCAL_CODEX_WORKDIR = os.getenv("CODEX_WORKDIR", str(PROJECT_ROOT / "data" / "codex_tmp"))
# 运行 codex 前注入代理（默认使用你当前要求的代理）
LOCAL_HTTP_PROXY = os.getenv("HTTP_PROXY", "http://192.168.2.245:10808")
LOCAL_HTTPS_PROXY = os.getenv("HTTPS_PROXY", "http://192.168.2.245:10808")
# 可选：指定 codex 模型；为空时使用 codex 默认模型
CODEX_MODEL = os.getenv("CODEX_MODEL", "").strip()

# --- 提示词（保持与 backend/main.py 完全一致）---
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


def build_codex_prompt(project_name: str, camera_id: str | int | None) -> str:
    """与 backend/main.py 保持一致的 Prompt 拼接逻辑。"""
    final_prompt = PROMPT_PART_1 + "\n" + PROMPT_PART_3
    if camera_id:
        try:
            bm = get_business_manager_for_project(project_name)
            c_name, c_struct = bm.get_camera_info(camera_id)
            if c_struct and c_struct != "未知区域":
                part2 = PROMPT_PART_2_TEMPLATE.format(camera_name=c_name, camera_structure=c_struct)
                final_prompt = PROMPT_PART_1 + "\n" + part2 + "\n" + PROMPT_PART_3
        except Exception as e:
            print(f"构造动态Prompt失败: {e}")
    return final_prompt


def get_bge_model() -> tuple[AutoTokenizer, AutoModel, torch.device]:
    global _bge_tokenizer, _bge_model, _bge_device
    if _bge_tokenizer is None or _bge_model is None or _bge_device is None:
        print(f"Loading BGE model: {BGE_MODEL_NAME}")
        _bge_tokenizer = AutoTokenizer.from_pretrained(BGE_MODEL_NAME)
        _bge_model = AutoModel.from_pretrained(BGE_MODEL_NAME)
        _bge_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _bge_model = _bge_model.to(_bge_device)
        _bge_model.eval()
    return _bge_tokenizer, _bge_model, _bge_device


def encode_text_to_vector(text: str) -> bytes:
    tokenizer, model, device = get_bge_model()
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        output = model(**inputs)
        embedding = output.last_hidden_state[:, 0]
        embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)
    return embedding.cpu().numpy().astype(np.float32).tobytes()


def _run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _ensure_local_workdir() -> Path:
    """确保本地 codex 工作目录存在且可写。"""
    wd = Path(LOCAL_CODEX_WORKDIR).expanduser().resolve()
    wd.mkdir(parents=True, exist_ok=True)
    test_file = wd / ".codex_write_test"
    test_file.write_text("ok", encoding="utf-8")
    test_file.unlink(missing_ok=True)
    return wd


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("远端 codex 输出为空")
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        return json.loads(raw)
    except Exception:
        # 容错：尝试提取首个 JSON 对象
        l = raw.find("{")
        r = raw.rfind("}")
        if l >= 0 and r > l:
            return json.loads(raw[l : r + 1])
        raise


def _validate_analysis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = payload.get("semantic_search")
    training = payload.get("training_data")
    if not isinstance(semantic, dict) or not isinstance(training, dict):
        raise ValueError("返回 JSON 缺少 semantic_search/training_data")

    description = semantic.get("description", "")
    keywords = semantic.get("keywords", [])
    qwen_captions = training.get("qwen_captions", {})
    yolo_objects = training.get("yolo_objects", [])

    if not isinstance(description, str):
        description = str(description)
    if not isinstance(keywords, list):
        keywords = []
    if not isinstance(qwen_captions, dict):
        qwen_captions = {}
    if not isinstance(yolo_objects, list):
        yolo_objects = []

    return {
        "semantic_search": {
            "description": description,
            "keywords": [str(k).strip() for k in keywords if str(k).strip()],
        },
        "training_data": {
            "qwen_captions": qwen_captions,
            "yolo_objects": [str(x).strip() for x in yolo_objects if str(x).strip()],
        },
    }


def analyze_image_with_codex_local(
    image_data_uri: str, source_name: str = "", prompt: str | None = None
) -> dict[str, Any]:
    """
    本地调用流程（单次）：
    1) 将 data-uri 图片写成本地临时文件
    2) 在本地工作目录执行 codex exec（先注入代理）
    3) 读取 result 文件并解析成结构化 JSON
    """
    if "," not in image_data_uri:
        raise ValueError("image_data_uri 非法")

    head, b64 = image_data_uri.split(",", 1)
    ext = ".jpg"
    if "image/png" in head:
        ext = ".png"
    elif "image/webp" in head:
        ext = ".webp"

    workdir = _ensure_local_workdir()
    local_img: Path | None = None
    local_out: Path | None = None
    try:
        base_name = Path(source_name).name if source_name else f"img_{uuid.uuid4().hex[:8]}{ext}"
        base_stem = Path(base_name).stem or f"img_{uuid.uuid4().hex[:8]}"
        unique_tag = uuid.uuid4().hex[:8]
        local_img = workdir / f"{base_stem}_{unique_tag}{ext}"
        local_out = workdir / f"{base_stem}_{unique_tag}.result.txt"
        local_img.write_bytes(base64.b64decode(b64))

        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "-i",
            str(local_img),
            "-o",
            str(local_out),
        ]
        if CODEX_MODEL:
            cmd.extend(["-m", CODEX_MODEL])
        cmd.append(prompt or (PROMPT_PART_1 + "\n" + PROMPT_PART_3))

        env = os.environ.copy()
        env["HTTP_PROXY"] = LOCAL_HTTP_PROXY
        env["HTTPS_PROXY"] = LOCAL_HTTPS_PROXY
        env["http_proxy"] = LOCAL_HTTP_PROXY
        env["https_proxy"] = LOCAL_HTTPS_PROXY

        ret = subprocess.run(
            cmd,
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if ret.returncode != 0:
            raise RuntimeError(f"本地 codex 执行失败: {(ret.stderr or ret.stdout).strip()}")
        if not local_out.exists():
            raise RuntimeError(f"本地 codex 输出文件不存在: {local_out}")

        payload = _extract_json(local_out.read_text(encoding="utf-8", errors="replace"))
        return _validate_analysis_payload(payload)
    finally:
        # 无论成功/失败都清理本地临时文件
        try:
            if local_img and local_img.exists():
                local_img.unlink()
            if local_out and local_out.exists():
                local_out.unlink()
        except Exception:
            pass


def update_database_with_analysis(
    image_id: int, analysis_result: dict[str, Any], minio_client: MinIOStorageClient | None = None
) -> None:
    semantic = analysis_result.get("semantic_search", {})
    training = analysis_result.get("training_data", {})
    description = semantic.get("description", "")
    keywords = semantic.get("keywords", [])
    qwen_captions = training.get("qwen_captions", {})
    yolo_objects = training.get("yolo_objects", [])

    if not isinstance(keywords, list):
        raise ValueError("AI 分析结果 keywords 非列表")
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    if not keywords:
        raise ValueError("AI 分析结果 keywords 为空")

    now = datetime.now().isoformat()
    relative_path = None
    image_uuid = None
    file_name = None

    keyword_embeddings: list[tuple[str, bytes]] = []
    for k in keywords:
        keyword_embeddings.append((k, encode_text_to_vector(k)))

    meta = update_image_analysis_with_embeddings(
        image_id,
        description or "",
        keywords,
        qwen_captions,
        yolo_objects,
        keyword_embeddings,
    )
    relative_path = meta.get("relative_path")
    image_uuid = meta.get("uuid")
    file_name = meta.get("file_name")
    now = meta.get("created_at") or now

    if minio_client and relative_path:
        try:
            json_path = relative_path + ".json"
            ai_analysis_json = {
                "semantic_search": {"description": description, "keywords": keywords},
                "training_data": {"qwen_captions": qwen_captions, "yolo_objects": yolo_objects},
                "metadata": {
                    "uuid": image_uuid or "",
                    "file_name": file_name,
                    "created_at": now,
                    "image_path": relative_path,
                },
            }
            minio_client.upload_file_data(
                json.dumps(ai_analysis_json, ensure_ascii=False, indent=2).encode("utf-8"),
                json_path,
                "application/json",
            )
        except Exception as e:
            print(f"  -> 警告: JSON 上传 MinIO 失败: {e}")


def batch_reextract_missing_tags_codex() -> None:
    print(f"任务启动: Codex 补齐缺失标签 (最新 {BATCH_LIMIT} 张)", flush=True)
    if shutil.which("codex") is None:
        print("缺少依赖: codex CLI", flush=True)
        print("请安装: npm install -g @openai/codex", flush=True)
        return
    print(f"本地 Codex 工作目录: {LOCAL_CODEX_WORKDIR}", flush=True)
    if CODEX_MODEL:
        print(f"Codex 模型: {CODEX_MODEL}", flush=True)
    else:
        print("Codex 模型: 使用 CLI 默认模型（可通过 CODEX_MODEL 指定）", flush=True)
    try:
        minio_client = MinIOStorageClient(skip_bucket_check=True)
    except Exception as e:
        print(f"MinIO 客户端初始化失败: {e}", flush=True)
        return

    candidates = get_images_missing_keywords(limit=BATCH_LIMIT)
    total = len(candidates)
    if total == 0:
        print("没有找到 keywords_json 为空的记录，任务无需执行", flush=True)
        return

    ok = 0
    fail = 0

    # 启动前校验本地工作目录可写
    try:
        _ensure_local_workdir()
    except Exception as e:
        print(f"本地工作目录不可用: {e}", flush=True)
        return

    def process_one(i: int, img: dict[str, Any]) -> tuple[bool, int]:
        image_id = img["id"]
        rel_path = img.get("relative_path") or ""
        camera_id = img.get("camera_id")
        image_uuid = img.get("uuid") or ""
        print(f"\n[{i+1}/{total}] 处理图片: id={image_id} uuid={image_uuid} path={rel_path}", flush=True)
        if not rel_path:
            print("  -> 失败: relative_path 为空", flush=True)
            return False, image_id
        try:
            print("  -> 下载 MinIO 图片...", flush=True)
            img_bytes = minio_client.download_file_data(rel_path)
            mime_type = "image/jpeg"
            if rel_path.lower().endswith(".png"):
                mime_type = "image/png"
            elif rel_path.lower().endswith(".webp"):
                mime_type = "image/webp"
            data_uri = f"data:{mime_type};base64,{base64.b64encode(img_bytes).decode('utf-8')}"

            project_name = "浦东道运" if "浦东道运" in rel_path else "交委指挥中心"
            final_prompt = build_codex_prompt(project_name=project_name, camera_id=camera_id)
            print("  -> 本地执行 Codex...", flush=True)
            analysis_result = analyze_image_with_codex_local(
                data_uri, source_name=rel_path, prompt=final_prompt
            )
            print("  -> 回写数据库与 MinIO JSON...", flush=True)
            update_database_with_analysis(image_id, analysis_result, minio_client)
            print("  -> 成功", flush=True)
            return True, image_id
        except Exception as e:
            print(f"  -> 失败: {e}", flush=True)
            return False, image_id

    print(f"并发执行线程数: {MAX_WORKERS}", flush=True)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_one, i, img) for i, img in enumerate(candidates)]
        for f in as_completed(futures):
            success, _ = f.result()
            if success:
                ok += 1
            else:
                fail += 1

    print(f"\n补齐完成: 成功 {ok}，失败 {fail}", flush=True)


if __name__ == "__main__":
    try:
        batch_reextract_missing_tags_codex()
    except Exception as e:
        print(f"任务执行失败: {e}", flush=True)
        sys.exit(1)
