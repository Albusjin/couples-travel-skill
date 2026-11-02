"""Resolve machine settings once at the application boundary. No core imports."""

import copy
import os
import shutil
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import RuntimeConfigError

SKILL_ROOT = Path(__file__).resolve().parents[2]
SAFE_ENV_NAMES = (
    "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy", "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "PYTHONUTF8", "PYTHONIOENCODING",
)
ENV_OVERRIDES = {
    "TRAVEL_PLANNER_PYTHON": ("executables", "python"),
    "TRAVEL_PLANNER_NODE": ("executables", "node"),
    "TRAVEL_PLANNER_NPX": ("executables", "npx"),
    "TRAVEL_PLANNER_NPX_CLI": ("executables", "npx_cli"),
    "TRAVEL_PLANNER_VENV_DIR": ("paths", "venv_dir"),
    "TRAVEL_PLANNER_SKILL_DESTINATION": ("paths", "skill_destination"),
    "TRAVEL_PLANNER_DATA_DIR": ("paths", "data_dir"),
    "CODEX_HOME": ("paths", "codex_home"),
}


def merge(base, override):
    result = copy.deepcopy(base)
    for name, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(name), dict):
            result[name] = merge(result[name], value)
        else:
            result[name] = copy.deepcopy(value)
    return result


def validate_settings(values):
    allowed = {"paths": {"codex_home", "skill_destination", "venv_dir", "data_dir"},
               "executables": {"python", "node", "npx", "npx_cli"}, "environment": None}
    for section, entries in values.items():
        if section not in allowed or not isinstance(entries, dict):
            raise RuntimeConfigError(f"无效运行配置节：{section}")
        for name, value in entries.items():
            if (allowed[section] is not None and name not in allowed[section]) or not isinstance(value, str):
                raise RuntimeConfigError(f"无效运行配置字段或类型：{section}.{name}")


@dataclass(frozen=True)
class RuntimeSettings:
    platform: str
    config_file: Path | None
    codex_home: Path
    skill_destination: Path
    venv_dir: Path
    data_dir: Path | None
    python: str
    node: str | None
    npx: str | None
    npx_cli: str | None
    environment: dict

    @property
    def venv_python(self):
        return self.venv_dir / ("Scripts/python.exe" if self.platform == "win32" else "bin/python")

    @property
    def codex_config(self):
        return self.codex_home / "config.toml"

    def child_environment(self, node=None, credential=None):
        # Providers receive a bounded environment, not unrelated API keys.
        env = {name: os.environ[name] for name in SAFE_ENV_NAMES if name in os.environ}
        env.update(self.environment)
        if node:
            env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        if credential is not None:
            env["AMAP_MAPS_API_KEY"] = credential
        return env


def load_settings(config=None, *, platform=None, environ=None, home=None):
    env = os.environ if environ is None else environ
    host = platform or sys.platform
    user_home = Path(home) if home else Path.home()
    try:
        defaults = tomllib.loads((SKILL_ROOT / "config/runtime.toml").read_text(encoding="utf-8"))
        profiles = defaults.pop("platforms")
        if host not in profiles:
            raise RuntimeConfigError(f"未定义运行平台配置：{host}")
        values = merge(defaults, profiles[host])
        selected = config or env.get("TRAVEL_PLANNER_RUNTIME_CONFIG")
        local = Path(selected).expanduser().resolve() if selected else SKILL_ROOT / "config/runtime.local.toml"
        if selected or local.exists():
            values = merge(values, tomllib.loads(local.read_text(encoding="utf-8-sig")))
        else:
            local = None
        for name, (section, field) in ENV_OVERRIDES.items():
            if env.get(name):
                values[section][field] = env[name]
        validate_settings(values)
        base = local.parent if local else SKILL_ROOT
        tokens = {"home": str(user_home), "skill_root": str(SKILL_ROOT),
                  "local_app_data": env.get("LOCALAPPDATA", str(user_home / "AppData/Local"))}

        def expand(value):
            return value.format_map(tokens)

        def path(value):
            expanded = Path(expand(value)).expanduser()
            return expanded.resolve() if expanded.is_absolute() else (base / expanded).resolve()

        configured_environment = {name: expand(value) for name, value in values["environment"].items()}
        search_path = configured_environment.get("PATH", env.get("PATH"))

        def executable(name, fallback=None):
            value = values["executables"].get(name, "")
            if not value:
                return fallback
            expanded = expand(value)
            if "/" in expanded or "\\" in expanded or expanded.startswith("~"):
                return str(path(value))
            return shutil.which(expanded, path=search_path) or expanded

        paths = values["paths"]
        return RuntimeSettings(
            host, local, path(paths["codex_home"]), path(paths["skill_destination"]),
            path(paths["venv_dir"]), path(paths["data_dir"]) if paths["data_dir"] else None,
            executable("python", sys.executable), executable("node", shutil.which("node", path=search_path)),
            executable("npx", shutil.which("npx", path=search_path)), executable("npx_cli"),
            configured_environment,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Never echo configuration values (which may be local credentials/proxies).
        raise RuntimeConfigError("无法读取运行配置；请检查文件、字段类型和路径占位符") from error
