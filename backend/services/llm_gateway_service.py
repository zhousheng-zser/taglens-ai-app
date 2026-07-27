"""统一 LLM 网关：千问 / Gemini / Codex / MiMo 视觉分析。"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import httpx
import requests
from openai import OpenAI

from services.http_timeouts import mimo_upstream_timeout
from services.llm_prompts import build_default_analysis_prompt
from services.sync_hard_timeout import HardTimeoutError, call_with_hard_timeout

LLMProviderName = Literal["qwen", "gemini", "codex", "mimo"]
SUPPORTED_PROVIDERS: tuple[str, ...] = ("qwen", "gemini", "codex", "mimo")

QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-vl-max")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5")
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MIMO_HTTP_TIMEOUT_SEC = float(os.getenv("MIMO_HTTP_TIMEOUT_SEC", "120"))
MIMO_HTTP_HARD_TIMEOUT_SEC = float(
    os.getenv("MIMO_HTTP_HARD_TIMEOUT_SEC", str(MIMO_HTTP_TIMEOUT_SEC + 15))
)
GEMINI_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

CODEX_LOCAL_WORKDIR = os.getenv(
    "CODEX_WORKDIR", str(Path(__file__).resolve().parent.parent.parent / "data" / "codex_tmp")
)
CODEX_LOCAL_HTTP_PROXY = os.getenv("HTTP_PROXY", "http://192.168.2.245:10808")
CODEX_LOCAL_HTTPS_PROXY = os.getenv("HTTPS_PROXY", "http://192.168.2.245:10808")
# spark 等纯文本模型无法看图；交通标注必须用支持 image 的模型
CODEX_MODEL = os.getenv("CODEX_MODEL", "gpt-5.5").strip() or "gpt-5.5"

# 临时：Codex 卸载到内网机器（SSH/scp）；CODEX_REMOTE_ENABLED=0 回退本机 CLI
CODEX_REMOTE_ENABLED = os.getenv("CODEX_REMOTE_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
CODEX_REMOTE_HOST = os.getenv("CODEX_REMOTE_HOST", "192.168.2.145").strip()
CODEX_REMOTE_USER = os.getenv("CODEX_REMOTE_USER", "root").strip()
CODEX_REMOTE_PASSWORD = os.getenv("CODEX_REMOTE_PASSWORD", "md@xinxi2022")
CODEX_REMOTE_PORT = os.getenv("CODEX_REMOTE_PORT", "").strip()
CODEX_REMOTE_DIR = os.getenv("CODEX_REMOTE_DIR", "/root/codex_tmp").strip()
CODEX_REMOTE_KEEP = max(1, int(os.getenv("CODEX_REMOTE_KEEP", "100")))
# 远端 145 DNS 常挂；Codex 出网须走局域网 HTTP 代理（不可用 127.0.0.1）
_DEFAULT_LAN_PROXY = "http://192.168.2.245:10808"


def _sanitize_remote_proxy(url: str) -> str:
    u = (url or "").strip() or _DEFAULT_LAN_PROXY
    # Cursor/本机沙箱代理对远端 145 不可达
    if "127.0.0.1" in u or "localhost" in u:
        print(f"[codex-remote] 忽略不可达代理 {u}，改用 {_DEFAULT_LAN_PROXY}")
        return _DEFAULT_LAN_PROXY
    return u


CODEX_REMOTE_HTTP_PROXY = _sanitize_remote_proxy(
    os.getenv("CODEX_REMOTE_HTTP_PROXY")
    or os.getenv("HTTP_PROXY")
    or os.getenv("http_proxy")
    or _DEFAULT_LAN_PROXY
)
CODEX_REMOTE_HTTPS_PROXY = _sanitize_remote_proxy(
    os.getenv("CODEX_REMOTE_HTTPS_PROXY")
    or os.getenv("HTTPS_PROXY")
    or os.getenv("https_proxy")
    or CODEX_REMOTE_HTTP_PROXY
)
CODEX_REMOTE_NO_PROXY = os.getenv(
    "CODEX_REMOTE_NO_PROXY", "127.0.0.1,localhost,192.168.0.0/16"
)
# 远端 ~/.codex/config.toml 常设 model_reasoning_effort=xhigh，看图批量会极慢甚至卡死
CODEX_REASONING_EFFORT = (
    os.getenv("CODEX_REASONING_EFFORT", "medium").strip() or "medium"
)
# 远端 Codex 并发上限（标签补齐默认 5 路，xhigh/高并发下易把网关线程占满）
CODEX_REMOTE_MAX_CONCURRENT = max(
    1, int(os.getenv("CODEX_REMOTE_MAX_CONCURRENT", "2"))
)
_CODEX_REMOTE_SEM = threading.Semaphore(CODEX_REMOTE_MAX_CONCURRENT)

_resolved_remote_port: Optional[int] = None

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


def _call_mimo_once(api_key: str, data_uri: str, prompt: str) -> dict[str, Any]:
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
    with httpx.Client(trust_env=False, timeout=mimo_upstream_timeout()) as client:
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


def _call_mimo(api_key: str, data_uri: str, prompt: str) -> dict[str, Any]:
    try:
        return call_with_hard_timeout(
            MIMO_HTTP_HARD_TIMEOUT_SEC,
            _call_mimo_once,
            api_key,
            data_uri,
            prompt,
        )
    except HardTimeoutError as exc:
        raise LLMGatewayError(f"MiMo API 硬超时: {exc}", status_code=504) from exc


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


def _sshpass_base() -> list[str]:
    if shutil.which("sshpass") is None:
        raise LLMGatewayError("缺少依赖 sshpass（远端 Codex 需要）")
    return ["sshpass", "-p", CODEX_REMOTE_PASSWORD]


def _ssh_common_opts(port: int) -> list[str]:
    return [
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "LogLevel=ERROR",
    ]


def _resolve_remote_port() -> int:
    """优先 CODEX_REMOTE_PORT；否则探测 22，再 2222。"""
    global _resolved_remote_port
    if CODEX_REMOTE_PORT:
        return int(CODEX_REMOTE_PORT)
    if _resolved_remote_port is not None:
        return _resolved_remote_port
    for port in (22, 2222):
        cmd = _sshpass_base() + ["ssh"] + _ssh_common_opts(port) + [
            f"{CODEX_REMOTE_USER}@{CODEX_REMOTE_HOST}",
            "echo ok",
        ]
        ret = _run_cmd(cmd)
        if ret.returncode == 0:
            _resolved_remote_port = port
            print(f"[codex-remote] SSH 端口就绪: {port}")
            return port
    raise LLMGatewayError(
        f"无法 SSH 连接 {CODEX_REMOTE_HOST}（端口 22/2222 均失败）"
    )


def _remote_ssh(remote_cmd: str, *, timeout_sec: int = 300) -> subprocess.CompletedProcess:
    port = _resolve_remote_port()
    cmd = _sshpass_base() + ["ssh"] + _ssh_common_opts(port) + [
        f"{CODEX_REMOTE_USER}@{CODEX_REMOTE_HOST}",
        remote_cmd,
    ]
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=timeout_sec
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMGatewayError(f"远端 SSH 超时({timeout_sec}s): {exc}") from exc


def _remote_scp_to(local_path: Path, remote_path: str) -> None:
    port = _resolve_remote_port()
    cmd = _sshpass_base() + [
        "scp",
        "-P",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        str(local_path),
        f"{CODEX_REMOTE_USER}@{CODEX_REMOTE_HOST}:{remote_path}",
    ]
    ret = _run_cmd(cmd)
    if ret.returncode != 0:
        raise LLMGatewayError(f"scp 上传失败: {(ret.stderr or ret.stdout).strip()}")


def _remote_scp_from(remote_path: str, local_path: Path) -> None:
    port = _resolve_remote_port()
    cmd = _sshpass_base() + [
        "scp",
        "-P",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        f"{CODEX_REMOTE_USER}@{CODEX_REMOTE_HOST}:{remote_path}",
        str(local_path),
    ]
    ret = _run_cmd(cmd)
    if ret.returncode != 0:
        raise LLMGatewayError(f"scp 下载失败: {(ret.stderr or ret.stdout).strip()}")


def _remote_prune_codex_tmp() -> None:
    """远端只保留最新 CODEX_REMOTE_KEEP 组（同 stem 的图/prompt/result）。"""
    keep = CODEX_REMOTE_KEEP
    remote_dir = CODEX_REMOTE_DIR
    script = f"""
