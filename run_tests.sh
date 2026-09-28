#!/usr/bin/env bash
# 运行全部测试（预约竞争 / 配件完整性 / 照片配对 / 押金幂等 / 客户隔离）
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m unittest discover -s tests -v
