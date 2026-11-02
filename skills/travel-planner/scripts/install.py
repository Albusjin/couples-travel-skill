#!/usr/bin/env python3
"""Copy the complete self-contained Skill. Refuses to replace an existing install."""

import argparse
import json
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=Path.home() / ".agents/skills/travel-planner")
    args = parser.parse_args()
    destination = args.destination.expanduser().absolute()
    source = Path(__file__).resolve().parents[1]
    if destination.exists() or destination.is_symlink() or destination.resolve().is_relative_to(source):
        print(json.dumps({"ok": False, "message": "目标已存在或位于源目录内；请选新目录，不自动覆盖"}, ensure_ascii=False))
        return 2
    try:
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    except OSError as error:
        print(json.dumps({"ok": False, "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "skill_directory": str(destination),
                      "next": "按 README 安装 Python 依赖，在 Codex Desktop 重新加载 Skill；真实数据另选私有目录"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
