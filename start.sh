#!/bin/bash

# TagLens AI 前端启动脚本

echo "=========================================="
echo "TagLens AI 前端启动脚本"
echo "=========================================="
echo ""

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
# 过滤高频媒体请求日志，避免控制台被 /bucket-taglens 打爆
npm run dev 2>&1 | sed -u '/GET \/bucket-taglens\//d'
