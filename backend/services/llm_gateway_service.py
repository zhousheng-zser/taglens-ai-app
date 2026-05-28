"""统一 LLM 网关：千问 / Gemini / Codex / MiMo 视觉分析。"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import httpx
import requests
from openai import OpenAI

from services.llm_prompts import build_default_analysis_prompt

LLMProviderName = Literal["qwen", "gemini", "codex", "mimo"]
SUPPORTED_PROVIDERS: tuple[str, ...] = ("qwen", "gemini", "codex", "mimo")

QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-vl-max")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5")
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
GEMINI_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

CODEX_LOCAL_WORKDIR = os.getenv(
    "CODEX_WORKDIR", str(Path(__file__).resolve().parent.parent.parent / "data" / "codex_tmp")
)
CODEX_LOCAL_HTTP_PROXY = os.getenv("HTTP_PROXY", "http://192.168.2.245:10808")
CODEX_LOCAL_HTTPS_PROXY = os.getenv("HTTPS_PROXY", "http://192.168.2.245:10808")
CODEX_MODEL = os.getenv("CODEX_MODEL", "").strip()

MOCK_ANALYSIS_DATA: Dict[str, Any] = {
    "semantic_search": {"description": "", "keywords": []},
    "training_data": {"yolo_objects": [], "qwen_captions": {}},
}


class LLMGatewayError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalize_provider(provider: str) -> LLMProviderName:
    name = (provider or "").strip().lower()
    if name not in SUPPORTED_PROVIDERS:
        raise LLMGatewayError(f"不支持的模型提供商: {provider}", status_code=400)
    return name  # type: ignore[return-value]


def _resolve_qwen_api_key() -> Optional[str]:
    return (os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip() or None


def _resolve_gemini_api_key() -> Optional[str]:
    return (os.getenv("GEMINI_API_KEY") or "").strip() or None


def _resolve_mimo_api_key() -> Optional[str]:
    return (os.getenv("MIMO_API_KEY") or "").strip() or None


def _get_proxies() -> Optional[dict[str, str]]:
    proxies: dict[str, str] = {}
    http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies or None


def _parse_json_from_model_text(content_text: str) -> dict[str, Any]:
    text = (content_text or "").strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        parts = text.split("```")
        for part in parts:
            if "{" in part and "}" in part:
                text = part
                break
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        left = text.find("{")
        right = text.rfind("}")
        if left >= 0 and right > left:
            return json.loads(text[left : right + 1])
        raise


def _call_qwen(api_key: str, data_uri: str, prompt: str) -> dict[str, Any]:
    client = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=120.0)
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
        top_p=0.8,
    )
    content_text = completion.choices[0].message.content or ""
    try:
        log_path = Path(__file__).resolve().parent.parent.parent / "B_qwen_response.txt"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*40}\nQwen response at {datetime.now().isoformat()}:\n")
            f.write(content_text[:800])
            f.write("\n")
    except Exception:
        pass
    return _parse_json_from_model_text(content_text)


def _call_mimo(api_key: str, data_uri: str, prompt: str) -> dict[str, Any]:
    url = f"{MIMO_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": MIMO_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
        "max_completion_tokens": 4096,
        "temperature": 1.0,
        "top_p": 0.95,
        "stream": False,
    }
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    with httpx.Client(trust_env=False, timeout=120.0) as client:
        response = client.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        try:
            err_body = response.json()
            err_msg = err_body.get("error", {}).get("message", response.text)
        except Exception:
            err_msg = response.text
        raise LLMGatewayError(f"MiMo API 错误 ({response.status_code}): {err_msg}")
    result = response.json()
    choices = result.get("choices") or []
    if not choices:
        raise LLMGatewayError("MiMo API 返回格式异常：无 choices")
    content_text = choices[0].get("message", {}).get("content") or ""
    return _parse_json_from_model_text(content_text)


def _call_gemini(api_key: str, data_uri: str, prompt: str) -> dict[str, Any]:
    url = GEMINI_API_URL_TEMPLATE.format(model=GEMINI_MODEL)
    headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
    if "," not in data_uri:
        raise LLMGatewayError("无效图片 data URI", status_code=400)
    base64_data = data_uri.split(",", 1)[1]
    mime_type = "image/jpeg"
    if data_uri.startswith("data:image/png"):
        mime_type = "image/png"
    elif data_uri.startswith("data:image/webp"):
        mime_type = "image/webp"
    elif data_uri.startswith("data:image/gif"):
        mime_type = "image/gif"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": base64_data}},
                ]
            }
        ],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    response = requests.post(
        url, headers=headers, json=payload, proxies=_get_proxies(), timeout=120
    )
    try:
        log_path = Path(__file__).resolve().parent.parent.parent / "A_gemini_response.txt"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(
                f"\n{'='*40}\nGemini HTTP {response.status_code} at {datetime.now().isoformat()}:\n"
            )
            f.write(response.text[:800])
            f.write("\n")
    except Exception:
        pass
    response.raise_for_status()
    result = response.json()
    if "candidates" in result and result["candidates"]:
        content_text = result["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json_from_model_text(content_text)
    raise LLMGatewayError("Gemini API 返回格式异常")


def _run_cmd(cmd: list[str], cwd: str | None = None, env: dict[str, str] | None = None):
    return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=cwd, env=env)


def _ensure_codex_workdir() -> Path:
    wd = Path(CODEX_LOCAL_WORKDIR).expanduser().resolve()
    wd.mkdir(parents=True, exist_ok=True)
    test_file = wd / ".codex_write_test"
    test_file.write_text("ok", encoding="utf-8")
    test_file.unlink(missing_ok=True)
    return wd


def _normalize_codex_payload(payload: dict[str, Any]) -> dict[str, Any]:
    semantic = payload.get("semantic_search")
    training = payload.get("training_data")
    if not isinstance(semantic, dict) or not isinstance(training, dict):
        raise LLMGatewayError("Codex 返回缺少 semantic_search 或 training_data")
    description = semantic.get("description", "")
    keywords = semantic.get("keywords", [])
    qwen_captions = training.get("qwen_captions", {})
    yolo_objects = training.get("yolo_objects", [])
    return {
        "semantic_search": {
            "description": str(description),
            "keywords": [str(k).strip() for k in keywords if str(k).strip()],
        },
        "training_data": {
            "qwen_captions": qwen_captions if isinstance(qwen_captions, (dict, list)) else {},
            "yolo_objects": [str(x).strip() for x in yolo_objects if str(x).strip()],
        },
    }


def _call_codex(data_uri: str, prompt: str) -> dict[str, Any]:
    if "," not in data_uri:
        raise LLMGatewayError("无效图片 data URI", status_code=400)
    if shutil.which("codex") is None:
        raise LLMGatewayError("缺少依赖 codex CLI")
    head, b64 = data_uri.split(",", 1)
    ext = ".jpg"
    if "image/png" in head:
        ext = ".png"
    elif "image/webp" in head:
        ext = ".webp"
    elif "image/gif" in head:
        ext = ".gif"
    workdir = _ensure_codex_workdir()
    local_img: Path | None = None
    local_out: Path | None = None
    try:
        unique = uuid.uuid4().hex[:10]
        local_img = workdir / f"img_{unique}{ext}"
        local_out = workdir / f"img_{unique}.result.txt"
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
        cmd.append(prompt)
        env = os.environ.copy()
        env["HTTP_PROXY"] = CODEX_LOCAL_HTTP_PROXY
        env["HTTPS_PROXY"] = CODEX_LOCAL_HTTPS_PROXY
        env["http_proxy"] = CODEX_LOCAL_HTTP_PROXY
        env["https_proxy"] = CODEX_LOCAL_HTTPS_PROXY
        ret = _run_cmd(cmd, cwd=str(workdir), env=env)
        if ret.returncode != 0:
            raise LLMGatewayError(f"本地 codex 执行失败: {(ret.stderr or ret.stdout).strip()}")
        if not local_out.exists():
            raise LLMGatewayError(f"本地 codex 输出文件不存在: {local_out}")
        payload = _parse_json_from_model_text(
            local_out.read_text(encoding="utf-8", errors="replace")
        )
        return _normalize_codex_payload(payload)
    finally:
        for p in (local_img, local_out):
            try:
                if p and p.exists():
                    p.unlink()
            except Exception:
                pass


def infer_traffic_image(
    provider: str,
    image_data_uri: str,
    prompt: Optional[str] = None,
    *,
    allow_mock: bool = True,
    camera_name: Optional[str] = None,
    camera_structure: Optional[str] = None,
) -> tuple[dict[str, Any], bool]:
    """
    统一视觉推理入口。
    返回 (analysis_dict, is_mock)。
    """
    normalized = normalize_provider(provider)
    if not (image_data_uri or "").strip():
        raise LLMGatewayError("image 不能为空", status_code=400)

    final_prompt = (prompt or "").strip() or build_default_analysis_prompt(
        camera_name=camera_name,
        camera_structure=camera_structure,
    )

    if normalized == "qwen":
        api_key = _resolve_qwen_api_key()
        if not api_key:
            if allow_mock:
                return dict(MOCK_ANALYSIS_DATA), True
            raise LLMGatewayError("未配置 QWEN_API_KEY / DASHSCOPE_API_KEY")
        return _call_qwen(api_key, image_data_uri, final_prompt), False

    if normalized == "gemini":
        api_key = _resolve_gemini_api_key()
        if not api_key:
            if allow_mock:
                return dict(MOCK_ANALYSIS_DATA), True
            raise LLMGatewayError("未配置 GEMINI_API_KEY")
        return _call_gemini(api_key, image_data_uri, final_prompt), False

    if normalized == "mimo":
        api_key = _resolve_mimo_api_key()
        if not api_key:
            raise LLMGatewayError("未配置 MIMO_API_KEY")
        return _call_mimo(api_key, image_data_uri, final_prompt), False

    if normalized == "codex":
        return _call_codex(image_data_uri, final_prompt), False

    raise LLMGatewayError(f"不支持的模型提供商: {provider}", status_code=400)


def test_qwen_connection() -> None:
    """启动时测试 DashScope 连接。"""
    api_key = _resolve_qwen_api_key()
    if not api_key:
        print(">> 警告: 未找到 QWEN_API_KEY / DASHSCOPE_API_KEY，部分功能将返回模拟数据。")
        return
    try:
        client = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=30.0)
        client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        print(">> DashScope API 连接测试成功")
    except Exception as exc:
        print(f">> DashScope API 连接测试失败: {exc}")
