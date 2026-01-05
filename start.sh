#!/bin/bash

# TagLens AI 前后端服务启动脚本

echo "=========================================="
echo "TagLens AI 服务启动脚本"
echo "=========================================="
echo ""

# 检查并重启后端服务
echo "正在检查后端服务状态..."
if curl -s http://localhost:8000/ > /dev/null 2>&1; then
    echo "✓ 后端服务运行中，正在停止旧进程..."
    # 查找并杀掉后端进程
    pkill -f "python.*main.py" || pkill -f "uvicorn.*main:app" || true
    sleep 2
    echo "✓ 旧进程已停止"
fi

echo "正在初始化数据库..."
cd /opt/Traffic-LLM/zser/taglens-ai-app/backend
source venv/bin/activate

# 初始化数据库
python3 -c "from database import init_database; init_database()" 2>&1
if [ $? -eq 0 ]; then
    echo "✓ 数据库初始化完成"
else
    echo "⚠ 警告: 数据库初始化可能失败"
fi

echo "正在启动后端服务..."
python main.py > /tmp/taglens-backend.log 2>&1 &
BACKEND_PID=$!

echo "后端服务启动中 (PID: $BACKEND_PID)..."

# 等待后端服务启动
for i in {1..30}; do
    if curl -s http://localhost:8000/ > /dev/null 2>&1; then
        echo "✓ 后端服务启动成功！"
        break
    fi
    sleep 1
done

if ! curl -s http://localhost:8000/ > /dev/null 2>&1; then
    echo "⚠ 警告: 后端服务可能启动失败，请检查日志: /tmp/taglens-backend.log"
fi

cd /opt/Traffic-LLM/zser/taglens-ai-app
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

echo "正在启动前端开发服务器..."
echo ""
npm run dev
