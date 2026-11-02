"""Synthetic fixtures only: these tests do NOT establish live Amap capability."""

import asyncio
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/travel-planner/scripts"))
import setup_amap as setup


class KeyInputChecks(unittest.TestCase):
    def test_prompt_key_ignores_existing_environment_key(self):
        with patch.dict(os.environ, {"AMAP_MAPS_API_KEY": "OLD-SYNTHETIC-KEY"}), \
                patch("setup_amap.getpass.getpass", return_value="NEW-SYNTHETIC-KEY") as prompt:
            self.assertEqual(setup.read_key(True), ("NEW-SYNTHETIC-KEY", "local_prompt"))
            prompt.assert_called_once()

    def test_explicit_cli_environment_workflow_still_supported(self):
        with patch.dict(os.environ, {"AMAP_MAPS_API_KEY": "ENV-SYNTHETIC-KEY"}), \
                patch("setup_amap.getpass.getpass") as prompt:
            self.assertEqual(setup.read_key(False), ("ENV-SYNTHETIC-KEY", "environment"))
            prompt.assert_not_called()

    def test_accidentally_pasted_url_assignment_or_hidden_separator_rejected(self):
        for value in ("https://example.invalid/mcp?key=SYNTHETIC", "AMAP_MAPS_API_KEY=SYNTHETIC",
                      "SYNTHETIC KEY", "SYNTHETIC\u200bKEY"):
            with self.subTest(value=value), patch("setup_amap.getpass.getpass", return_value=value):
                with self.assertRaises(setup.SetupError) as error:
                    setup.read_key(True)
                self.assertNotIn(value, str(error.exception))


