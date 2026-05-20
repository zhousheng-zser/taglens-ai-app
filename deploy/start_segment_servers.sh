#!/usr/bin/env bash
# 同时启动 DTC(8010) 与 SAM3(8011) 分割服务（各开一个后台进程）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "${LOG_DIR}"

start_one() {
  local name="$1"
  local script="$2"
  local log="${LOG_DIR}/${name}.log"
  if pgrep -f "uvicorn ${name}_server:app" >/dev/null 2>&1; then
    echo "[${name}] 已在运行，跳过"
    return
  fi
  echo "[${name}] 启动 -> ${log}"
  nohup bash "${script}" >>"${log}" 2>&1 &
}

start_one "dtc" "${ROOT}/DTC/start_dtc_server.sh"
start_one "sam3" "${ROOT}/sam3/start_sam3_server.sh"

echo ""
echo "DTC:  http://127.0.0.1:8010/health"
echo "SAM3: http://127.0.0.1:8011/health"
echo "日志: ${LOG_DIR}/dtc.log  ${LOG_DIR}/sam3.log"
