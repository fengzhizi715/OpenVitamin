#!/bin/bash

# 检查 npm 环境
if ! command -v npm &> /dev/null; then
    echo "错误: 未找到 npm"
    exit 1
fi

echo "正在启动前端服务 (Vite)..."
cd frontend

# 检查 node_modules 是否存在
if [ ! -d "node_modules" ]; then
    echo "检测到未安装依赖，正在执行 npm install..."
    npm install
fi

# 使用 exec 让当前进程被真实 node 进程替换，便于 run-all.sh 通过 PID/进程组正确停止
exec npm run dev
