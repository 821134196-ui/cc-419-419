#!/usr/bin/env bash
# 单条本地启动命令：首次运行自动生成预约/出店/返店/扣款样例，然后启动服务。
#   ./run.sh            打开 http://127.0.0.1:8765
#   BRIDAL_PORT=9000 ./run.sh
set -e
cd "$(dirname "$0")"

# 首次运行（数据库不存在）时生成演示样例
if [ ! -f data/bridal.db ]; then
  echo "首次启动，生成演示样例数据…"
  python3 seed.py
fi

exec python3 server.py
