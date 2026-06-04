#!/bin/bash

# TagLens AI 前端启动脚本（生产模式：next build + next start）

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PORT="${PORT:-9002}"
export NODE_ENV=production
export PORT

echo "=========================================="
echo "TagLens AI 前端启动脚本（生产模式）"
echo "=========================================="
echo ""

release_port() {
  local pid
  pid="$(lsof -t -i:"$PORT" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    echo ">> [自动清理] 发现端口 $PORT 被占用 (PID: $pid)，正在强制释放..."
    kill -9 $pid 2>/dev/null || true
    sleep 2
    echo ">> 端口已释放"
  else
    echo ">> 端口 $PORT 空闲"
  fi
}

ensure_build() {
  if [[ ! -f .next/BUILD_ID ]] || [[ "${TAGLENS_FRONTEND_REBUILD:-0}" == "1" ]]; then
    echo "正在构建前端生产包 (npm run build)..."
    echo "（首次或强制重建可能需数分钟；跳过后续重建可 unset TAGLENS_FRONTEND_REBUILD）"
    npm run build
    echo "✓ 构建完成"
  else
    echo "✓ 已有生产构建 (.next/BUILD_ID)，跳过 npm run build"
    echo "  若刚改前端代码，请执行: TAGLENS_FRONTEND_REBUILD=1 $0"
  fi
}

release_port
ensure_build

echo ""
echo "正在启动前端生产服务 (next start -p $PORT)..."
echo ""
# 过滤高频媒体请求日志，避免 journal 被 /bucket-taglens 打爆
npm run start 2>&1 | sed -u '/GET \/bucket-taglens\//d'