set -e
DIR='{remote_dir}'
KEEP={keep}
cd "$DIR" || exit 0
mapfile -t imgs < <(ls -1t img_* 2>/dev/null | grep -vE '\\.(prompt|result)\\.txt$' || true)
if [ "${{#imgs[@]}}" -le "$KEEP" ]; then
  exit 0
fi
for f in "${{imgs[@]:$KEEP}}"; do
  stem="${{f%.*}}"
  rm -f "$stem".*
done
"""
    try:
        ret = _remote_ssh(script, timeout_sec=60)
        if ret.returncode != 0:
            print(f"[codex-remote] 清理旧文件警告: {(ret.stderr or ret.stdout).strip()}")
    except Exception as exc:
        print(f"[codex-remote] 清理旧文件失败: {exc}")


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


def _call_codex_local(data_uri: str, prompt: str) -> dict[str, Any]:
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
            "--dangerously-bypass-approvals-and-sandbox",
            "-c",
            f"model_reasoning_effort={CODEX_REASONING_EFFORT}",
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


def _call_codex_remote(data_uri: str, prompt: str) -> dict[str, Any]:
    """临时：上传图+prompt 到远端执行 codex，拉回结果；远端仅保留最新 N 组。"""
    head, b64 = data_uri.split(",", 1)
    ext = ".jpg"
    if "image/png" in head:
        ext = ".png"
    elif "image/webp" in head:
        ext = ".webp"
    elif "image/gif" in head:
        ext = ".gif"

    workdir = _ensure_codex_workdir()
    unique = uuid.uuid4().hex[:10]
    stem = f"img_{unique}"
    img_name = f"{stem}{ext}"
    prompt_name = f"{stem}.prompt.txt"
    out_name = f"{stem}.result.txt"
    local_img = workdir / img_name
    local_prompt = workdir / prompt_name
    local_out = workdir / out_name
    remote_img = f"{CODEX_REMOTE_DIR}/{img_name}"
    remote_prompt = f"{CODEX_REMOTE_DIR}/{prompt_name}"
    remote_out = f"{CODEX_REMOTE_DIR}/{out_name}"

    try:
        local_img.write_bytes(base64.b64decode(b64))
        local_prompt.write_text(prompt, encoding="utf-8")

        mkdir_ret = _remote_ssh(f"mkdir -p '{CODEX_REMOTE_DIR}'", timeout_sec=30)
        if mkdir_ret.returncode != 0:
            raise LLMGatewayError(
                f"远端创建目录失败: {(mkdir_ret.stderr or mkdir_ret.stdout).strip()}"
            )

        which_ret = _remote_ssh("which codex", timeout_sec=30)
        if which_ret.returncode != 0:
            raise LLMGatewayError("远端缺少 codex CLI")

        _remote_scp_to(local_img, remote_img)
        _remote_scp_to(local_prompt, remote_prompt)

        # 非交互 SSH 须绕过审批；prompt 走 stdin（不要再传 `-`，避免与重定向混淆）；
        # 绝对路径 -i；远端必须带 HTTP 代理（145 本机 DNS 不可用）。
        # 覆盖远端 config.toml 的 xhigh，避免批量看图卡死。
        remote_exec = (
            f"cd '{CODEX_REMOTE_DIR}' && "
            f"export HTTP_PROXY='{CODEX_REMOTE_HTTP_PROXY}' "
            f"HTTPS_PROXY='{CODEX_REMOTE_HTTPS_PROXY}' "
            f"http_proxy='{CODEX_REMOTE_HTTP_PROXY}' "
            f"https_proxy='{CODEX_REMOTE_HTTPS_PROXY}' "
            f"ALL_PROXY='{CODEX_REMOTE_HTTP_PROXY}' "
            f"NO_PROXY='{CODEX_REMOTE_NO_PROXY}' "
            f"no_proxy='{CODEX_REMOTE_NO_PROXY}' && "
            f"codex exec --skip-git-repo-check "
            f"--dangerously-bypass-approvals-and-sandbox "
            f"-c model_reasoning_effort={CODEX_REASONING_EFFORT} "
            f"-m '{CODEX_MODEL}' "
            f"-C '{CODEX_REMOTE_DIR}' "
            f"-i '{remote_img}' -o '{out_name}' "
            f"< '{prompt_name}'"
        )
        print(
            f"[codex-remote] 等待并发槽位 "
            f"(max={CODEX_REMOTE_MAX_CONCURRENT}) {CODEX_REMOTE_HOST}:{img_name}"
        )
        with _CODEX_REMOTE_SEM:
            print(
                f"[codex-remote] 开始远端执行 {CODEX_REMOTE_HOST}:{img_name} "
                f"model={CODEX_MODEL} effort={CODEX_REASONING_EFFORT} "
                f"proxy={CODEX_REMOTE_HTTP_PROXY}"
            )
            exec_ret = _remote_ssh(remote_exec, timeout_sec=900)

            # 即使 CLI 非 0，只要结果文件可读 JSON 仍可成功（网络重试等场景）
            try:
                _remote_scp_from(remote_out, local_out)
            except LLMGatewayError:
                if exec_ret.returncode != 0:
                    err = (exec_ret.stderr or exec_ret.stdout or "").strip()
                    # 避免把 banner/超长 prompt 整段塞进错误；取末尾更有信号
                    err_tail = err[-1500:] if len(err) > 1500 else err
                    raise LLMGatewayError(
                        f"远端 codex 执行失败 (exit={exec_ret.returncode}): {err_tail}"
                    ) from None
                raise

            if not local_out.exists() or local_out.stat().st_size == 0:
                err = (exec_ret.stderr or exec_ret.stdout or "").strip()
                err_tail = err[-1500:] if len(err) > 1500 else err
                raise LLMGatewayError(
                    f"远端结果文件为空或不存在: {out_name}"
                    + (f"; stderr={err_tail}" if err_tail else "")
                )

            try:
                payload = _parse_json_from_model_text(
                    local_out.read_text(encoding="utf-8", errors="replace")
                )
                normalized = _normalize_codex_payload(payload)
            except Exception as parse_exc:
                if exec_ret.returncode != 0:
                    err = (exec_ret.stderr or exec_ret.stdout or "").strip()
                    err_tail = err[-1500:] if len(err) > 1500 else err
                    raise LLMGatewayError(
                        f"远端 codex 执行失败 (exit={exec_ret.returncode}): {err_tail}"
                    ) from parse_exc
                raise

            if exec_ret.returncode != 0:
                print(
                    f"[codex-remote] CLI exit={exec_ret.returncode} 但结果 JSON 可用，继续"
                )
            _remote_prune_codex_tmp()
            print(f"[codex-remote] 完成 {stem}")
            return normalized
    finally:
        for p in (local_img, local_prompt, local_out):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass


def _call_codex(data_uri: str, prompt: str) -> dict[str, Any]:
    if "," not in data_uri:
        raise LLMGatewayError("无效图片 data URI", status_code=400)
    if CODEX_REMOTE_ENABLED:
        return _call_codex_remote(data_uri, prompt)
    return _call_codex_local(data_uri, prompt)


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
