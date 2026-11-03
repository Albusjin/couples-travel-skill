"""Validate scenic visits against the same flat day timeline used by the core."""

from .model import timestamp


def check_scenic(trip, maps, errors, hard, sourced):
    for place in trip["places"]:
        seen, current = set(), place
        while current:
            if current["id"] in seen:
                errors.append({"code": "place_cycle", "target_id": place["id"], "message": "景区地点层级不能循环"})
                break
            seen.add(current["id"])
            current = maps["places"].get(current.get("parent_place_id"))
    for route in trip["routes"]:
        geometry = route.get("geometry")
        if geometry and geometry["kind"] == "actual" and not geometry["source_ids"]:
            errors.append({"code": "geometry_source", "target_id": route["id"], "message": "实际路径必须有取得坐标串的来源"})
    used = set()
    for visit in trip.get("scenic_visits", []):
        vid = visit["id"]
        day = maps["days"][visit["day_id"]]
        route_ids, activity_ids = visit["route_ids"], visit["activity_ids"]
        if (not set(route_ids).issubset(day["route_ids"])
                or not set(activity_ids).issubset(day["activity_ids"])):
            errors.append({"code": "scenic_day", "target_id": vid, "message": "景区内部路线和活动须纳入所属当天的同一时间线"})
            continue
        if used & (set(route_ids) | set(activity_ids)):
            errors.append({"code": "scenic_reuse", "target_id": vid, "message": "同一活动或路段不能重复属于两个景区游览组"})
        used.update(route_ids + activity_ids)
        routes = [maps["routes"][rid] for rid in route_ids]
        if not routes or not activity_ids:
            hard("scenic_detail", vid, "unknown", "大型景区须补齐内部景点、入口出口和串联路线")
            continue
        good = routes[0]["from_place_id"] == visit["entry_place_id"] and routes[-1]["to_place_id"] == visit["exit_place_id"]
        good = good and all(a["to_place_id"] == b["from_place_id"] for a, b in zip(routes, routes[1:]))
        positions = [day["route_ids"].index(rid) for rid in route_ids]
        if positions != sorted(positions):
            good = False
        hard("scenic_chain", vid, "pass" if good else "violation", "内部路线须按当天顺序连接选定入口与出口")
        nodes = {r[key] for r in routes for key in ("from_place_id", "to_place_id")}
        membership = True
        for pid in nodes | {maps["activities"][aid]["place_id"] for aid in activity_ids}:
            seen, current = set(), maps["places"][pid]
            while current and current["id"] != visit["scenic_place_id"] and current["id"] not in seen:
                seen.add(current["id"])
                current = maps["places"].get(current.get("parent_place_id"))
            if not current or current["id"] != visit["scenic_place_id"]:
                membership = False
        hard("scenic_membership", vid, "pass" if membership else "unknown", "园内节点与入口出口须明确关联所属景区，不能把外部转场当作内部路线")
        for aid in activity_ids:
            if maps["activities"][aid]["place_id"] not in nodes:
                hard("scenic_activity", aid, "violation", "内部景点没有接入景区路线")
    # Even a not-yet-grouped special transport must not bypass operating checks.
    scheduled = {rid for day in trip["days"] for rid in day["route_ids"]}
    for route in trip["routes"]:
        if route["id"] in scheduled:
            if route["mode"] not in ("shuttle", "cable_car", "elevator", "boat"):
                continue
            window = route.get("operating_window")
            if (not window or not sourced(window["source_ids"]) or not route["depart_at"]
                    or not window["last_departure_at"]):
                hard("scenic_operation", route["id"], "unknown", "园内接驳、索道、电梯或游船须核验运营时段和末班限制")
                continue
            departure = timestamp(route["depart_at"])
            last = timestamp(window["last_departure_at"])
            first = timestamp(window["first_departure_at"]) if window["first_departure_at"] else None
            if first and first > last:
                errors.append({"code": "operating_window", "target_id": route["id"], "message": "首班不能晚于末班"})
            hard("scenic_operation", route["id"], "pass" if departure <= last and (first is None or departure >= first) else "violation",
                 "计划乘坐时间须在核验的运营范围内，排队与步行另留缓冲")
