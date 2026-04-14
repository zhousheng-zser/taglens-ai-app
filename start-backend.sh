#!/bin/bash

# TagLens AI 后端启动脚本（前台运行，Ctrl+C 可直接停止）

set -e

echo "=========================================="
echo "TagLens AI 后端启动脚本"
echo "=========================================="
echo ""

cd "$(dirname "$0")/backend"
source venv/bin/activate

# 强制 HuggingFace/Transformers 离线，避免后台自动转换线程访问外网报错。
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1

echo "正在初始化数据库..."
python3 -c "from core.database import init_database; init_database()" || echo "⚠ 数据库初始化可能失败"

# 检查并释放端口 8000
PORT=8000
PID=$(lsof -t -i:$PORT || true)
if [ ! -z "$PID" ]; then
    echo ">> [自动清理] 发现端口 $PORT 被占用 (PID: $PID)，正在强制释放..."
    kill -9 $PID
    sleep 2
    echo ">> 端口已释放"
else
    echo ">> 端口 $PORT 空闲"
fi

echo "正在启动后端服务 (前台运行，Ctrl+C 可直接停止)..."
python main.py
