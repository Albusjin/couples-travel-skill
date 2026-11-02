"""Host/configuration regression tests. No real credentials or provider calls."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/travel-planner"
sys.path.insert(0, str(SKILL / "scripts"))
import runtime
from travel_runtime import RuntimeConfigError
from travel_runtime.config import load_settings
from travel_runtime.mcp import catalog, server_definition, server_launch


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="travel runtime ")
        self.home = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def settings(self, **kwargs):
        return load_settings(home=self.home, environ={}, **kwargs)

    def test_platform_defaults_are_only_runtime_paths(self):
        for platform, directory, python in (
            ("darwin", "Library/Application Support/TravelPlanner/amap-setup-venv", "bin/python"),
            ("win32", "AppData/Local/TravelPlanner/amap-setup-venv", "Scripts/python.exe"),
            ("linux", ".local/share/TravelPlanner/amap-setup-venv", "bin/python"),
        ):
            with self.subTest(platform=platform):
                settings = self.settings(platform=platform)
                self.assertEqual(settings.venv_dir, self.home / directory)
                self.assertEqual(settings.venv_python, self.home / directory / python)
                self.assertIsNone(settings.data_dir)
                self.assertEqual(settings.codex_config, self.home / ".codex/config.toml")

    def test_local_override_environment_and_explicit_file_precedence(self):
        first = self.home / "first.toml"
        second = self.home / "second.toml"
        first.write_text('[paths]\ndata_dir="first"\n', encoding="utf-8")
        second.write_text('[paths]\ndata_dir="second"\ncodex_home="codex-local"\n', encoding="utf-8")
        settings = load_settings(second, home=self.home, environ={
            "TRAVEL_PLANNER_RUNTIME_CONFIG": str(first), "TRAVEL_PLANNER_DATA_DIR": str(self.home / "override"),
            "CODEX_HOME": str(self.home / "custom-codex"),
        })
        self.assertEqual(settings.config_file, second)
        self.assertEqual(settings.data_dir, self.home / "override")
        self.assertEqual(settings.codex_config, self.home / "custom-codex/config.toml")

    def test_relative_paths_and_unicode_do_not_depend_on_working_directory(self):
        config = self.home / "runtime.toml"
        config.write_text('[paths]\nvenv_dir="运行环境 with spaces"\ndata_dir="private"\n', encoding="utf-8-sig")
        settings = self.settings(config=config)
        self.assertEqual(settings.venv_dir, self.home / "运行环境 with spaces")
        self.assertEqual(settings.data_dir, self.home / "private")

    def test_windows_local_app_data_and_explicit_python_path(self):
        settings = load_settings(platform="win32", home=self.home, environ={
            "LOCALAPPDATA": str(self.home / "Local Profile"),
            "TRAVEL_PLANNER_PYTHON": str(self.home / "Python Installation/python.exe"),
        })
        self.assertEqual(settings.venv_dir, self.home / "Local Profile/TravelPlanner/amap-setup-venv")
        self.assertEqual(settings.python, str(self.home / "Python Installation/python.exe"))

    def test_configured_path_is_used_for_executable_discovery(self):
        config = self.home / "runtime.toml"
        config.write_text('[environment]\nPATH="/fixture/configured-path"\n', encoding="utf-8")
        with patch("travel_runtime.config.shutil.which", return_value=None) as which:
            self.settings(config=config)
        self.assertTrue(which.call_args_list)
        self.assertTrue(all(call.kwargs.get("path") == "/fixture/configured-path" for call in which.call_args_list))

    def test_invalid_missing_or_misspelled_configuration_fails_without_values(self):
        config = self.home / "runtime.toml"
        for content in ('[paths]\nvenv_dir=123\n', '[paths]\nvenv_dri="SYNTHETIC-SECRET"\n',
                        '[paths]\nvenv_dir="{SYNTHETIC-SECRET}"\n', 'not valid TOML'):
            config.write_text(content, encoding="utf-8")
            with self.assertRaises(RuntimeConfigError) as raised:
                self.settings(config=config)
            self.assertNotIn("SYNTHETIC-SECRET", str(raised.exception))
        with self.assertRaises(RuntimeConfigError):
            self.settings(config=self.home / "missing.toml")

    def test_environment_is_bounded_and_local_values_are_not_printed_by_doctor(self):
        settings = replace(self.settings(), environment={"HTTPS_PROXY": "SYNTHETIC-PRIVATE-VALUE"})
        with patch.dict(os.environ, {"UNRELATED_API_KEY": "UNRELATED-SECRET"}):
            child = settings.child_environment(credential="MAP-KEY")
        self.assertNotIn("UNRELATED_API_KEY", child)
        self.assertEqual(child["AMAP_MAPS_API_KEY"], "MAP-KEY")
        with patch("runtime.python_version", return_value="3.13.0"), patch("runtime.node_version", return_value="24.0.0"), \
                patch("runtime.server_launch", return_value=("node", [])):
            report = runtime.doctor(settings)
        self.assertNotIn("SYNTHETIC-PRIVATE-VALUE", json.dumps(report))
        self.assertIn("HTTPS_PROXY", report["environment_names"])


class RuntimeLaunchTests(unittest.TestCase):
    def test_forwarded_cli_arguments_keep_original_order_and_spaces(self):
        settings = load_settings(environ={})
        arguments = ["--data-dir", "private path with spaces", "init", "demo", "--title", "虚构行程"]
        with patch("runtime.load_settings", return_value=settings), patch("runtime.launch", return_value=0) as launch:
            self.assertEqual(runtime.main(["run", *arguments]), 0)
        launch.assert_called_once_with(settings, "travel.py", arguments)

    def test_setup_uses_same_runtime_and_forwards_only_setup_options(self):
        settings = load_settings(environ={})
        with patch("runtime.load_settings", return_value=settings), patch("runtime.node_version"), \
                patch("runtime.server_launch"), patch("runtime.bootstrap") as bootstrap, \
                patch("runtime.launch", return_value=2) as launch:
            result = runtime.main(["setup-amap", "--bootstrap", "--apply", "--prompt-key", "--report", "private report.json"])
        self.assertEqual(result, 2)
        bootstrap.assert_called_once_with(settings)
        launch.assert_called_once_with(settings, "setup_amap.py", ["--apply", "--prompt-key", "--report", "private report.json"])

    def test_bootstrap_uses_configured_interpreter_and_venv_paths_without_shell(self):
        with tempfile.TemporaryDirectory(prefix="travel bootstrap ") as directory:
            settings = replace(load_settings(environ={}), python=str(Path(directory) / "Python Installation/python"),
                               venv_dir=Path(directory) / "new environment")
            with patch("runtime.python_version"), patch("runtime.subprocess.run") as run:
                runtime.bootstrap(settings, core_only=True)
            self.assertEqual(run.call_args_list[0].args[0], [settings.python, "-m", "venv", str(settings.venv_dir)])
            self.assertEqual(run.call_args_list[1].args[0][0], str(settings.venv_python))
            self.assertTrue(run.call_args_list[1].args[0][-1].endswith("requirements.txt"))
            self.assertTrue(all(not call.kwargs.get("shell") for call in run.call_args_list))

    def test_selected_config_reaches_child_even_from_another_directory(self):
        with tempfile.TemporaryDirectory(prefix="travel child ") as folder:
            config = Path(folder) / "runtime.toml"
            config.write_text('[paths]\ndata_dir="private data"\n', encoding="utf-8")
            # Exercise normalization on every host, including Linux where temp
            # paths normally have neither macOS symlinks nor Windows 8.3 aliases.
            alias_directory = Path(folder) / "alias directory"
            alias_directory.mkdir()
            selected = alias_directory / ".." / config.name
            settings = load_settings(selected)
            with patch("runtime.python_version"), patch("runtime.subprocess.run") as run:
                run.return_value.returncode = 0
                runtime.launch(settings, "travel.py", ["read", "demo"])
            forwarded = Path(run.call_args.kwargs["env"]["TRAVEL_PLANNER_RUNTIME_CONFIG"])
            self.assertTrue(forwarded.is_absolute())
            self.assertTrue(forwarded.samefile(selected))

    def test_cli_uses_configured_data_dir_and_explicit_cli_overrides_it(self):
        with tempfile.TemporaryDirectory(prefix="travel CLI ") as folder:
            config = Path(folder) / "runtime.toml"
            config.write_text('[paths]\ndata_dir="configured data"\n', encoding="utf-8")
            base = [sys.executable, str(SKILL / "scripts/runtime.py"), "--runtime-config", str(config), "run"]
            result = subprocess.run(base + ["init", "config-demo", "--title", "虚构测试", "--mock"],
                                    cwd=folder, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((Path(folder) / "configured data/trip-config-demo/HEAD.json").exists())
            override = Path(folder) / "explicit data"
            result = subprocess.run(base + ["--data-dir", str(override), "init", "cli-demo", "--title", "虚构测试", "--mock"],
                                    cwd=folder, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((override / "trip-cli-demo/HEAD.json").exists())

    def test_install_does_not_copy_machine_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "installed"
            shutil.copytree(SKILL, source, ignore=shutil.ignore_patterns("__pycache__", "*.local.toml"))
            (source / "config/runtime.local.toml").write_text('[paths]\ndata_dir="private"\n', encoding="utf-8")
            result = subprocess.run([sys.executable, str(source / "scripts/install.py"), "--destination", str(destination)],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((destination / "config/runtime.local.toml").exists())
            self.assertTrue((destination / "config/runtime.toml").is_file())


class SharedMCPTests(unittest.TestCase):
    def test_shared_arguments_are_preserved_by_platform_adapter(self):
        settings = replace(load_settings(environ={}), node="/fixture/node", npx="/fixture/npx", platform="darwin")
        shared = {"fixture": {"command": "npx", "args": ["--offline", "-y", "fixture@1", "--read-only"],
                              "enabled_tools": ["read"]}}
        with patch("travel_runtime.mcp.catalog", return_value=shared):
            result = server_definition("fixture", settings)
        self.assertEqual(result["args"], shared["fixture"]["args"])

    def test_windows_explicit_npx_cli_supports_nonstandard_npm_layout(self):
        with tempfile.TemporaryDirectory(prefix="npm installation ") as directory:
            cli = Path(directory) / "custom npm/npx-cli.js"
            cli.parent.mkdir()
            cli.write_text("// fixture", encoding="utf-8")
            command, args = server_launch(None, "node.exe", "win32", package="fixture@1", npx_cli=str(cli))
            self.assertEqual(command, "node.exe")
            self.assertEqual(args, [str(cli), "-y", "fixture@1"])
            with self.assertRaises(RuntimeConfigError):
                server_launch(None, "node.exe", "win32", npx_cli=str(cli.parent / "missing.js"))

    def test_all_platforms_share_packages_timeouts_and_whitelists(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / "node_modules/npm/bin/npx-cli.js"
            cli.parent.mkdir(parents=True)
            cli.write_text("// fixture", encoding="utf-8")
            definitions = catalog()
            for platform in ("darwin", "win32", "linux"):
                settings = replace(load_settings(platform=platform, environ={}), node=str(Path(directory) / "node.exe"),
                                   npx=str(Path(directory) / "npx.cmd") if platform == "win32" else "/fixture/npx")
                for name, shared in definitions.items():
                    result = server_definition(name, settings)
                    self.assertEqual(result["args"][-2:], shared["args"])
                    for field in ("enabled_tools", "startup_timeout_sec", "tool_timeout_sec"):
                        self.assertEqual(result[field], shared[field])
                    if name == "travel_rail":
                        self.assertFalse(result["enabled"])
                    self.assertNotIn("AMAP_MAPS_API_KEY", result["env"])

    @unittest.skipUnless(importlib.util.find_spec("tomlkit"), "tomlkit is optional")
    def test_verification_and_written_configuration_use_identical_launch_settings(self):
        import setup_amap
        settings = replace(load_settings(environ={}), node="/fixture/node", npx="/fixture/npx", platform="darwin",
                           environment={"HTTPS_PROXY": "http://example.invalid:1234", "PYTHONUTF8": "1"})
        definition = server_definition("travel_amap", settings, tool_names=setup_amap.READ_TOOLS, credential="SYNTHETIC")
        written = tomllib.loads(setup_amap.merged_config(b"", "SYNTHETIC", settings.npx, settings.node,
                                                        setup_amap.READ_TOOLS, settings).decode("utf-8"))
        server = written["mcp_servers"]["travel_amap"]
        self.assertEqual(server["command"], definition["command"])
        self.assertEqual(server["args"], definition["args"])
        self.assertEqual(server["env"]["HTTPS_PROXY"], settings.child_environment(settings.node)["HTTPS_PROXY"])
        self.assertEqual(server["enabled_tools"], definition["enabled_tools"])


if __name__ == "__main__":
    unittest.main()
