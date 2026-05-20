#!/usr/bin/env bash
# DTC 本地分割服务：启动时加载模型，默认端口 8010
set -euo pipefail

DTC_ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${DTC_ROOT}/dtc_dep/bin/python3"
PORT="${DTC_SERVER_PORT:-8010}"

if [[ ! -x "${PY}" ]]; then
  echo "错误: 未找到 ${PY}" >&2
  exit 1
fi

cd "${DTC_ROOT}"

# 服务依赖（若已安装会跳过）
if ! "${PY}" -m pip --version &>/dev/null; then
  echo "正在安装 pip ..."
  curl -sS https://bootstrap.pypa.io/get-pip.py | "${PY}"
fi
"${PY}" -m pip install -q -r "${DTC_ROOT}/requirements-server.txt" 2>/dev/null || true

export PYTHONPATH="${DTC_ROOT}:${PYTHONPATH:-}"
export DTC_CHECKPOINT="${DTC_CHECKPOINT:-${DTC_ROOT}/ckpt/checkpoint.pt}"
export DTC_CATEGORY="${DTC_CATEGORY:-complex}"

echo "=========================================="
echo "DTC 本地分割服务"
echo "  目录: ${DTC_ROOT}"
echo "  端口: ${PORT}"
echo "  健康: http://127.0.0.1:${PORT}/health"
echo "  接口: http://127.0.0.1:${PORT}/dtc/tasks/path"
echo "=========================================="

exec "${PY}" -m uvicorn dtc_server:app --host 0.0.0.0 --port "${PORT}"