class DirectKeyDiagnosticChecks(unittest.TestCase):
    def test_direct_provider_rejection_is_separate_from_transport_success(self):
        key = "abcdef0123456789abcdef0123456789"
        response = io.BytesIO(json.dumps({"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}).encode())
        with patch("setup_amap.urllib.request.urlopen", return_value=response):
            result = setup.direct_key_diagnostic(key)
        self.assertTrue(result["diagnostic_completed"])
        self.assertFalse(result["api_success"])
        self.assertEqual(result["infocode"], "10001")
        self.assertEqual(result["key_length"], 32)
        self.assertTrue(result["looks_like_hex32"])
        self.assertNotIn(key, json.dumps(result))
        self.assertNotIn("?", result["endpoint"])

    def test_direct_success_and_network_failure_are_not_confused(self):
        response = io.BytesIO(b'{"status":"1","info":"OK","infocode":"10000"}')
        with patch("setup_amap.urllib.request.urlopen", return_value=response):
            self.assertTrue(setup.direct_key_diagnostic("SYNTHETIC-KEY")["api_success"])
        with patch("setup_amap.urllib.request.urlopen", side_effect=OSError("synthetic TLS/network error")):
            result = setup.direct_key_diagnostic("SYNTHETIC-KEY")
        self.assertFalse(result["diagnostic_completed"])
        self.assertFalse(result["api_success"])
        self.assertIn("network_error", result)


class BusinessChecks(unittest.TestCase):
    def call(self, name, args):
        async def result():
            if name == "maps_text_search":
                return {"pois": [{"id": "station" if "东站" in args["keywords"] else "lake", "name": args["keywords"]}]}
            if name == "maps_search_detail":
                return {"id": args["id"], "name": "杭州东站" if args["id"] == "station" else "西湖风景名胜区",
                        "city": "杭州市", "location": "120.21,30.29" if args["id"] == "station" else "120.14,30.24"}
            if name.startswith("maps_direction"):
                return {"route": {**args, "paths": [{"distance": "12000", "duration": "1800"}]}}
            if name == "maps_weather":
                today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
                return {"city": "杭州市", "forecasts": [{"date": today}]}
            raise AssertionError("unexpected test call")
        return result()

    def test_complete_fixture_flow(self):
        calls = []
        async def call(name, arguments):
            calls.append((name, arguments))
            return await self.call(name, arguments)
        result = asyncio.run(setup.business_checks(call))
        self.assertEqual(len(calls), 7)
        self.assertEqual(result["routes"]["driving"]["distance_km"], 12)
        self.assertEqual(result["routes"]["walking"]["duration_minutes"], 30)
        self.assertEqual(calls[4][1]["origin"], result["places"][0]["location"])

    def test_ambiguous_or_empty_place_fails(self):
        for payload in ({"pois": []}, {"pois": [{"id": "1", "name": "杭州东站东广场"}]},
                        {"pois": [{"id": "1", "name": "杭州东站"}, {"id": "2", "name": "杭州东站"}]}):
            with self.assertRaises(setup.SetupError):
                setup.poi_id(payload, "杭州东站")

    def test_city_prefix_grade_label_and_duplicate_id_are_supported(self):
        value = {"id": "lake", "name": "杭州市西湖风景名胜区（5A级景区）"}
        self.assertEqual(setup.poi_id({"pois": [value, dict(value)]}, "西湖风景名胜区"), "lake")
        self.assertEqual(setup.poi_id({"pois": [{"id": "lake", "name": "杭州西湖景区"}]}, "西湖风景名胜区"), "lake")

    def test_gate_is_not_automatically_treated_as_whole_scenic_area(self):
        with self.assertRaises(setup.PlaceSelectionError):
            setup.poi_id({"pois": [{"id": "gate", "name": "杭州西湖风景名胜区-东门"}]}, "西湖风景名胜区")

    def test_ambiguous_search_can_be_selected_then_fully_checked(self):
        selected_ids = []
        async def call(name, arguments):
            if name == "maps_text_search" and "西湖" in arguments["keywords"]:
                return {"pois": [{"id": "lake", "name": "西湖风景名胜区"},
                                 {"id": "other-lake", "name": "西湖风景名胜区"}]}
            return await self.call(name, arguments)
        async def choose(keyword, candidates):
            selected_ids.append((keyword, [p["id"] for p in candidates]))
            return "lake"
        result = asyncio.run(setup.business_checks(call, choose))
        self.assertEqual(selected_ids[0][1], ["lake", "other-lake"])
        self.assertEqual(result["places"][1]["selection_method"], "local_user")
        self.assertTrue(result["routes"]["driving"])

    def test_manual_selection_cannot_bypass_actual_candidates_or_city_check(self):
        async def choose_unknown(keyword, candidates):
            return "not-in-provider-results"
        async def search_ambiguous(name, arguments):
            if name == "maps_text_search":
                return {"pois": [{"id": "first", "name": "候选一"}, {"id": "second", "name": "候选二"}]}
            return await self.call(name, arguments)
        with self.assertRaises(setup.SetupError):
            asyncio.run(setup.business_checks(search_ambiguous, choose_unknown))
        with self.assertRaises(setup.SetupError):
            setup.checked_place({"id": "lake", "name": "西湖东门", "city": "别的城市", "location": "120.14,30.24"},
                                "lake", "西湖风景名胜区", "西湖东门")

    def test_local_choice_supports_retry_and_cancellation(self):
        candidates = [{"id": "1", "name": "候选一"}, {"id": "2", "name": "候选二"}]
        with patch("builtins.input", side_effect=["invalid", "2"]), patch("sys.stderr", io.StringIO()):
            self.assertEqual(setup.choose_poi_locally("测试地点", candidates), "2")
        with patch("builtins.input", return_value=""), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(setup.PlaceSelectionError):
                setup.choose_poi_locally("测试地点", candidates)

    def test_wrong_city_and_coordinates_fail(self):
        for city, location in (("上海市", "120.2,30.2"), ("杭州市", "0,0"), ("杭州市", "missing")):
            with self.assertRaises(setup.SetupError):
                setup.checked_place({"id": "1", "name": "杭州东站", "city": city, "location": location}, "1", "杭州东站")

    def test_route_missing_time_or_wrong_endpoints_fail(self):
        for route in ({"origin": "120,30", "destination": "120.1,30.1", "paths": []},
                      {"origin": "120,30", "destination": "120.1,30.1", "paths": [{"distance": 100, "duration": 0}]},
                      {"origin": "0,0", "destination": "120.1,30.1", "paths": [{"distance": 100, "duration": 10}]}):
            with self.assertRaises(setup.SetupError):
                setup.checked_route({"route": route}, "120,30", "120.1,30.1")

    def test_stale_weather_fails(self):
        with self.assertRaises(setup.SetupError):
            setup.checked_weather({"city": "杭州市", "forecasts": [{"date": "2020-01-01"}]})

    def test_exception_group_redacts_key(self):
        message = setup.error_message(ExceptionGroup("transport", [setup.SetupError("key=SYNTHETIC-KEY")]))
        self.assertNotIn("SYNTHETIC-KEY", setup.redact(message, "SYNTHETIC-KEY"))


class PlatformLaunchChecks(unittest.TestCase):
    def test_macos_keeps_native_npx_command(self):
        self.assertEqual(setup.server_launch("/test/npx", "/test/node", "darwin"),
                         ("/test/npx", ["-y", setup.PACKAGE]))

    def test_windows_uses_node_and_npx_js_with_spaces_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            node_dir = Path(folder) / "Program Files" / "nodejs"
            cli = node_dir / "node_modules/npm/bin/npx-cli.js"
            cli.parent.mkdir(parents=True)
            cli.write_text("// synthetic fixture")
            node, npx = str(node_dir / "node.exe"), str(node_dir / "npx.cmd")
            command, arguments = setup.server_launch(npx, node, "win32")
            self.assertEqual(command, node)
            # Windows may expand an 8.3 TEMP path to its long spelling.
            # Check file identity while retaining a separate path argument.
            self.assertTrue(Path(arguments[0]).samefile(cli))
            self.assertEqual(arguments[1:], ["-y", setup.PACKAGE])

    def test_missing_windows_npm_fails_before_config_write(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(setup.SetupError):
                setup.server_launch(str(Path(folder) / "npx.cmd"), str(Path(folder) / "node.exe"), "win32")

    def test_native_node_npx_launch_runs_offline(self):
        node, npx = shutil.which("node"), shutil.which("npx")
        if not node or not npx:
            self.skipTest("Node/npm not installed")
        command, args = setup.server_launch(npx, node)
        result = subprocess.run([command, *args[:-2], "--version"], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip())


@unittest.skipUnless(importlib.util.find_spec("tomlkit"), "optional Amap setup dependency not installed")
class ConfigChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "config.toml"
        self.original = b'# keep comment\nmodel = "test-model"\n[mcp_servers.other]\nurl = "https://example.invalid/mcp"\n'
        self.path.write_bytes(self.original)
        self.report = {"passed": True, "data_mode": "live", "tools": setup.READ_TOOLS}
        node_dir = Path(self.temp.name) / "Node Installation"
        cli = node_dir / "node_modules/npm/bin/npx-cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// synthetic fixture")
        self.node = str(node_dir / ("node.exe" if os.name == "nt" else "node"))
        self.npx = str(node_dir / ("npx.cmd" if os.name == "nt" else "npx"))

    def tearDown(self):
        self.temp.cleanup()

    def apply(self):
        return setup.apply_config(self.path, self.original, self.report, "SYNTHETIC-KEY", self.npx, self.node)

    def test_failed_or_mock_check_never_writes(self):
        for change in ({"passed": False}, {"data_mode": "mock"}):
            self.report.update(change)
            with self.assertRaises(setup.SetupError):
                self.apply()
            self.assertEqual(self.path.read_bytes(), self.original)
            self.report.update(passed=True, data_mode="live")

    def test_success_preserves_other_config_and_makes_backup(self):
        result = self.apply()
        self.assertEqual(Path(result["backup"]).read_bytes(), self.original)
        text = self.path.read_text()
        self.assertIn("# keep comment", text)
        parsed = tomllib.loads(text)
        self.assertEqual(parsed["model"], "test-model")
        self.assertEqual(parsed["mcp_servers"]["other"]["url"], "https://example.invalid/mcp")
        command, args = setup.server_launch(self.npx, self.node)
        self.assertEqual(parsed["mcp_servers"]["travel_amap"]["command"], command)
        self.assertEqual(parsed["mcp_servers"]["travel_amap"]["args"], args)
        self.assertEqual(parsed["mcp_servers"]["travel_amap"]["env"]["AMAP_MAPS_API_KEY"], "SYNTHETIC-KEY")
        if os.name != "nt":
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_existing_amap_transport_is_replaced_without_changing_other_server(self):
        existing = self.original + b'[mcp_servers.travel_amap]\nurl = "https://example.invalid/old-mcp"\n'
        text = setup.merged_config(existing, "SYNTHETIC-KEY", self.npx, self.node, setup.READ_TOOLS)
        parsed = tomllib.loads(text.decode())
        self.assertNotIn("url", parsed["mcp_servers"]["travel_amap"])
        self.assertIn("other", parsed["mcp_servers"])

    def test_external_edit_and_write_failure_preserve_current_config(self):
        self.path.write_bytes(self.original + b'\n# edited\n')
        with self.assertRaises(setup.SetupError):
            self.apply()
        self.path.write_bytes(self.original)
        with patch("setup_amap.os.replace", side_effect=OSError("synthetic write failure")):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(self.path.with_name("config.toml.travel-amap.lock").exists())

    def test_key_config_cannot_be_written_in_repository(self):
        marker = Path(self.temp.name) / ".git"
        marker.mkdir()
        (marker / "HEAD").write_text("ref: refs/heads/main\n")
        with self.assertRaises(setup.SetupError):
            self.apply()


if __name__ == "__main__":
    unittest.main()
