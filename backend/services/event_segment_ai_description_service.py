"""事件分段 AI 描述：HTTP 拉取媒体 + QRL 多模态（流式采集 thinking，与 answer 合并后返回，不落盘）。"""
from __future__ import annotations

import base64
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from openai import OpenAI

from prompts.event_segment_prompt import PROMPT, PROMPT_IMAGE_FOCUS_SUFFIX
from services.segment_media_validator import (
    VideoDamageReport,
    analyze_segment_video_bytes,
    is_playability_check_enabled,
)

MAX_WORKERS = 15
_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="segment-ai")

EVENT_SEGMENT_AI_BASE_URL = os.getenv(
    "EVENT_SEGMENT_AI_BASE_URL",
    "http://192.168.11.148:6006/v1",
)
EVENT_SEGMENT_AI_API_KEY = os.getenv("EVENT_SEGMENT_AI_API_KEY", "EMPTY")
EVENT_SEGMENT_AI_MODEL = os.getenv("EVENT_SEGMENT_AI_MODEL", "models/QRL")
EVENT_SEGMENT_AI_TIMEOUT_SEC = float(os.getenv("EVENT_SEGMENT_AI_TIMEOUT_SEC", "600"))

EVENT_MEDIA_HTTP_ORIGIN = os.getenv("EVENT_MEDIA_HTTP_ORIGIN", "http://127.0.0.1:9002").rstrip("/")
EVENT_MEDIA_FETCH_TIMEOUT_SEC = float(os.getenv("EVENT_MEDIA_FETCH_TIMEOUT_SEC", "120"))
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "bucket-taglens")

THINKING_ANSWER_SEPARATOR = "------------"


