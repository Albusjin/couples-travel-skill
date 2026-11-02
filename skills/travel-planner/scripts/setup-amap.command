#!/bin/bash
# Thin host entrypoint; shared Python runtime owns setup and configuration.
set -euo pipefail
TRAVEL_AMAP_SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
exec "${TRAVEL_PLANNER_PYTHON:-python3}" "$TRAVEL_AMAP_SCRIPT_DIR/runtime.py" setup-amap --bootstrap --apply --prompt-key "$@"
