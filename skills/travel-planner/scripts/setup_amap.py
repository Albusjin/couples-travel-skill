#!/usr/bin/env python3
"""Local-only Amap business checks, followed by an optional private config write.

No account registration, credential upload, purchase, or provider simulation.
Run on the user's computer, never by passing a Key as a command-line argument.
"""

import argparse
import asyncio
import getpass
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import tomllib
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from travel_runtime import RuntimeConfigError as SetupError
from travel_runtime.config import load_settings
from travel_runtime.mcp import amap_settings, catalog, server_definition, server_launch

PACKAGE = catalog()["travel_amap"]["args"][-1]
SETUP_VERSION = "5"
SERVER_NAME = "travel_amap"
READ_TOOLS = catalog()[SERVER_NAME]["enabled_tools"]
REQUIRED_TOOLS = {"maps_text_search", "maps_search_detail", "maps_direction_driving",
                  "maps_direction_walking", "maps_weather"}


class PlaceSelectionError(SetupError):
    def __init__(self, keyword, candidates, reason="搜索结果不够明确，需要本机选择"):
        super().__init__(f"{keyword}：{reason}")
        self.keyword = keyword
        self.candidates = candidates


def stamp():
    return datetime.now(timezone.utc).isoformat()


def redact(text, key):
    return str(text).replace(key, "[REDACTED]") if key else str(text)


def read_key(prompt_key=False):
    value = "" if prompt_key else os.environ.get("AMAP_MAPS_API_KEY", "").strip()
    source = "environment" if value else "local_prompt"
    if not value:
        value = getpass.getpass("请输入高德 Web 服务 Key（不回显，不上传到聊天）：").strip()
    if not value or "placeholder" in value.lower() or "replace" in value.lower():
        raise SetupError("需要在本机输入真实 Web 服务 Key")
    if "://" in value or value.startswith("AMAP_MAPS_API_KEY="):
        raise SetupError("只粘贴控制台 Key 字段，不要粘贴 URL、环境变量赋值或整段配置")
    if any(character.isspace() or character in "\u200b\ufeff" for character in value):
        raise SetupError("Key 中包含空格、换行或不可见分隔符；请从控制台重新复制 Key 字段")
    return value, source