def build_public_media_url(path: Optional[str]) -> str:
    """将 DB/MinIO 相对路径转为与前端页面一致的 HTTP 直链。"""
    raw = (path or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("/"):
        return f"{EVENT_MEDIA_HTTP_ORIGIN}{raw}"
    if raw.startswith(f"{MINIO_BUCKET}/"):
        return f"{EVENT_MEDIA_HTTP_ORIGIN}/{raw}"
    return f"{EVENT_MEDIA_HTTP_ORIGIN}/{MINIO_BUCKET}/{raw.lstrip('/')}"


class SegmentAiMediaError(Exception):
    """媒体 HTTP 拉取失败。"""


class SegmentAiModelError(Exception):
    """视觉模型调用失败。"""


def get_executor() -> ThreadPoolExecutor:
    return _EXECUTOR


def _resolve_media_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise SegmentAiMediaError("媒体 URL 为空")
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https"):
        return raw
    if raw.startswith("/"):
        return f"{EVENT_MEDIA_HTTP_ORIGIN}{raw}"
    return urljoin(f"{EVENT_MEDIA_HTTP_ORIGIN}/", raw)


def _fetch_media_bytes(url: str) -> tuple[bytes, str]:
    resolved = _resolve_media_url(url)
    try:
        with httpx.Client(trust_env=False, timeout=EVENT_MEDIA_FETCH_TIMEOUT_SEC) as client:
            response = client.get(resolved)
    except httpx.TimeoutException as exc:
        raise SegmentAiMediaError(f"媒体拉取超时: {resolved}") from exc
    except httpx.HTTPError as exc:
        raise SegmentAiMediaError(f"媒体拉取失败: {resolved}") from exc

    if response.status_code == 404:
        raise SegmentAiMediaError(f"媒体不存在: {resolved}")
    if response.status_code >= 400:
        raise SegmentAiMediaError(f"媒体拉取 HTTP {response.status_code}: {resolved}")

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    return response.content, content_type


def _guess_image_mime(url: str, content_type: str) -> str:
    if content_type.startswith("image/"):
        return content_type
    mime, _ = mimetypes.guess_type(url)
    if mime and mime.startswith("image/"):
        return mime
    return "image/jpeg"


def _bytes_to_data_url(data: bytes, mime: str) -> str:
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def _build_prompt(include_image_focus: bool) -> str:
    if include_image_focus:
        return PROMPT + PROMPT_IMAGE_FOCUS_SUFFIX
    return PROMPT


def _build_user_content(video_data_url: str, image_data_url: Optional[str]) -> List[dict]:
    content: List[dict] = []
    if image_data_url:
        content.append({"type": "image_url", "image_url": {"url": image_data_url}})
    content.append({"type": "video_url", "video_url": {"url": video_data_url}})
    content.append({"type": "text", "text": _build_prompt(image_data_url is not None)})
    return content


def _get_delta_text(delta, *field_names: str) -> Optional[str]:
    """从流式 delta 读取 think/reasoning 等扩展字段（兼容 vLLM Qwen3）。"""
    for name in field_names:
        value = getattr(delta, name, None)
        if value:
            return value
    if hasattr(delta, "model_dump"):
        data = delta.model_dump(exclude_none=True)
        for name in field_names:
            if data.get(name):
                return data[name]
    return None


def _combine_thinking_and_answer(think: str, answer: str) -> str:
    think = think.strip()
    answer = answer.strip()
    if think and answer:
        return f"{think}\n{THINKING_ANSWER_SEPARATOR}\n{answer}"
    return answer or think


def _stream_rlq_thinking_and_answer(client: OpenAI, video_data_url: str, image_data_url: Optional[str]) -> tuple[str, str]:
    """流式调用 QRL，分别采集 thinking 与最终 answer。"""
    response = client.chat.completions.create(
        model=EVENT_SEGMENT_AI_MODEL,
        messages=[{"role": "user", "content": _build_user_content(video_data_url, image_data_url)}],
        temperature=1.0,
        top_p=0.95,
        presence_penalty=1.5,
        extra_body={
            "repetition_penalty": 1.0,
            "top_k": 20,
            "chat_template_kwargs": {"enable_thinking": True},
            "mm_processor_kwargs": {
                "fps": 5,
                "do_sample_frames": True,
            },
        },
        stream=True,
    )

    think_parts: List[str] = []
    answer_parts: List[str] = []
    for chunk in response:
        choices = chunk.choices or []
        if not choices:
            continue
        delta = choices[0].delta
        think = _get_delta_text(delta, "reasoning_content", "reasoning", "thinking")
        answer = getattr(delta, "content", None)
        if think:
            think_parts.append(think)
        if answer:
            answer_parts.append(answer)

    return "".join(think_parts), "".join(answer_parts)


def inspect_video_damage(video_bytes: bytes) -> VideoDamageReport:
    """检测分段视频损坏程度（批量任务写日志用）。"""
    return analyze_segment_video_bytes(video_bytes)


def get_video_damage_reason(video_bytes: bytes) -> Optional[str]:
    """ffmpeg 检测损坏；None=可送 QRL，非 None=损坏原因。"""
    report = inspect_video_damage(video_bytes)
    return report.skip_reason


def fetch_segment_video_bytes(segment_video_url: str) -> tuple[bytes, str]:
    """拉取分段视频（供批量任务：先检测再决定是否调 QRL）。"""
    return _fetch_media_bytes(segment_video_url)


def check_rlq_api_available() -> Optional[str]:
    """任务开始前探测 QRL；None=可用，否则返回原因。"""
    url = f"{EVENT_SEGMENT_AI_BASE_URL.rstrip('/')}/models"
    try:
        with httpx.Client(trust_env=False, timeout=20.0) as client:
            response = client.get(
                url,
                headers={"Authorization": f"Bearer {EVENT_SEGMENT_AI_API_KEY}"},
            )
    except httpx.TimeoutException:
        return f"QRL API 连接超时: {url}"
    except httpx.HTTPError as exc:
        return f"QRL API 连接失败: {exc}"

    if response.status_code == 404:
        return (
            "QRL 视觉 API 返回 404（常见于 AutoDL 实例关机或端口未映射），"
            f"请检查 EVENT_SEGMENT_AI_BASE_URL={EVENT_SEGMENT_AI_BASE_URL}"
        )
    if response.status_code >= 400:
        return f"QRL API 返回 HTTP {response.status_code}"
    return None


def format_model_error(exc: Exception) -> str:
    """避免把整页 HTML 打进日志。"""
    message = str(exc).strip()
    lower = message.lower()
    if "<html" in lower or "not found" in lower and "404" in lower:
        return (
            "QRL 视觉 API 不可用(404)，未成功调用模型。"
            f"请检查 backend/.env 中 EVENT_SEGMENT_AI_BASE_URL={EVENT_SEGMENT_AI_BASE_URL}"
        )
    if len(message) > 400:
        return message[:400] + "…"
    return f"QRL 视觉模型调用失败: {message}"


def generate_segment_description_sync(
    segment_video_url: str,
    overlay_image_url: Optional[str] = None,
    video_bytes: Optional[bytes] = None,
    video_content_type: Optional[str] = None,
) -> str:
    if video_bytes is None:
        video_bytes, video_ct = _fetch_media_bytes(segment_video_url)
        damage = get_video_damage_reason(video_bytes)
        if damage:
            raise SegmentAiMediaError(f"视频损坏，跳过补齐: {damage}")
    else:
        video_ct = video_content_type or "video/mp4"

    video_mime = video_ct if video_ct.startswith("video/") else "video/mp4"
    video_data_url = _bytes_to_data_url(video_bytes, video_mime)

    image_data_url: Optional[str] = None
    overlay = (overlay_image_url or "").strip()
    if overlay:
        try:
            image_bytes, image_ct = _fetch_media_bytes(overlay)
            image_mime = _guess_image_mime(overlay, image_ct)
            image_data_url = _bytes_to_data_url(image_bytes, image_mime)
        except SegmentAiMediaError:
            image_data_url = None

    client = OpenAI(
        base_url=EVENT_SEGMENT_AI_BASE_URL,
        api_key=EVENT_SEGMENT_AI_API_KEY,
        timeout=EVENT_SEGMENT_AI_TIMEOUT_SEC,
    )

    try:
        think_text, answer_text = _stream_rlq_thinking_and_answer(client, video_data_url, image_data_url)
    except Exception as exc:
        raise SegmentAiModelError(format_model_error(exc)) from exc

    combined = _combine_thinking_and_answer(think_text, answer_text)
    if not combined:
        raise SegmentAiModelError("视觉模型未返回描述内容")
    return combined
