#!/usr/bin/env python3
"""Shared bootstrap, launch and diagnostics. Only this layer handles host differences."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print("需要 Python 3.11 或更新版本；请更换初始 Python 解释器后重试", file=sys.stderr)
    sys.exit(2)

from travel_runtime import RuntimeConfigError
from travel_runtime.config import SKILL_ROOT, load_settings
from travel_runtime.mcp import catalog, server_definition, server_launch


def check_version(command, expression, minimum, label):
    result = subprocess.run([command, *expression], capture_output=True, text=True,
                            encoding="utf-8", timeout=20, check=True)
    try:
        parts = tuple(int(value) for value in result.stdout.strip().lstrip("v").split(".")[:2])
    except ValueError:
        raise RuntimeConfigError(f"无法识别 {label} 版本") from None
    if parts < minimum:
        raise RuntimeConfigError(f"{label} 版本过低；最低 {minimum[0]}.{minimum[1]}")
    return result.stdout.strip()


def python_version(command):
    return check_version(command, ["-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"], (3, 11), "Python")


def node_version(settings):
    if not settings.node:
        raise RuntimeConfigError("缺少 Node.js；请安装 Node.js 24 LTS 或配置 executables.node")
    return check_version(settings.node, ["--version"], (22, 14), "Node.js")


def bootstrap(settings, core_only=False):
    python_version(settings.python)
    if not settings.venv_python.is_file():
        subprocess.run([settings.python, "-m", "venv", str(settings.venv_dir)], check=True)
    python_version(str(settings.venv_python))
    requirements = SKILL_ROOT / ("requirements.txt" if core_only else "requirements-amap-setup.txt")
    subprocess.run([str(settings.venv_python), "-m", "pip", "install", "--disable-pip-version-check",
                    "-r", str(requirements)], check=True, env={**os.environ, **settings.environment})


def launch(settings, script, arguments):
    interpreter = str(settings.venv_python) if settings.venv_python.is_file() else settings.python
    python_version(interpreter)
    environment = {**os.environ, **settings.environment}
    if settings.config_file:
        environment["TRAVEL_PLANNER_RUNTIME_CONFIG"] = str(settings.config_file)
    return subprocess.run([interpreter, str(SKILL_ROOT / "scripts" / script), *arguments], env=environment).returncode


def doctor(settings):
    checks = {}
    for label, check in (("python", lambda: python_version(settings.python)),
                         ("venv", lambda: python_version(str(settings.venv_python))),
                         ("node", lambda: node_version(settings)),
                         ("mcp_launch", lambda: server_launch(settings.npx, settings.node, settings.platform,
                                                               npx_cli=settings.npx_cli))):
        try:
            checks[label] = {"ok": True, "result": check()}
        except (RuntimeConfigError, OSError, subprocess.SubprocessError):
            checks[label] = {"ok": False} # No environment values, credentials or command stderr.
    return {"platform": settings.platform, "runtime_config": str(settings.config_file) if settings.config_file else None,
            "paths": {"codex_config": str(settings.codex_config), "skill_destination": str(settings.skill_destination),
                      "venv_python": str(settings.venv_python), "data_dir": str(settings.data_dir) if settings.data_dir else None},
            "environment_names": sorted(settings.environment), "checks": checks,
            "note": "离线检查；不查询服务商、不写入 Codex 配置，不证明实时能力或私有目录权限"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Travel Planner 共用运行环境入口（Python 3.11+）")
    parser.add_argument("--runtime-config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    install = sub.add_parser("bootstrap")
    install.add_argument("--core-only", action="store_true")
    for name in ("run", "setup-amap", "install"):
        entry = sub.add_parser(name, add_help=False)
        if name == "setup-amap":
            entry.add_argument("--bootstrap", action="store_true")
    sub.add_parser("mcp-config", help="只输出本机无凭证 TOML；不改写 Codex 配置")
    # Forward script-specific options without requiring an extra '--'.
    args, extra = parser.parse_known_args(argv)
    if extra and args.command not in ("run", "setup-amap", "install"):
        parser.error("无法识别的参数")
    try:
        settings = load_settings(args.runtime_config)
        if args.command == "doctor":
            result = doctor(settings)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if all(item["ok"] for item in result["checks"].values()) else 2
        if args.command == "bootstrap":
            bootstrap(settings, args.core_only)
            return 0
        if args.command == "mcp-config":
            import tomlkit
            document = {"mcp_servers": {name: server_definition(name, settings) for name in catalog()}}
            print(tomlkit.dumps(document), end="")
            return 0
        arguments = extra
        if arguments[:1] == ["--"]:
            arguments = arguments[1:]
        script = {"run": "travel.py", "setup-amap": "setup_amap.py", "install": "install.py"}[args.command]
        if args.command == "setup-amap":
            node_version(settings)
            server_launch(settings.npx, settings.node, settings.platform, npx_cli=settings.npx_cli)
            if args.bootstrap:
                bootstrap(settings)
        return launch(settings, script, arguments)
    except (RuntimeConfigError, OSError, subprocess.SubprocessError, ModuleNotFoundError) as error:
        message = str(error) if isinstance(error, RuntimeConfigError) else "运行环境未就绪；检查路径、版本和依赖，运行 bootstrap 后重试"
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
