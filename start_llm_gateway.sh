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

echo "=========================================="
echo "TagLens LLM Gateway"
echo "  端口: ${PORT}"
echo "  健康: http://127.0.0.1:${PORT}/health"
echo "  推理: http://127.0.0.1:${PORT}/llm/infer"
echo "=========================================="

exec python3 -m uvicorn llm_gateway_server:app --host 0.0.0.0 --port "${PORT}"
