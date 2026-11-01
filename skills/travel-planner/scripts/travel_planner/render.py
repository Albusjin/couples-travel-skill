"""Versioned Markdown views, all built from one loaded trip snapshot."""

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

from .budget import summarize
from .model import PACKAGE_ROOT, PlannerError, now
from .store import atomic_json, digest
from .validation import active, route_arrival, validate


def md(value):
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]")


def link(url):
    return f"[打开入口]({quote(url, safe=':/?=&%#@+;,')})" if url else "待取得入口"


def money(amount, currency):
    if amount is None:
        return "未知"
    if currency != "CNY":
        return f"{currency} {amount}（最小货币单位）"
    return f"{currency} {'-' if amount < 0 else ''}{abs(amount) // 100}.{abs(amount) % 100:02d}"


def views(trip, generated_at=None):
    generated_at = generated_at or now()
    report = validate(trip, as_of=generated_at)
    if report["errors"]:
        raise PlannerError("validation", "结构校验失败，不能生成输出", errors=report["errors"])
    budget = report["budget"]
    currency = budget["currency"]
    places = {p["id"]: p["name"] for p in trip["places"]}
    header = (f"计划：{md(trip['title'])} · {trip['trip_id']} · 修订 {trip['revision']}\n\n"
              f"生成时间：{generated_at} · 旅行时区：{trip['timezone']} · 状态：{trip['status']}\n\n"
              f"数据模式：{'模拟（不代表真实价格、库存或路线）' if trip['data_mode'] == 'mock' else '实际规划（以各项证据状态为准）'}\n\n")
    overview = ["## 本次需求", f"出发地：{md(places.get(trip['request']['origin'], '待询问'))}",
                f"目的地：{md('、'.join(places[p] for p in trip['request']['destinations']) or '待推荐')}",
                f"日期：{md(trip['request']['date_window'])}；人数：{len(trip['request']['travelers'])}",
                f"预算目标：{money(trip['request']['budget_minor'], currency)}；偏好档案版本：{md(trip['preferences_snapshot']['revision'])}",
                "## 候选方案", "| 方案 | 方式 | 费用（含参考的已知小计） | 门到门分钟 | 驾驶分钟 | 理由与取舍 |",
                "| --- | --- | --- | --- | --- | --- |"]
    for proposal in trip["proposals"]:
        amount = summarize(trip, proposal["quote_ids"], generated_at, proposal)
        overview.append(f"| {md(proposal['title'])}{'（已选择）' if proposal['id'] == trip['selected_proposal_id'] else ''} | {proposal['mode']} | "
                        f"{money(amount['known_subtotal_minor'], currency)}{'；未完整核实' if amount['pending_quote_ids'] else ''} | "
                        f"{proposal['door_to_door_minutes'] if proposal['door_to_door_minutes'] is not None else '未知'} | "
                        f"{proposal['driving_minutes'] if proposal['driving_minutes'] is not None else '未知'} | "
                        f"{md(proposal['summary'])}；优点：{md('；'.join(proposal['pros']))}；不足：{md('；'.join(proposal['cons']))}；风险：{md('；'.join(proposal['risks']))} |")
        overview[-1] = overview[-1][:-1] + f"住宿区域：{md('、'.join(proposal['areas']))}；景点：{md('、'.join(proposal['attractions']))} |"
    overview.extend(["## 交通、住宿与租车", "| 类型 | 安排 | 费用引用 | 核验及限制 |", "| --- | --- | --- | --- |"])
    for transport in trip["transports"]:
        if active(trip, transport):
            overview.append(f"| 交通 | {md(places[transport['from_place_id']])} → {md(places[transport['to_place_id']])}；{transport['mode']}；"
                            f"{md(transport['depart_at'])} → {md(transport['arrive_at'])} | {md(', '.join(transport['quote_ids']))} | "
                            f"门到门：{md(transport['door_to_door_minutes'])} 分钟；{md('；'.join(transport['transfer_notes']))} |")
    for hotel in trip["accommodations"]:
        if active(trip, hotel):
            overview.append(f"| 酒店 | {md(places[hotel['place_id']])}；{hotel['room_type']}；{hotel['rooms']} 间 / {hotel['guests']} 人；"
                            f"{hotel['check_in']} 至 {hotel['check_out']} | {md(', '.join(hotel['quote_ids']))} | "
                            f"{md(hotel['brand'])}；{md('；'.join(hotel['comfort_notes']))}；停车 {hotel['parking']}；早餐 {hotel['breakfast']}；"
                            f"最晚到店 {md(hotel['latest_check_in'])}；退改 {md(hotel['cancellation'])} |")
    for vehicle in trip["vehicles"]:
        if active(trip, vehicle):
            overview.append(f"| 租车 | {md(vehicle['class'])}；{vehicle['transmission']}；{vehicle['power']}；驾驶员 {md(', '.join(vehicle['driver_ids']))} | "
                            f"{md(', '.join(vehicle['quote_ids']))} | 取车 {md(vehicle['pickup_at'])} @ {md(places[vehicle['pickup_place_id']])}；"
                            f"还车 {md(vehicle['dropoff_at'])} @ {md(places[vehicle['dropoff_place_id']])}；"
                            f"驾驶员规则已核验 {vehicle['driver_rules_verified']}；异地已核验 {vehicle['one_way_verified']}；{md('；'.join(vehicle['notes']))} |")
            for stop in vehicle["energy_stops"]:
                overview.append(f"补能：{md(places[stop['place_id']])}；兼容 {stop['compatible']}；可用 {stop['availability']}；"
                                f"备用 {md(places.get(stop['backup_place_id'], '未知'))}")
    activities, routes = {v["id"]: v for v in trip["activities"]}, {v["id"]: v for v in trip["routes"]}
    route_lines = ["导航入口不代表路径耗时或可通行性已验证。", "| 日期 | 路段 | 方式 | 出发 | 含缓冲预计抵达 | 距离 km | 证据 | 导航 | 来源 |",
                   "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for day in sorted(trip["days"], key=lambda d: d["date"]):
        overview.extend([f"## {day['date']} · {md(day['id'])}",
                         f"步行：{md(day['walking_km'])} km；驾驶：{md(day['driving_minutes'])} 分钟",
                         "| 时间 | 活动 | 地点 | 开放/预约状态 |", "| --- | --- | --- | --- |"])
        for aid in day["activity_ids"]:
            a = activities[aid]
            overview.append(f"| {md(a['start_at'])} — {md(a['end_at'])}（{a['timing']}） | {md(a['label'])} | {md(places[a['place_id']])} | {a['access']}；{md('；'.join(a['notes']))} |")
        for rid in day["route_ids"]:
            r = routes[rid]
            arrival = route_arrival(r)
            line = (f"| {day['date']} | {md(places[r['from_place_id']])} → {md(places[r['to_place_id']])} | {r['mode']} | "
                    f"{md(r['depart_at'])} | {arrival.isoformat() if arrival else '未知'} | {md(r['distance_km'])} | {r['evidence']} | "
                    f"{link(r['navigation_url'])} | {md(', '.join(r['source_ids']))} |")
            route_lines.append(line)
            overview.append(f"交通：{md(places[r['from_place_id']])} → {md(places[r['to_place_id']])}，{r['mode']}，"
                            f"{md(r['duration_minutes'])} 分钟 + 缓冲 {sum(b['minutes'] for b in r['buffers'])} 分钟；{link(r['navigation_url'])}")
        for label, field in (("用餐/休息", "rest_notes"), ("自由活动", "free_time_notes"), ("天气风险", "weather_notes"), ("替代活动", "alternatives")):
            overview.append(f"{label}：{md('；'.join(day[field]) or '待补充')}")
    overview.extend(["## 预约、预订与锁定", "本地状态不代表第三方订单被修改。"])
    for booking in trip["bookings"]:
        overview.append(f"- {booking['id']} → {booking['target_id']}：{booking['status']}；确认来源 {md(booking['confirmation_source_id'])}；退改 {md(booking['cancellation_terms'])}")
    for group in ("activities", "transports", "accommodations", "vehicles"):
        for item in trip[group]:
            if item["locked"]:
                overview.append(f"- 已锁定：{item['id']}；已完成：{item['completed']}")
    overview.extend(["## 约束与待决定事项", f"当前硬约束校验：{'全部通过' if report['can_confirm'] else '尚不满足整份计划确认门槛'}；确认仍须用户决定。"])
    for item in report["hard_constraints"]:
        overview.append(f"- {item['result']} · {item['target_id']}：{md(item['message'])}")
    overview.extend([f"- 提醒 · {i['target_id']}：{md(i['message'])}" for i in report["warnings"]])
    overview.append("## 来源")
    for source in trip["sources"]:
        overview.append(f"- {source['id']}：{md(source['provider'])}；{source['kind']}；{source['queried_at']}；"
                        f"条件 {md(json.dumps(source['conditions'], ensure_ascii=False))}；{link(source['url'])}；{md(source['note'])}")
    overview.extend(["## 备注", *[md(n) for n in trip["notes"]]])

    budget_lines = ["| 费用 | 类别 | 单位 × 数量 | 已知金额 | 费用构成 | 状态 | 完整且有报价证据 |",
                    "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in budget["rows"]:
        components = "；".join(f"{md(c['label'])}（{'强制' if c['mandatory'] else '可选'}）：{money(c['amount_minor'], row['currency'])}" for c in row["components"])
        budget_lines.append(f"| {md(row['label'])}（{row['quote_id']}） | {row['category']} | {row['unit']} × {row['quantity']} | "
                            f"{money(row['known_amount_minor'], row['currency'])} | 基础单价 {money(row['unit_amount_minor'], row['currency'])}；{components or '无额外费用记录'} | {row['effective_status']} | {row['verified']} |")
    budget_lines.extend([f"已知小计（含估算/历史参考）：{money(budget['known_subtotal_minor'], currency)}",
                         f"其中有完整报价证据的小计：{money(budget['verified_subtotal_minor'], currency)}",
                         f"已完整核实的总预算：{money(budget['complete_verified_total_minor'], currency)}",
                         f"人均已知小计：{money(budget['known_subtotal_minor'], currency)} ÷ {len(trip['request']['travelers'])}（未核实费用另计）",
                         f"押金/预授权已知资金占用：{money(budget['deposit_hold_minor'], currency)}（不计消费，未知部分见清单）",
                         f"实际已付消费：{money(budget['paid_consumption_minor'], currency)}；已退款：{money(budget['refunded_consumption_minor'], currency)}",
                         "已查询不代表库存或最终成交价保证；预订前重新核验。"])
    pending = "## 未核实事项\n\n" + ("\n".join(f"- {i['target_id']}：{md(i['message'])}" for i in report["pending"]) or "暂无已记录的待核实项；不代表库存保证。")
    templates = PACKAGE_ROOT / "templates"
    content = {"overview.md": "\n\n".join(overview).replace("|\n\n|", "|\n|"),
               "budget.md": "\n\n".join(budget_lines).replace("|\n\n|", "|\n|"),
               "routes.md": "\n\n".join(route_lines).replace("|\n\n|", "|\n|")}
    return {name: (templates / "view.md").read_text(encoding="utf-8").replace("{{title}}", {"overview.md": "详细攻略与方案比较", "budget.md": "预算表", "routes.md": "路线索引"}[name]).replace("{{header}}", header).replace("{{body}}", body).replace("{{pending}}", pending)
            for name, body in content.items()}


def render(store, trip_id):
    trip = store.read(trip_id)
    namespace = "trip-" + trip_id
    generated_at = now()
    directory = store.path(namespace, "outputs", f"revision-{trip['revision']:08d}-{digest(trip)[:12]}-{uuid.uuid4().hex[:8]}")
    files = views(trip, generated_at)
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not directory.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".render-", dir=directory.parent))
        try:
            for name, content in files.items():
                (temporary / name).write_text(content, encoding="utf-8")
            atomic_json(temporary / "manifest.json", {"trip_id": trip_id, "revision": trip["revision"],
                                                       "document_hash": digest(trip), "generated_at": generated_at,
                                                       "validation_hash": digest(validate(trip, as_of=generated_at)),
                                                       "files": list(files)})
            os.rename(temporary, directory)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    # Never advertise old outputs for a new HEAD; all readers check this revision.
    if store.read(trip_id)["revision"] != trip["revision"]:
        raise PlannerError("version_conflict", "渲染过程中计划已更新；历史输出保留，请渲染最新版")
    atomic_json(store.path(namespace, "OUTPUTS.json"), {"revision": trip["revision"], "directory": directory.name})
    return {"revision": trip["revision"], "directory": str(directory), "files": [str(directory / name) for name in files]}


def output_status(store, trip_id):
    trip = store.read(trip_id)
    path = store.path("trip-" + trip_id, "OUTPUTS.json")
    record = json.loads(path.read_text()) if path.exists() else None
    complete = False
    if record and record["revision"] == trip["revision"]:
        directory = store.path("trip-" + trip_id, "outputs", record["directory"])
        complete = all((directory / name).is_file() for name in ("overview.md", "budget.md", "routes.md", "manifest.json"))
        if complete:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            complete = manifest["document_hash"] == digest(trip) and manifest["validation_hash"] == digest(validate(trip))
    return {"revision": trip["revision"], "outputs_current": bool(complete),
            "last_output_revision": record["revision"] if record else None}
