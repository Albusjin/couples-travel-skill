#!/bin/bash
# Run on the user's Mac. A real Key is entered only in Python's hidden prompt.
set -euo pipefail

TRAVEL_AMAP_SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
TRAVEL_AMAP_PACKAGE_DIR="$(cd -- "$TRAVEL_AMAP_SCRIPT_DIR/.." && pwd)"
TRAVEL_AMAP_VENV_DIR="$HOME/Library/Application Support/TravelPlanner/amap-setup-venv"

printf '%s\n' '高德 MCP：先真实测试，通过后才写入配置。' \
  'Key 在本机静默输入；通过后保存在本机私有 ~/.codex/config.toml。' \
  '已有配置会先备份，其他服务器和模型配置会保留。'

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  printf '%s\n' '需要 Python 3.11 或更新版本。请安装后重新运行。'
  exit 2
fi
if ! command -v node >/dev/null 2>&1 || ! command -v npx >/dev/null 2>&1; then
  printf '%s\n' '需要 Node.js 和 npx。请从 https://nodejs.org 安装 Node.js 24 LTS 后重新运行。'
  exit 2
fi
if ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 14) ? 0 : 1)'; then
  printf '%s\n' 'Node.js 版本过低；需要至少 22.14，推荐 24 LTS。'
  exit 2
fi

if [ ! -x "$TRAVEL_AMAP_VENV_DIR/bin/python" ]; then
  python3 -m venv "$TRAVEL_AMAP_VENV_DIR"
fi
"$TRAVEL_AMAP_VENV_DIR/bin/python" -m pip install --disable-pip-version-check \
  -r "$TRAVEL_AMAP_PACKAGE_DIR/requirements-amap-setup.txt"
"$TRAVEL_AMAP_VENV_DIR/bin/python" "$TRAVEL_AMAP_SCRIPT_DIR/setup_amap.py" --apply --prompt-key

printf '\n%s\n' '请核对上方 passed 和 configuration_written 是否均为 true。' \
  '均为 true 后，Cmd+Q 完全退出并重开 Codex，再验证 travel_amap 工具是否可见。'
