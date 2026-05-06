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

# 可选：启动时后台执行 MP4 faststart 批处理（默认关闭）
# 用法示例：
#   RUN_MP4_FASTSTART_ON_START=1 MP4_FASTSTART_PREFIX="event_data/" MP4_FASTSTART_LIMIT=0 bash start-backend.sh
if [ "${RUN_MP4_FASTSTART_ON_START:-0}" = "1" ]; then
    FASTSTART_SCRIPT="../scripts/mp4_faststart_minio_batch.py"
    FASTSTART_LOG="../logs/mp4_faststart_startup.log"
    FASTSTART_PREFIX="${MP4_FASTSTART_PREFIX:-event_data/}"
    FASTSTART_LIMIT="${MP4_FASTSTART_LIMIT:-0}"
    FASTSTART_EXTRA_ARGS="${MP4_FASTSTART_EXTRA_ARGS:-}"

    mkdir -p ../logs
    if pgrep -f "mp4_faststart_minio_batch.py" > /dev/null 2>&1; then
        echo ">> MP4 faststart 任务已在运行，跳过重复启动"
    elif [ -f "$FASTSTART_SCRIPT" ]; then
        echo ">> 启动 MP4 faststart 后台任务: prefix=$FASTSTART_PREFIX limit=$FASTSTART_LIMIT"
        nohup python3 "$FASTSTART_SCRIPT" \
            --prefix "$FASTSTART_PREFIX" \
            --limit "$FASTSTART_LIMIT" \
            $FASTSTART_EXTRA_ARGS >> "$FASTSTART_LOG" 2>&1 &
        echo ">> 日志: $FASTSTART_LOG"
    else
        echo ">> 未找到 faststart 脚本: $FASTSTART_SCRIPT"
    fi
fi

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
