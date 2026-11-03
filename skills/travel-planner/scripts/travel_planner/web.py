"""Buildless, local-first travel website; explicit confirmed-snapshot export only."""

import copy
import json
import re
from urllib.parse import urlsplit

from .allocation import fit_trip, plan_document, prepare_plan
from .model import PACKAGE_ROOT, PlannerError, schema_errors
from .store import digest
from .transport import reference_source
from .validation import validate

THEMES = {"guide": "清爽攻略", "journal": "旅行杂志", "map": "地图工具"}


def map_configuration(config):
    if config is None:
        return None
    if not isinstance(config, dict) or set(config) != {"amap_key", "service_host"}:
        raise PlannerError("map_config", "地图配置仅接受浏览器 JS API 的 amap_key 和安全代理 service_host")
    key, host = config["amap_key"], config["service_host"]
    if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,128}", key):
        raise PlannerError("map_config", "请配置有效的浏览器 JS API Key；不能用 MCP 或 Web 服务 Key 代替")
    if not isinstance(host, str):
        raise PlannerError("map_config", "地图安全代理须为 HTTPS 地址")
    parsed = urlsplit(host)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(c.isspace() for c in host)):
        raise PlannerError("map_config", "地图安全代理须为无凭证、无查询参数的 HTTPS 地址")
    return {"amap_key": key, "service_host": host.rstrip("/")}


def map_data(trip):
    places = {p["id"]: p for p in trip["places"]}
    sources = {s["id"]: s for s in trip["sources"]}
    allowed = {"official", "provider", "user"} | ({"mock"} if trip["data_mode"] == "mock" else set())
    routes, pending = [], []
    def point(pid):
        p = places[pid]
        if p.get("coordinate_system") == "gcj02" and p["longitude"] is not None and p["latitude"] is not None:
            return [p["longitude"], p["latitude"]]
        return None
    used = {pid for day in trip["days"] for pid in (day["start_place_id"], day["end_place_id"])}
    selected = {rid for day in trip["days"] for rid in day["route_ids"]}
    for route in trip["routes"]:
        if route["id"] not in selected:
            continue
        used.update((route["from_place_id"], route["to_place_id"]))
        geometry = route.get("geometry")
        actual = bool(geometry and geometry["kind"] == "actual" and geometry["coordinate_system"] == "gcj02"
                      and geometry["source_ids"] and all(sources[sid]["reliable"] and sources[sid]["kind"] in allowed
                      and not reference_source(sources[sid]) for sid in geometry["source_ids"]))
        coordinates = geometry["coordinates"] if actual else None
        start, end = point(route["from_place_id"]), point(route["to_place_id"])
        if coordinates and start and end:
            # Prevent a path for another POI/entrance from being advertised as this route.
            if any(abs(a - b) > .01 for pair in ((coordinates[0], start), (coordinates[-1], end)) for a, b in zip(*pair)):
                actual, coordinates = False, None
        if not coordinates:
            coordinates = [start, end] if start and end else None
            pending.append(route["id"] + ("：仅顺序示意，缺少可用的真实路径" if coordinates else "：坐标或坐标系待核实"))
        routes.append({"id": route["id"], "kind": "actual" if actual else "schematic", "coordinates": coordinates})
    for day in trip["days"]:
        used.update(a["place_id"] for a in trip["activities"] if a["id"] in day["activity_ids"])
    for pid in sorted(used):
        if point(pid) is None:
            pending.append(places[pid]["name"] + "：位置或坐标系待核实，未在地图标点")
    return {"routes": routes, "points": {pid: point(pid) for pid in sorted(used)}, "pending": pending}


def web_files(store, trip, theme, config=None, generated_at=None):
    if theme not in THEMES:
        raise PlannerError("website_style_required", "请先选择网站风格：guide 清爽攻略、journal 旅行杂志或 map 地图工具")
    if trip["status"] != "confirmed":
        raise PlannerError("website_confirmation_required", "具体计划确认并保存后才能生成网站；草稿和待调整计划不生成")
    bundle = store._entity_path("trip-" + trip["trip_id"])
    change_id = bundle["change"].get("change_id")
    if not change_id or not any(d["kind"] == "plan_confirmation" and d["change_id"] == change_id
                                and trip["trip_id"] in d["target_ids"] for d in trip["decisions"]):
        raise PlannerError("website_confirmation_required", "缺少绑定当前计划变更的用户确认记录")
    report = validate(trip, as_of=generated_at)
    if not report["can_confirm"]:
        raise PlannerError("website_validation", "当前计划校验未通过，须修复或重新确认后再生成网站")
    if trip["request"]["currency"] != "CNY":
        raise PlannerError("website_currency", "当前网页预算编辑支持人民币；其他币种请使用原预算文档，不自动换算")
    config = map_configuration(config)
    mapping = map_data(trip)
    payload = {"trip_id": trip["trip_id"], "title": trip["title"], "revision": trip["revision"],
               "base_hash": digest(trip), "generated_at": generated_at, "timezone": trip["timezone"],
               "currency": trip["request"]["currency"], "total_minor": trip["request"]["budget_minor"],
               "data_mode": trip["data_mode"], "theme": theme, "places": trip["places"],
               "days": trip["days"], "activities": trip["activities"], "routes": trip["routes"],
               "scenic_visits": trip.get("scenic_visits", []), "map": mapping, "map_config": config,
               "budget_plan": prepare_plan(trip), "budget": report["budget"],
               "pending": report["pending"],
               "sources": [{k: s[k] for k in ("id", "provider", "url", "queried_at")} for s in trip["sources"]]}
    # The website needs no identities, orders, payment records, decision text or private configuration.
    # Application JSON must not terminate its script element, even with hostile supplier strings.
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("&", "\\u0026")
    template = PACKAGE_ROOT / "templates" / "web"
    files = {name: (template / name).read_text(encoding="utf-8") for name in ("index.html", "style.css", "budget.js", "app.js")}
    files["index.html"] = files["index.html"].replace("{{PAYLOAD}}", encoded)
    return files, {"theme": theme, "map_configured": config is not None, "map_pending": mapping["pending"],
                   "map_verified": False, "note": "地图接入配置不等于浏览器加载和实际地理路径已验收"}


def import_budget_draft(store, trip_id, draft):
    expected = {"format", "trip_id", "base_revision", "base_hash", "currency", "total_minor", "plan"}
    if not isinstance(draft, dict) or set(draft) != expected or draft["format"] != "travel-budget-draft/1":
        raise PlannerError("budget_draft", "预算草稿格式不正确")
    trip = store.read(trip_id)
    if (draft["trip_id"] != trip_id or draft["base_revision"] != trip["revision"]
            or draft["base_hash"] != digest(trip) or draft["currency"] != trip["request"]["currency"]):
        raise PlannerError("version_conflict", "草稿与当前计划不一致，请从最新版重新试算")
    candidate = copy.deepcopy(trip)
    candidate["request"]["budget_minor"] = draft["total_minor"]
    # Validates bounds/types, re-derives locks, fills omitted quotes and payment facts.
    plan = prepare_plan(candidate, draft["plan"])
    candidate["budget_plan"] = plan_document(plan)
    report = fit_trip(candidate)
    if trip["status"] in ("confirmed", "in_progress"):
        candidate["status"] = "detailed"
    change = store.propose(trip_id, candidate, reason="网页预算试算调整；不修改实际报价、订单或支付记录")
    return {"change": change, "allocation": report,
            "note": "仅生成待审核候选，未保存正式计划；需用户确认，再 commit，重新确认计划后更新网站"}
