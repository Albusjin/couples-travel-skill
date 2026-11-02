"""Shared MCP catalog and native process adaptation; no travel business rules."""

import copy
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

from . import RuntimeConfigError
from .config import SKILL_ROOT, load_settings


def catalog():
    return tomllib.loads((SKILL_ROOT / "config/mcp-servers.toml").read_text(encoding="utf-8"))["mcp_servers"]


def server_launch(npx, node, platform=None, *, package=None, npx_cli=None, arguments=None):
    """Return argv components, never a shell command; .cmd is not a native exe."""
    arguments = list(arguments) if arguments is not None else (["-y", package] if package else catalog()["travel_amap"]["args"])
    host = platform or sys.platform
    if not node:
        raise RuntimeConfigError("本机缺少 Node；请配置 executables.node 或安装 Node.js 24 LTS")
    if npx_cli:
        cli = Path(npx_cli)
        if not cli.is_file():
            raise RuntimeConfigError("配置的 executables.npx_cli 文件不存在")
        return node, [str(cli), *arguments]
    if npx and (host != "win32" or Path(npx).suffix.lower() == ".exe"):
        return npx, arguments
    candidates = ([Path(npx).resolve().parent / "node_modules/npm/bin/npx-cli.js"] if npx else [])
    candidates.append(Path(node).resolve().parent / "node_modules/npm/bin/npx-cli.js")
    for candidate in candidates:
        if candidate.is_file():
            return node, [str(candidate), *arguments]
    raise RuntimeConfigError("找不到 npm npx-cli.js；请安装含 npm 的 Node.js，或配置 executables.npx_cli")


def server_definition(name, settings, *, tool_names=None, credential=None):
    definition = copy.deepcopy(catalog()[name])
    command, arguments = server_launch(settings.npx, settings.node, settings.platform,
                                       arguments=definition["args"], npx_cli=settings.npx_cli)
    definition.update(command=command, args=arguments)
    if tool_names is not None:
        definition["enabled_tools"] = [name for name in definition["enabled_tools"] if name in tool_names]
    environment = dict(settings.environment)
    environment["PATH"] = settings.child_environment(settings.node)["PATH"]
    if credential is not None:
        for name in definition.pop("env_vars", []):
            environment[name] = credential
    definition["env"] = environment
    return definition


def amap_settings(npx, node, settings=None):
    """Keep the historical setup API usable while allowing explicit runtime settings."""
    return replace(settings or load_settings(), npx=npx, node=node)