def direct_key_diagnostic(key):
    """Compare the same credential against a public-landmark API, without MCP.

    Return only status codes and input shape; never return the credential or URL query.
    This is diagnostic evidence only, never a substitute for MCP business checks.
    """
    endpoint = "https://restapi.amap.com/v3/geocode/geo"
    result = {"endpoint": endpoint, "queried_at": stamp(), "key_length": len(key),
              "looks_like_hex32": bool(re.fullmatch(r"[0-9a-fA-F]{32}", key)),
              "api_success": False, "diagnostic_completed": False}
    query = urllib.parse.urlencode({"key": key, "address": "杭州市杭州东站", "city": "杭州", "output": "json"})
    try:
        request = urllib.request.Request(endpoint + "?" + query, headers={"User-Agent": "TravelPlannerKeyCheck/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("高德直连诊断未返回 JSON 对象")
        result.update(diagnostic_completed=True, status=str(payload.get("status", "")),
                      info=redact(str(payload.get("info", "")), key),
                      infocode=str(payload.get("infocode", "")), api_success=str(payload.get("status")) == "1")
    except urllib.error.HTTPError as error:
        result["network_error"] = f"HTTP {error.code}；直连诊断未完成，不能据此判定 Key 有效性"
    except Exception as error:
        result["network_error"] = redact(str(error), key)[:400]
    return result


def error_message(error):
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(error_message(item) for item in error.exceptions)
    return str(error)


def positive(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return False
    return not isinstance(value, bool) and math.isfinite(number) and number > 0


def place_name(value):
    """Normalize city prefix and tourist-grade labels, preserving entrances/shops."""
    text = str(value).strip().replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^杭州市?", "", text)
    return re.sub(r"\((?:国家)?[1-5]A(?:级)?(?:旅游)?景区\)$", "", text, flags=re.I)


def place_aliases(keyword):
    canonical = place_name(keyword)
    if canonical == "西湖风景名胜区":
        return {canonical, "西湖景区"}
    return {canonical}


def poi_candidates(payload):
    values = payload.get("pois", [])
    if not isinstance(values, list):
        raise SetupError("地点搜索结果 pois 不是数组")
    distinct = {}
    for item in values:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] and isinstance(item.get("name"), str) and item["name"]:
            distinct.setdefault(item["id"], {key: item[key] for key in ("id", "name", "address", "typecode") if key in item})
    return list(distinct.values())


def poi_id(payload, keyword):
    candidates = poi_candidates(payload)
    exact = [p for p in candidates if place_name(p["name"]) in place_aliases(keyword)]
    if len(exact) != 1:
        raise PlaceSelectionError(keyword, candidates)
    return exact[0]["id"]


def choose_poi_locally(keyword, candidates):
    if not candidates:
        raise PlaceSelectionError(keyword, [], "高德返回空候选；尚未验证地点能力，未写配置")
    # Public test places only. No credentials or private travel data are displayed.
    print(f"\n“{keyword}”有多个候选或名称变体。以下只用于本次连通性测试：", file=sys.stderr)
    for index, item in enumerate(candidates, 1):
        print(f"  {index}. {item['name']} | {item.get('address', '地址未知')} | ID={item['id']}", file=sys.stderr)
    while True:
        answer = input("请选择正确测试地点的编号（0 或直接回车取消；不要输入 Key）：").strip()
        if answer in ("", "0"):
            raise PlaceSelectionError(keyword, candidates, "用户取消地点选择，未写配置")
        if answer.isdecimal() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]["id"]
        print("请输入上方候选编号，或输入 0 取消。", file=sys.stderr)


def checked_place(payload, expected_id, keyword, selected_name=None):
    expected_names = {place_name(selected_name)} if selected_name else place_aliases(keyword)
    if payload.get("id") != expected_id or place_name(payload.get("name", "")) not in expected_names or "杭州" not in str(payload.get("city", "")):
        raise SetupError("地点详情的 ID、名称或城市不匹配")
    location = payload.get("location", "")
    try:
        longitude, latitude = map(float, location.split(","))
    except (ValueError, TypeError, AttributeError):
        raise SetupError("地点没有可核验的经纬度") from None
    if not (119 < longitude < 121.5 and 29 < latitude < 31.5):
        raise SetupError("地点坐标不在本次杭州测试的合理范围内")
    return location


def checked_route(payload, origin, destination):
    route = payload.get("route", {})
    def point(value):
        try:
            return tuple(map(float, value.split(",")))
        except (ValueError, TypeError, AttributeError):
            raise SetupError("路线起终点坐标缺失") from None
    if point(route.get("origin")) != point(origin) or point(route.get("destination")) != point(destination):
        raise SetupError("路线返回的起终点与本次查询不一致")
    paths = [p for p in route.get("paths", []) if isinstance(p, dict)
             and positive(p.get("distance")) and positive(p.get("duration"))]
    if not paths:
        raise SetupError("路线没有有效的道路距离及耗时，不能宣布通过")
    return {"distance_m": float(paths[0]["distance"]), "duration_s": float(paths[0]["duration"]),
            "distance_km": float(paths[0]["distance"]) / 1000,
            "duration_minutes": float(paths[0]["duration"]) / 60}


def checked_weather(payload):
    if "杭州" not in str(payload.get("city", "")):
        raise SetupError("天气结果城市不匹配")
    try:
        days = [date.fromisoformat(item["date"]) for item in payload.get("forecasts", [])]
    except (ValueError, TypeError, KeyError):
        raise SetupError("天气结果没有有效日期") from None
    today = datetime.now(timezone(timedelta(hours=8))).date()
    if not days or not any(today <= day <= today + timedelta(days=7) for day in days):
        raise SetupError("天气没有覆盖当前或近期有效日期")
    return {"city": payload["city"], "covered_dates": [d.isoformat() for d in days]}


async def business_checks(call, choose=None):
    places = []
    for keyword in ("杭州东站", "西湖风景名胜区"):
        search = await call("maps_text_search", {"keywords": keyword, "city": "杭州"})
        candidates = poi_candidates(search)
        selection_method = "unique_name"
        try:
            selected = poi_id(search, keyword)
        except PlaceSelectionError:
            if choose is None:
                raise
            selected = await choose(keyword, candidates)
            selection_method = "local_user"
        selected_place = next((p for p in candidates if p["id"] == selected), None)
        if selected_place is None:
            raise SetupError("地点选择 ID 不在高德实际返回的候选中")
        detail = await call("maps_search_detail", {"id": selected})
        location = checked_place(detail, selected, keyword, selected_place["name"])
        places.append({"id": selected, "name": detail["name"], "city": detail["city"],
                       "location": location, "coordinate_system": "GCJ-02", "selection_method": selection_method})
    origin, destination = (p["location"] for p in places)
    routes = {}
    for mode, tool in (("driving", "maps_direction_driving"), ("walking", "maps_direction_walking")):
        raw = await call(tool, {"origin": origin, "destination": destination})
        routes[mode] = checked_route(raw, origin, destination)
    weather = checked_weather(await call("maps_weather", {"city": "330100"}))
    return {"places": places, "routes": routes, "weather": weather}


async def verify(key, npx, node, runtime=None):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from jsonschema import Draft202012Validator

    report = {"setup_tool_version": SETUP_VERSION, "provider": "amap", "package": PACKAGE, "started_at": stamp(),
              "data_mode": "live", "passed": False, "checks": [], "tools": [],
              "source": "https://lbs.amap.com/api/mcp-server/gettingstarted"}
    settings = amap_settings(npx, node, runtime)
    definition = server_definition(SERVER_NAME, settings, credential=key)
    parameters = StdioServerParameters(command=definition["command"], args=definition["args"],
                                       env=settings.child_environment(node, key))
    try:
        # Provider/SDK stderr may include request URLs; never forward or persist it.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            async with stdio_client(parameters, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=60)) as session:
                    initialized = await session.initialize()
                    report["server"] = initialized.serverInfo.model_dump()
                    tools, cursor = {}, None
                    seen_cursors = set()
                    while True:
                        listed = await session.list_tools(cursor=cursor)
                        tools.update({t.name: t for t in listed.tools})
                        cursor = listed.nextCursor
                        if cursor is None:
                            break
                        if cursor in seen_cursors:
                            raise SetupError("tools/list 返回重复游标")
                        seen_cursors.add(cursor)
                    report["tools"] = sorted(tools)
                    if not REQUIRED_TOOLS <= tools.keys():
                        raise SetupError("本次所需查询工具不完整")

                    async def call(name, arguments):
                        Draft202012Validator(tools[name].inputSchema).validate(arguments)
                        result = await session.call_tool(name, arguments)
                        texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
                        if result.isError:
                            raise SetupError("查询失败：" + name + "；" + " ".join(texts)[:300])
                        payload = getattr(result, "structuredContent", None)
                        if payload is None:
                            try:
                                payload = json.loads("\n".join(texts))
                            except ValueError:
                                raise SetupError("工具未返回可验证的 JSON 数据：" + name) from None
                        if not isinstance(payload, dict):
                            raise SetupError("工具结果结构不符合已审查版本：" + name)
                        report["checks"].append({"tool": name, "arguments": arguments, "queried_at": stamp(),
                                                 "result": payload})
                        return payload

                    async def choose(keyword, candidates):
                        return await asyncio.to_thread(choose_poi_locally, keyword, candidates)

                    report["business"] = await business_checks(call, choose)
                    report["passed"] = True
    except Exception as error:
        # ExceptionGroup/transport errors are surfaced without dumping SDK objects or headers.
        report["error"] = redact(error_message(error), key)[:1000]
        if "INVALID_USER_KEY" in report["error"]:
            report["error_code"] = "INVALID_USER_KEY"
            report["direct_key_diagnostic"] = await asyncio.to_thread(direct_key_diagnostic, key)
            diagnostic = report["direct_key_diagnostic"]
            if diagnostic["api_success"]:
                report["diagnosis"] = "同一 Key 的高德直连鉴权成功；MCP 查询仍失败，需排查 MCP 凭证传递或接口差异，不写配置"
            elif diagnostic.get("info") == "INVALID_USER_KEY":
                report["diagnosis"] = "MCP 与高德直连均拒绝同一输入值；高德后端未认可本次提交的 Key，需核对控制台或联系高德"
            elif diagnostic["diagnostic_completed"]:
                report["diagnosis"] = "直连接口返回了不同错误码；请按 infocode/info 核对服务权限，暂不推断具体原因"
            else:
                report["diagnosis"] = "直连诊断受网络或响应错误影响，根因尚未确定；原 MCP 鉴权错误保留"
            report["next_steps"] = [
                "高德拒绝了此次实际使用的 Key；已列出工具不代表 Key 鉴权通过",
                "从控制台重新复制 Key 字段，而不是安全密钥；核对 Key 有效状态和 Web 服务类型",
                "使用启动器重新在本机输入；或为 Python 命令添加 --prompt-key，忽略旧环境变量",
                "可分享 direct_key_diagnostic 中的状态码、长度和布尔标记；不要分享 Key 或完整配置"]
    report["completed_at"] = stamp()
    report["limitations"] = ["只验证本次杭州公共地点、路线和近期天气，不保证未来耗时或全部地图能力",
                              "未验证酒店房价、库存、余票、租车或专属导航入口"]
    return report


def merged_config(existing, key, npx, node, tool_names, runtime=None):
    import tomlkit
    document = tomlkit.parse(existing.decode("utf-8")) if existing else tomlkit.document()
    servers = document.setdefault("mcp_servers", tomlkit.table())
    settings = amap_settings(npx, node, runtime)
    server = server_definition(SERVER_NAME, settings, tool_names=tool_names, credential=key)
    server["enabled"] = True
    servers[SERVER_NAME] = server
    output = tomlkit.dumps(document).encode("utf-8")
    tomllib.loads(output.decode("utf-8"))
    return output


def apply_config(path, expected, report, key, npx, node, runtime=None):
    if report.get("passed") is not True or report.get("data_mode") != "live":
        raise SetupError("业务验证未通过，禁止写入配置")
    path = Path(path).expanduser()
    if path.is_symlink():
        raise SetupError("配置文件是符号链接，需先人工确认实际目标")
    path = path.parent.resolve() / path.name
    for parent in (path.parent, *path.parent.parents):
        if (parent / ".git").is_file() or (parent / ".git/HEAD").exists():
            raise SetupError("带 Key 的配置不能写入 Git 仓库")
    output = merged_config(expected, key, npx, node, report["tools"], runtime)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = path.with_name(path.name + ".travel-amap.lock")
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    except FileExistsError:
        raise SetupError("配置写入锁已存在；不覆盖其他写入") from None
    backup = None
    temporary = None
    try:
        current = path.read_bytes() if path.exists() else b""
        if current != expected:
            raise SetupError("测试期间配置发生变化；保留现状，重新运行")
        if path.exists():
            backup = path.with_name(path.name + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(current)
                stream.flush()
                os.fsync(stream.fileno())
        fd, temporary = tempfile.mkstemp(prefix=".travel-amap-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        return {"config": str(path), "backup": str(backup) if backup else None,
                "server": SERVER_NAME, "config_sha256": hashlib.sha256(output).hexdigest()}
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description="本机高德 MCP：真实测试通过后，才写入私有 Codex 配置")
    parser.add_argument("--apply", action="store_true", help="业务验证通过后备份并写入配置；默认只测试")
    parser.add_argument("--prompt-key", action="store_true", help="始终在本机输入 Key，忽略已有 AMAP_MAPS_API_KEY")
    parser.add_argument("--runtime-config", type=Path, help="本机运行配置；不同于 Codex config.toml")
    parser.add_argument("--config", type=Path, help="Codex 配置路径；优先于 CODEX_HOME/运行配置")
    parser.add_argument("--report", type=Path, help="可选：保存脱敏验证结果到本机私有目录")
    args = parser.parse_args()
    key = ""
    report = None
    try:
        for module in ("mcp", "tomlkit", "jsonschema"):
            __import__(module)
        settings = load_settings(args.runtime_config)
        npx, node = settings.npx, settings.node
        server_launch(npx, node, settings.platform, npx_cli=settings.npx_cli)
        path = args.config.expanduser() if args.config else settings.codex_config
        if args.report:
            if args.report.expanduser().resolve() == path.resolve():
                raise SetupError("报告路径不能与配置路径相同")
            if args.report.expanduser().exists() or args.report.expanduser().is_symlink():
                raise SetupError("报告路径已存在；请选择新报告文件，避免覆盖")
        existing = path.read_bytes() if path.exists() else b""
        if existing:
            tomllib.loads(existing.decode("utf-8"))
        key, credential_source = read_key(args.prompt_key)
        report = asyncio.run(asyncio.wait_for(verify(key, npx, node, settings), timeout=240))
        report["credential_source"] = credential_source
        report["configuration_written"] = False
        if args.apply and report["passed"]:
            report["configuration"] = apply_config(path, existing, report, key, npx, node, settings)
            report["configuration_written"] = True
            report["next"] = "完全退出并重开 Codex；新聊天复测工具可见性与真实查询"
        safe = redact(json.dumps(report, ensure_ascii=False, indent=2), key)
        if args.report:
            target = args.report.expanduser()
            # Never replace an existing report or a symlink with potentially sensitive data.
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(safe + "\n")
        print(safe)
        return 0 if report["passed"] else 2
    except (Exception, KeyboardInterrupt) as error:
        message = "已取消；配置是否提交请先检查本机文件" if isinstance(error, KeyboardInterrupt) else error_message(error)
        if isinstance(error, ModuleNotFoundError):
            message = "请先安装 requirements-amap-setup.txt 中的依赖"
        print(json.dumps({"setup_tool_version": SETUP_VERSION, "passed": bool(report and report.get("passed")),
                          "configuration_written": bool(report and report.get("configuration_written")),
                          "error": redact(message, key),
                          "next": "不提供 Key 到聊天；若已开始写入，请核对配置/备份后再重试"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
