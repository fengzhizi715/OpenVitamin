#!/bin/bash

# 检查是否安装了 conda
if command -v conda &> /dev/null; then
    echo "检测到 Conda，正在使用环境 'ai-inference-platform' 启动..."
    cd backend
    # 使用 conda run 可以绕过 shell init 问题，直接在指定环境下运行命令
    # 使用 exec 让当前进程被真实后端进程替换，便于 run-all.sh 通过 PID/进程组正确停止
    exec conda run -n ai-inference-platform --no-capture-output python3 main.py
else
    echo "未检测到 Conda，尝试使用系统 python3 启动..."
    if ! command -v python3 &> /dev/null; then
        echo "错误: 未找到 python3"
        exit 1
    fi
    cd backend
    # 同上：exec 便于信号直达后端
    exec python3 main.py
fi
