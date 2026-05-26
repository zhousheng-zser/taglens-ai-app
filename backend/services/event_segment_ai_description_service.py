"""事件分段 AI 描述：HTTP 拉取媒体 + RLQ 多模态（仿 qianwen_test/test.py，无 thinking、不落盘）。"""
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

MAX_WORKERS = 15
_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="segment-ai")

EVENT_SEGMENT_AI_BASE_URL = os.getenv(
    "EVENT_SEGMENT_AI_BASE_URL",
    "https://u149890-jyv3-5b09aec6.westb.seetacloud.com:8443/v1",
)
EVENT_SEGMENT_AI_API_KEY = os.getenv("EVENT_SEGMENT_AI_API_KEY", "EMPTY")
EVENT_SEGMENT_AI_MODEL = os.getenv("EVENT_SEGMENT_AI_MODEL", "model/RLQ")
EVENT_SEGMENT_AI_TIMEOUT_SEC = float(os.getenv("EVENT_SEGMENT_AI_TIMEOUT_SEC", "600"))

EVENT_MEDIA_HTTP_ORIGIN = os.getenv("EVENT_MEDIA_HTTP_ORIGIN", "http://127.0.0.1:9002").rstrip("/")
EVENT_MEDIA_FETCH_TIMEOUT_SEC = float(os.getenv("EVENT_MEDIA_FETCH_TIMEOUT_SEC", "120"))
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "bucket-taglens")


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


def generate_segment_description_sync(
    segment_video_url: str,
    overlay_image_url: Optional[str] = None,
) -> str:
    video_bytes, video_ct = _fetch_media_bytes(segment_video_url)
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
        response = client.chat.completions.create(
            model=EVENT_SEGMENT_AI_MODEL,
            messages=[{"role": "user", "content": _build_user_content(video_data_url, image_data_url)}],
            temperature=1.0,
            top_p=0.95,
            presence_penalty=1.5,
            extra_body={
                "repetition_penalty": 1.0,
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": False},
                "mm_processor_kwargs": {
                    "fps": 5,
                    "do_sample_frames": True,
                },
            },
            stream=False,
        )
    except Exception as exc:
        raise SegmentAiModelError(f"视觉模型调用失败: {exc}") from exc

    choices = response.choices or []
    if not choices:
        raise SegmentAiModelError("视觉模型返回为空")
    answer = (choices[0].message.content or "").strip()
    if not answer:
        raise SegmentAiModelError("视觉模型未返回描述内容")
    return answer
