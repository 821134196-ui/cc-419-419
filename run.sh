#!/usr/bin/env bash
# 单条本地启动命令：生成预约/出店/返店/扣款样例后启动 Web。
#   ./run.sh                 首次生成样例（已存在则跳过），启动在 127.0.0.1:8000
#   RESET=1 ./run.sh         重建全部演示数据后启动
#   PORT=8080 HOST=0.0.0.0 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

if [ "${RESET:-0}" = "1" ]; then
  "$PYTHON" -m app.demo --reset
else
  "$PYTHON" -m app.demo
fi

exec "$PYTHON" -m app.server --host "$HOST" --port "$PORT"
