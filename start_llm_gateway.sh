#!/usr/bin/env bash
# TagLens 统一 LLM 网关（独立服务，默认端口 8020）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "${ROOT}/backend"
source venv/bin/activate

PORT="${LLM_GATEWAY_PORT:-8020}"

# 释放端口
PID="$(lsof -t -i:"${PORT}" 2>/dev/null || true)"
if [[ -n "${PID}" ]]; then
  echo ">> 释放端口 ${PORT} (PID ${PID})"
  kill -9 ${PID} || true
  sleep 1
fi

export LLM_GATEWAY_PORT="${PORT}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"

# 临时：Codex 卸载到 192.168.2.145（设 CODEX_REMOTE_ENABLED=0 回退本机）
export CODEX_REMOTE_ENABLED="${CODEX_REMOTE_ENABLED:-1}"
export CODEX_REMOTE_HOST="${CODEX_REMOTE_HOST:-192.168.2.145}"
export CODEX_REMOTE_USER="${CODEX_REMOTE_USER:-root}"
export CODEX_REMOTE_PASSWORD="${CODEX_REMOTE_PASSWORD:-md@xinxi2022}"
export CODEX_REMOTE_DIR="${CODEX_REMOTE_DIR:-/root/codex_tmp}"
export CODEX_REMOTE_KEEP="${CODEX_REMOTE_KEEP:-100}"
# CODEX_REMOTE_PORT 为空时自动探测 22→2222
# spark 仅文本；交通看图默认 gpt-5.5（可用 CODEX_MODEL 覆盖）
export CODEX_MODEL="${CODEX_MODEL:-gpt-5.4-mini}"
# 覆盖远端 ~/.codex/config.toml 的 xhigh（批量看图否则极易卡住）
export CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-medium}"
# 远端同时跑的 codex 进程上限
export CODEX_REMOTE_MAX_CONCURRENT="${CODEX_REMOTE_MAX_CONCURRENT:-2}"
# 每 N 次 Codex 请求共用一个会话；设 1 或 0 关闭
export CODEX_SESSION_REUSE_EVERY="${CODEX_SESSION_REUSE_EVERY:-20}"
# 远端 145 DNS 不可用；代理优先读 backend/.env 的 HTTP_PROXY（与 .env 17-18 行一致）
_CODEX_LAN_PROXY="http://192.168.2.245:10808"
if [[ -f .env ]]; then
  while IFS= read -r line || [[ -n "${line}" ]]; do
    case "${line}" in
      \#*|"") continue ;;
    esac
    key="${line%%=*}"
    case "${key}" in
      HTTP_PROXY|HTTPS_PROXY|http_proxy|https_proxy)
        val="${line#*=}"
        val="${val%$'\r'}"
        val="${val#\"}"
        val="${val%\"}"
        val="${val#\'}"
        val="${val%\'}"
        if [[ -z "${!key:-}" ]]; then
          export "${key}=${val}"
        fi
        ;;
    esac
  done < .env
fi
export HTTP_PROXY="${HTTP_PROXY:-${_CODEX_LAN_PROXY}}"
export HTTPS_PROXY="${HTTPS_PROXY:-${HTTP_PROXY}}"
export CODEX_REMOTE_HTTP_PROXY="${CODEX_REMOTE_HTTP_PROXY:-${HTTP_PROXY}}"
export CODEX_REMOTE_HTTPS_PROXY="${CODEX_REMOTE_HTTPS_PROXY:-${HTTPS_PROXY}}"
# 主后端/补标签调用网关的超时（需重启主后端才会进到 client）
export LLM_GATEWAY_TIMEOUT_SEC="${LLM_GATEWAY_TIMEOUT_SEC:-600}"
export LLM_GATEWAY_HARD_TIMEOUT_SEC="${LLM_GATEWAY_HARD_TIMEOUT_SEC:-630}"

echo "=========================================="
echo "TagLens LLM Gateway"
echo "  端口: ${PORT}"
echo "  健康: http://127.0.0.1:${PORT}/health"
echo "  推理: http://127.0.0.1:${PORT}/llm/infer"
echo "  Codex 远端: ${CODEX_REMOTE_ENABLED} -> ${CODEX_REMOTE_USER}@${CODEX_REMOTE_HOST}:${CODEX_REMOTE_DIR}"
echo "  Codex 模型: ${CODEX_MODEL}"
echo "  Codex reasoning: ${CODEX_REASONING_EFFORT}"
echo "  Codex 远端并发: ${CODEX_REMOTE_MAX_CONCURRENT}"
echo "  Codex 会话复用: 每 ${CODEX_SESSION_REUSE_EVERY} 次"
echo "  Codex 远端代理: ${CODEX_REMOTE_HTTP_PROXY}"
echo "=========================================="

exec python3 -m uvicorn llm_gateway_server:app --host 0.0.0.0 --port "${PORT}"
