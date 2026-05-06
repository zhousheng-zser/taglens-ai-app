#!/bin/bash

# TagLens AI 前端启动脚本

echo "=========================================="
echo "TagLens AI 前端启动脚本"
echo "=========================================="
echo ""

# 可选：从前端启动脚本触发 MP4 faststart 后台任务（默认关闭）
# 用法示例：
#   RUN_MP4_FASTSTART_ON_START=1 MP4_FASTSTART_PREFIX="event_data/WHJM-9096/" MP4_FASTSTART_LIMIT=100 bash start.sh
if [ "${RUN_MP4_FASTSTART_ON_START:-0}" = "1" ]; then
    FASTSTART_SCRIPT="scripts/mp4_faststart_minio_batch.py"
    FASTSTART_LOG="logs/mp4_faststart_startup.log"
    FASTSTART_PREFIX="${MP4_FASTSTART_PREFIX:-event_data/}"
    FASTSTART_LIMIT="${MP4_FASTSTART_LIMIT:-0}"
    FASTSTART_EXTRA_ARGS="${MP4_FASTSTART_EXTRA_ARGS:-}"

    mkdir -p logs
    if pgrep -f "mp4_faststart_minio_batch.py" > /dev/null 2>&1; then
        echo ">> MP4 faststart 任务已在运行，跳过重复启动"
    elif [ -f "$FASTSTART_SCRIPT" ]; then
        echo ">> 启动 MP4 faststart 后台任务: prefix=$FASTSTART_PREFIX limit=$FASTSTART_LIMIT"
        nohup backend/venv/bin/python "$FASTSTART_SCRIPT" \
            --prefix "$FASTSTART_PREFIX" \
            --limit "$FASTSTART_LIMIT" \
            $FASTSTART_EXTRA_ARGS >> "$FASTSTART_LOG" 2>&1 &
        echo ">> 日志: $FASTSTART_LOG"
    else
        echo ">> 未找到 faststart 脚本: $FASTSTART_SCRIPT"
    fi
fi

# 检查并重启前端服务
echo ""
echo "正在检查前端服务状态..."
if curl -s http://localhost:9002 > /dev/null 2>&1; then
    echo "✓ 前端服务运行中，正在停止旧进程..."
    # 查找并杀掉前端进程
    pkill -f "next dev" || pkill -f "node.*next" || true
    sleep 2
    echo "✓ 旧进程已停止"
fi

# 检查并释放端口 8000
PORT=9002
PID=$(lsof -t -i:$PORT || true)
if [ ! -z "$PID" ]; then
    echo ">> [自动清理] 发现端口 $PORT 被占用 (PID: $PID)，正在强制释放..."
    kill -9 $PID
    sleep 2
    echo ">> 端口已释放"
else
    echo ">> 端口 $PORT 空闲"
fi



echo "正在启动前端开发服务器..."
echo ""
npm run dev
