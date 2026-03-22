#!/bin/bash

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}正在同步启动后端和前端服务...${NC}"

# 启动后端 (在后台运行)
./run-backend.sh &
BACKEND_PID=$!

# 启动前端
./run-frontend.sh &
FRONTEND_PID=$!

cleanup() {
  echo -e "\n${BLUE}正在停止服务...${NC}"

  # 先发 TERM 给各自的进程组（更可靠地杀掉子进程树）
  for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      # bash 的后台 job 通常会成为一个独立进程组，PGID=PID；优先杀进程组
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  # 给一点时间优雅退出
  sleep 2

  # 仍存活则 KILL
  for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
  done
}

# 捕获 Ctrl+C / SIGTERM / 关终端常见 SIGHUP，确保能清理进程树
trap cleanup SIGINT SIGTERM SIGHUP

echo -e "${GREEN}服务已启动！按 Ctrl+C 停止所有服务。${NC}"

# 等待子进程
wait
