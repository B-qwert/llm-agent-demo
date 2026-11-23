#!/bin/bash
# 双击运行（macOS）：拉起 Milvus 容器 → 启动问答服务 → 打开页面
# Windows 成员请参见 workbench/README.md 里的 PowerShell 启动方式
cd "$(dirname "$0")"

# 优先用仓库自带的虚拟环境，找不到再退回系统 python3
ROOT="$(cd .. && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
PORT=8777

echo "=== 智能问询 · 可视化平台 ==="

if ! nc -z 127.0.0.1 19530 2>/dev/null; then
  echo "Milvus 还没就绪，正在打开 OrbStack，等它启动（最多 40 秒）…"
  open -a OrbStack
  for i in $(seq 1 40); do
    nc -z 127.0.0.1 19530 2>/dev/null && break
    sleep 1
  done
fi

P=$(lsof -ti tcp:$PORT 2>/dev/null)
if [ -n "$P" ]; then
  if ps -p $P -o command= | grep -q "serve.py"; then
    kill $P 2>/dev/null
    sleep 1
  else
    echo "端口 $PORT 被其他程序占用，改用 8778。"
    PORT=8778
  fi
fi

QA_PORT=$PORT nohup "$PY" serve.py > /tmp/serve.log 2>&1 &
sleep 2

if grep -q "服务已启动" /tmp/serve.log; then
  echo "已启动：http://127.0.0.1:$PORT"
  open "http://127.0.0.1:$PORT"
else
  echo "启动失败，日志如下："
  cat /tmp/serve.log
  read -r -p "按回车关闭窗口"
fi
