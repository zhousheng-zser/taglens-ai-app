#!/usr/bin/env bash
# SAM3 本地分割服务，默认端口 8011（使用 backend/venv，含 transformers）
set -euo pipefail

SAM3_ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SAM3_ROOT}/.." && pwd)"
PY="${SAM3_VENV_PYTHON:-${PROJECT_ROOT}/backend/venv/bin/python3}"
PORT="${SAM3_SERVER_PORT:-8011}"

if [[ ! -x "${PY}" ]]; then
  echo "错误: 未找到 Python: ${PY}" >&2
  echo "可设置 SAM3_VENV_PYTHON 指向含 transformers 的 python3" >&2
  exit 1
fi

cd "${SAM3_ROOT}"
export PYTHONPATH="${SAM3_ROOT}:${PYTHONPATH:-}"
export SAM3_MODEL_DIR="${SAM3_MODEL_DIR:-${SAM3_ROOT}/sam3_pt}"

"${PY}" -m pip install -q fastapi "uvicorn[standard]" pydantic python-multipart 2>/dev/null || true

echo "=========================================="
echo "SAM3 本地分割服务"
echo "  目录: ${SAM3_ROOT}"
echo "  Python: ${PY}"
echo "  端口: ${PORT}"
echo "  健康: http://127.0.0.1:${PORT}/health"
echo "  接口: http://127.0.0.1:${PORT}/sam3/tasks/path"
echo "=========================================="

exec "${PY}" -m uvicorn sam3_server:app --host 0.0.0.0 --port "${PORT}"
