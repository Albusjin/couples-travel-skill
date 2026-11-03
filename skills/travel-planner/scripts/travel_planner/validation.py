"""Structural/reference errors block writes; planning findings remain draftable."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .budget import summarize
from .model import effective_preferences, schema_errors, timestamp
from .transport import quote_transports, reference_source

COLLECTIONS = ("places", "proposals", "transports", "vehicles", "accommodations", "activities",
               "routes", "days", "quotes", "bookings", "expenses", "sources", "decisions", "scenic_visits")
LOCKABLE = ("transports", "vehicles", "accommodations", "activities")
DETAILED = {"detailed", "confirmed", "in_progress", "completed"}


def active(trip, item):
    return item.get("proposal_id") in (None, trip["selected_proposal_id"])


def route_arrival(route):
    if route["depart_at"] is None or route["duration_minutes"] is None:
        return None
    return timestamp(route["depart_at"]) + timedelta(
        minutes=route["duration_minutes"] + sum(b["minutes"] for b in route["buffers"]))


def validate(trip, as_of=None):
    errors = schema_errors(trip)
    result = {"errors": errors, "hard_constraints": [], "warnings": [], "pending": [],
              "budget": None, "can_confirm": False, "data_mode": trip.get("data_mode") if isinstance(trip, dict) else None}
    if errors:
        return result
    maps = {key: {item["id"]: item for item in trip.get(key, [])} for key in COLLECTIONS}
    all_ids = {trip["trip_id"]}
    for key in COLLECTIONS:
        for item in trip.get(key, []):
            if item["id"] in all_ids:
                errors.append({"code": "duplicate_id", "message": "稳定 ID 必须全局唯一", "target_id": item["id"]})
            all_ids.add(item["id"])
    travelers = {t["id"]: t for t in trip["request"]["travelers"]}
    for tid in [t["id"] for t in trip["request"]["travelers"]]:
        if tid in all_ids:
            errors.append({"code": "duplicate_id", "target_id": tid, "message": "旅行者 ID 重复"})
        all_ids.add(tid)

    def link(value, allowed, owner, field):
        if value is not None and value not in allowed:
            errors.append({"code": "reference", "target_id": owner, "field": field,
                           "message": f"引用不存在：{value}"})

    targets = {"origin": maps["places"], "place_id": maps["places"],
               "from_place_id": maps["places"], "to_place_id": maps["places"],
               "start_place_id": maps["places"], "end_place_id": maps["places"],
               "pickup_place_id": maps["places"], "dropoff_place_id": maps["places"],
               "backup_place_id": maps["places"], "proposal_id": maps["proposals"],
               "selected_proposal_id": maps["proposals"], "accommodation_id": maps["accommodations"],
               "transport_id": maps["transports"],
               "hotel_route_id": maps["routes"], "confirmation_source_id": maps["sources"],
               "hotel_exception_decision_id": maps["decisions"], "quote_id": maps["quotes"],
               "source_ids": maps["sources"], "quote_ids": maps["quotes"], "cost_quote_ids": maps["quotes"],
               "route_ids": maps["routes"], "activity_ids": maps["activities"],
               "driver_ids": travelers, "destinations": maps["places"], "must_visit": maps["places"],
               "excluded_places": maps["places"], "target_id": all_ids, "depends_on_ids": all_ids,
               "parent_place_id": maps["places"], "scenic_place_id": maps["places"],
               "entry_place_id": maps["places"], "exit_place_id": maps["places"], "day_id": maps["days"]}

    def walk(value, owner="trip"):
        if isinstance(value, dict):
            owner = value.get("id", owner)
            for field, item in value.items():
                if field in targets:
                    values = item if isinstance(item, list) else [item]
                    if isinstance(item, list) and len(item) != len(set(item)):
                        errors.append({"code": "duplicate_reference", "target_id": owner, "field": field,
                                       "message": "引用列表不能重复计费或重复执行"})
                    for v in values:
                        link(v, targets[field], owner, field)
                if field not in ("conditions", "expected_conditions", "details", "values", "overrides"):
                    walk(item, owner)
        elif isinstance(value, list):
            for item in value:
                walk(item, owner)
    walk(trip)
    if errors:
        return result
    zone = ZoneInfo(trip["timezone"])

    def hard(code, target, state, message):
        result["hard_constraints"].append({"code": code, "target_id": target, "result": state, "message": message})
        if state == "unknown":
            result["pending"].append({"code": code, "target_id": target, "message": message})

    def warn(code, target, message):
        result["warnings"].append({"code": code, "target_id": target, "message": message})

    def sourced(ids):
        allowed = {"official", "provider", "user"} | ({"mock"} if trip["data_mode"] == "mock" else set())
        return bool(ids) and all(maps["sources"][sid]["reliable"] and maps["sources"][sid]["kind"] in allowed
                                 and not reference_source(maps["sources"][sid]) for sid in ids)

    req = trip["request"]
    hard("origin", trip["trip_id"], "pass" if req["origin"] else "unknown", "出发地须由用户提供")
    window = req["date_window"]
    hard("dates", trip["trip_id"], "pass" if window else "unknown", "需明确日期或待选择的日期范围")
    if window and window["end"] < window["start"]:
        errors.append({"code": "dates", "message": "结束日期早于开始日期"})
    if not travelers:
        errors.append({"code": "travelers", "message": "旅行人数必须大于零"})
    if trip["status"] in {"selected", *DETAILED}:
        hard("selection", trip["trip_id"], "pass" if trip["selected_proposal_id"] else "unknown", "详细规划须先选定方案")
    if trip["status"] == "proposals_ready" and not trip["proposals"]:
        errors.append({"code": "proposals", "message": "候选就绪状态必须存在候选方案"})
    if len(trip["proposals"]) == 1:
        warn("comparison", trip["trip_id"], "通常应提供 2–3 个方案；若仅一个可行方案，应解释原因")
    if set(req["must_visit"]) & set(req["excluded_places"]):
        hard("places_conflict", trip["trip_id"], "violation", "必去与排除地点冲突，需用户决定")
    for condition in req["constraints"]:
        state = condition["result"]
        if state == "pass" and condition["level"] == "hard" and not sourced(condition["source_ids"]):
            state = "unknown"
        if condition["level"] == "hard":
            hard("user_constraint", condition["id"], state, condition["description"])
        elif state != "pass":
            warn("preference", condition["id"], condition["description"])

    from .scenic import check_scenic
    check_scenic(trip, maps, errors, hard, sourced)
    if errors:
        return result

    for booking in trip["bookings"]:
        if booking["status"] in ("booked", "completed", "cancelled"):
            sid = booking["confirmation_source_id"]
            hard("booking_evidence", booking["id"], "pass" if sid and sourced([sid]) else "unknown",
                 "已预订或已完成须有可靠确认；本地修改不改变外部订单")
            if not sid or not sourced([sid]):
                errors.append({"code": "booking_evidence", "target_id": booking["id"], "message": "不得在缺乏可靠确认时提升预订、完成或取消事实"})
        if booking["status"] in ("booked", "change_pending", "completed"):
            for group in LOCKABLE:
                item = maps[group].get(booking["target_id"])
                if item and not item["locked"]:
                    errors.append({"code": "booking_lock", "target_id": item["id"], "message": "已预订项目必须锁定"})
    for expense in trip["expenses"]:
        if expense["status"] in ("paid", "refunded") and expense["paid_at"] is None:
            errors.append({"code": "payment_time", "target_id": expense["id"], "message": "支付或退款须记录时间"})

    for vehicle in trip["vehicles"]:
        if not vehicle["recommended"] or not active(trip, vehicle):
            continue
        vid = vehicle["id"]
        hard("automatic", vid, {"automatic": "pass", "manual": "violation", "unknown": "unknown"}[vehicle["transmission"]],
             "租车仅推荐自动挡")
        drivers = vehicle["driver_ids"]
        planned = {t["id"] for t in req["travelers"] if t["planned_driver"]}
        verified = vehicle["driver_rules_verified"] and bool(drivers) and planned.issubset(drivers) and sourced(vehicle["source_ids"])
        hard("drivers", vid, "pass" if verified else "unknown", "核验全部计划驾驶员的资格、登记限制及额外费用")
        if vehicle["pickup_place_id"] != vehicle["dropoff_place_id"]:
            hard("one_way", vid, "pass" if vehicle["one_way_verified"] and sourced(vehicle["source_ids"]) else "unknown",
                 "异地还车须核验门店、时段、限制及额外费用")
        if not vehicle["pickup_at"] or not vehicle["dropoff_at"]:
            hard("rental_period", vid, "unknown", "取还车时间未知，不能核实实际租期费用")
        elif timestamp(vehicle["dropoff_at"]) <= timestamp(vehicle["pickup_at"]):
            hard("rental_period", vid, "violation", "还车必须晚于取车")
        if vehicle["power"] in ("electric", "hybrid", "range_extender"):
            sufficient = all(vehicle[k] is not None for k in ("range_km", "departure_energy_percent", "reserve_percent"))
            if sufficient:
                sufficient = vehicle["range_km"] > 0 and vehicle["departure_energy_percent"] > vehicle["reserve_percent"]
            hard("energy_inputs", vid, "pass" if sufficient else "unknown", "新能源路线需续航、出发电量及安全余量")
            for stop in vehicle["energy_stops"]:
                good = (stop["compatible"] == "yes" and stop["availability"] == "verified"
                        and stop["backup_place_id"] and sourced(stop["source_ids"]))
                hard("energy_stop", stop["place_id"], "pass" if good else "unknown", "核验兼容、可用性、绕行和备用补能点")
                if stop["arrival_percent"] is not None and vehicle["reserve_percent"] is not None:
                    hard("energy_reserve", stop["place_id"], "pass" if stop["arrival_percent"] >= vehicle["reserve_percent"] else "violation",
                         "预计抵达电量不得低于安全余量")
            warn("energy_review", vid, "逐段核对路程与可用续航；基础校验不能替代真实补能可用性验证")
            if sufficient and vehicle["power"] == "electric":
                remaining = vehicle["departure_energy_percent"]
                stops = {s["place_id"]: s for s in vehicle["energy_stops"]}
                driving = [maps["routes"][rid] for day in sorted(trip["days"], key=lambda d: d["date"])
                           for rid in day["route_ids"] if maps["routes"][rid]["mode"] == "drive"]
                energy_state = "pass" if driving else "unknown"
                for route in driving:
                    if route["distance_km"] is None:
                        energy_state = "unknown" if energy_state != "violation" else energy_state
                        continue
                    remaining -= route["distance_km"] / vehicle["range_km"] * 100
                    if remaining < vehicle["reserve_percent"]:
                        energy_state = "violation"
                    stop = stops.get(route["to_place_id"])
                    if stop:
                        if stop["departure_percent"] is None:
                            energy_state = "unknown" if energy_state != "violation" else energy_state
                        else:
                            remaining = stop["departure_percent"]
                hard("energy_route", vid, energy_state, "按逐段道路里程核对续航与安全余量；补能后电量须明确")
        if vehicle["same_group_only"]:
            warn("vehicle_group", vid, "同组车型交付，不保证具体型号或配置")

    prefs = effective_preferences(trip)
    room_type = prefs.get("hotel_room_type", "double")
    for hotel in trip["accommodations"]:
        if not active(trip, hotel):
            continue
        hard("hotel_policies", hotel["id"], "pass" if hotel["policies_verified"] and sourced(hotel["source_ids"]) else "unknown",
             "需核验房型、双人入住及最晚到店/退改规则；报价未知不代表入住规则已核验")
        hard("room_type", hotel["id"], "unknown" if hotel["room_type"] == "unknown" else
             ("pass" if hotel["room_type"] == room_type else "violation"), "房型须符合本次明确要求，默认大床房")
        hard("occupancy", hotel["id"], "pass" if hotel["guests"] >= len(travelers) and hotel["rooms"] == prefs.get("hotel_rooms", 1)
             else "violation", "按实际人数及房间数核验入住容量")
        nights = (date.fromisoformat(hotel["check_out"]) - date.fromisoformat(hotel["check_in"])).days
        if nights <= 0:
            errors.append({"code": "hotel_nights", "target_id": hotel["id"], "message": "离店日期须晚于入住日期"})
        for qid in hotel["quote_ids"]:
            q = maps["quotes"][qid]
            if q["category"] == "hotel" and (q["unit"] != "room_night" or q["quantity"] != nights * hotel["rooms"]):
                errors.append({"code": "room_nights", "target_id": qid, "message": "酒店按房间×实际晚数计费，不乘人数"})
            if q["category"] == "hotel" and q["unit_amount_minor"] is not None and q["unit_amount_minor"] > prefs["hotel_budget_minor"][1]:
                warn("hotel_budget", hotel["id"], "酒店超过适用房晚预算偏好；展示原因与低价备选")
    for transport in trip["transports"]:
        tid = transport["id"]
        if transport.get("taxi_details"):
            details = transport["taxi_details"]
            if transport["mode"] != "taxi" or details["passengers"] != len(travelers):
                errors.append({"code": "taxi_passengers", "target_id": tid, "message": "打车人数须匹配实际旅行人数，车型信息仅用于 taxi 交通"})
            if active(trip, transport) and details["passenger_capacity"] is not None and details["passenger_capacity"] < details["passengers"]:
                hard("taxi_capacity", tid, "violation", "一辆车的已知乘客容量不足，须重新选择车型并核实行李空间")
        reference = transport.get("rail_reference")
        if reference:
            if (transport["mode"] != "rail" or reference["reference_date"] >= reference["target_date"]
                    or (window and not window["start"] <= reference["target_date"] <= window["end"])
                    or (transport["depart_at"] and timestamp(transport["depart_at"]).astimezone(zone).date().isoformat() != reference["target_date"])):
                errors.append({"code": "rail_reference_dates", "target_id": tid, "message": "参考日须早于目标日；目标日须匹配本次旅行及交通出发日期"})
        if active(trip, transport):
            if reference:
                hard("rail_schedule", tid, "unknown", f"目标日 {reference['target_date']} 尚未核验，使用 {reference['reference_date']} 的参考班次；目标日时刻、票价和余票须复核")
            if transport["mode"] == "taxi":
                warn("taxi_estimate", tid, "按实际人数合乘一辆车，费用不乘人数；车型容量、行李、上车点、候车与动态价格出发前复核")
            if transport["depart_at"] and transport["arrive_at"] and timestamp(transport["arrive_at"]) <= timestamp(transport["depart_at"]):
                errors.append({"code": "transport_time", "target_id": transport["id"], "message": "交通抵达时间须晚于出发"})
            if transport["depart_at"] and transport["arrive_at"] and transport["door_to_door_minutes"] is not None:
                elapsed = (timestamp(transport["arrive_at"]) - timestamp(transport["depart_at"])).total_seconds() / 60
                if transport["door_to_door_minutes"] < elapsed:
                    errors.append({"code": "door_to_door", "target_id": transport["id"], "message": "门到门时间不能小于交通段运行时间"})
            for qid in transport["quote_ids"]:
                q = maps["quotes"][qid]
                if q["unit"] == "person" and q["quantity"] != len(travelers):
                    errors.append({"code": "person_quantity", "target_id": qid, "message": "按人计价须覆盖实际人数"})

    for quote in trip["quotes"]:
        taxi_targets = [t for t in quote_transports(trip, quote) if t["mode"] == "taxi"]
        if any(r["id"] == quote["target_id"] and r["mode"] == "taxi" for r in trip["routes"]):
            taxi_targets.append(quote)
        if taxi_targets and quote["category"] == "transport" and (quote["unit"] != "trip" or quote["quantity"] != 1):
            errors.append({"code": "taxi_quantity", "target_id": quote["id"], "message": "单程打车按一辆车计费：unit=trip、quantity=1，不得乘两人或重复计两辆车"})

    # Referenced activities/routes form one chronological chain per day.
    visiting, visited = set(), set()
    def check_cycle(rid):
        if rid in visiting:
            errors.append({"code": "dependency_cycle", "target_id": rid, "message": "路线依赖形成循环"})
            return
        if rid in visited:
            return
        visiting.add(rid)
        for dep in maps["routes"][rid]["depends_on_ids"]:
            if dep in maps["routes"]:
                check_cycle(dep)
        visiting.remove(rid)
        visited.add(rid)
    for rid in maps["routes"]:
        check_cycle(rid)
    seen_dates, used_activities, used_routes = set(), set(), set()
    for day in trip["days"]:
        did = day["id"]
        if day["date"] in seen_dates:
            errors.append({"code": "day_duplicate", "target_id": did, "message": "同一天只能有一个行程对象"})
        seen_dates.add(day["date"])
        if window and not window["start"] <= day["date"] <= window["end"]:
            errors.append({"code": "day_range", "target_id": did, "message": "行程日期不在旅行范围内"})
        events = []
        for aid in day["activity_ids"]:
            activity = maps["activities"][aid]
            if aid in used_activities:
                errors.append({"code": "activity_reuse", "target_id": aid, "message": "活动不能重复出现在多天"})
            used_activities.add(aid)
            state = {"verified": "pass", "closed": "violation", "reservation_failed": "violation", "unknown": "unknown"}[activity["access"]]
            if state == "pass" and not sourced(activity["source_ids"]):
                state = "unknown"
            if activity["requires_reservation"] and not activity["reservation_verified"] and state == "pass":
                state = "unknown"
            hard("activity_access", aid, state, "景点开放、最后入园和预约须核验；失败时提供替代活动")
            if activity["place_id"] in req["excluded_places"]:
                hard("excluded_place", aid, "violation", "行程包含用户排除地点")
            if activity["start_at"] and activity["end_at"]:
                start, end = timestamp(activity["start_at"]), timestamp(activity["end_at"])
                if end <= start:
                    errors.append({"code": "activity_time", "target_id": aid, "message": "活动结束须晚于开始"})
                if start.astimezone(zone).date().isoformat() != day["date"]:
                    errors.append({"code": "activity_date", "target_id": aid, "message": "活动起始日期须与所属日一致"})
                events.append((start, end, activity["place_id"], activity["place_id"], aid))
            else:
                hard("activity_time", aid, "unknown", "活动时间范围未知，不能核验冲突")
        for rid in day["route_ids"]:
            route = maps["routes"][rid]
            if rid in used_routes:
                errors.append({"code": "route_reuse", "target_id": rid, "message": "交通段不能重复执行"})
            used_routes.add(rid)
            arrival = route_arrival(route)
            transport = maps["transports"].get(route["transport_id"])
            if route["mode"] == "taxi" and (not transport or transport["mode"] != "taxi"):
                warn("taxi_transport", rid, "打车路段尚未关联 taxi 交通记录；按一车规划，需补充单车费用、人数和接驳时间，兼容旧路线记录")
            if transport:
                good = (route["from_place_id"] == transport["from_place_id"]
                        and route["to_place_id"] == transport["to_place_id"]
                        and route["depart_at"] is not None and transport["depart_at"] is not None
                        and timestamp(route["depart_at"]) == timestamp(transport["depart_at"]))
                if arrival and transport["arrive_at"]:
                    good = good and arrival >= timestamp(transport["arrive_at"])
                hard("transport_route", rid, "pass" if good else "violation", "日程路线必须保留关联交通安排的起终点和固定出发时间，抵达不能早于已知时刻")
            verified = (route["evidence"] == "verified" and sourced(route["source_ids"])
                        and not (transport and transport.get("rail_reference")))
            hard("route_time", rid, "pass" if arrival and verified else "unknown", "路线耗时须可核验，导航链接不能替代耗时证据")
            if not route["navigation_url"]:
                result["pending"].append({"code": "navigation", "target_id": rid, "message": "未取得可打开的导航入口"})
            if arrival:
                start = timestamp(route["depart_at"])
                if start.astimezone(zone).date().isoformat() != day["date"]:
                    errors.append({"code": "route_date", "target_id": rid, "message": "交通段出发日期须与所属日一致"})
                events.append((start, arrival, route["from_place_id"], route["to_place_id"], rid))
                if arrival.astimezone(zone).date() != start.astimezone(zone).date() and not day["hotel_exception_decision_id"]:
                    hard("overnight", rid, "violation", "跨夜交通须逐次明确确认例外")
            for dependency in route["depends_on_ids"]:
                if dependency == rid:
                    errors.append({"code": "dependency_cycle", "target_id": rid, "message": "路线不能依赖自身"})
        events.sort(key=lambda item: item[0])
        previous_place, previous_end = day["start_place_id"], None
        for start, end, origin, destination, eid in events:
            if origin != previous_place:
                hard("continuity", eid, "violation", "活动或交通起点与上一站不一致；补充转场或重新规划")
            if previous_end and start < previous_end:
                hard("overlap", eid, "violation", "活动与交通（含缓冲）存在时间冲突")
            previous_place, previous_end = destination, end
        if events and previous_place != day["end_place_id"]:
            hard("day_end", did, "violation", "每日终点与最后一站不一致")
        if not events:
            hard("empty_day", did, "unknown", "每日时间及路线尚未完整")
        if day["walking_km"] is None:
            warn("walking", did, "步行距离待核实")
        elif not prefs["walking_km"][0] <= day["walking_km"] <= prefs["walking_km"][1]:
            warn("walking", did, "步行距离偏离适用偏好范围，说明取舍及替代安排")
        if any(maps["routes"][rid]["mode"] == "drive" for rid in day["route_ids"]):
            if day["driving_minutes"] is None or not day["rest_notes"]:
                hard("driving_rest", did, "unknown", "驾驶总量与休息安排须逐日评估，两名驾驶员不免除疲劳检查")
            durations = [maps["routes"][rid]["duration_minutes"] for rid in day["route_ids"] if maps["routes"][rid]["mode"] == "drive"]
            if all(n is not None for n in durations) and day["driving_minutes"] is not None and day["driving_minutes"] != sum(durations):
                errors.append({"code": "driving_total", "target_id": did, "message": "每日驾驶分钟数必须与道路驾驶段相加一致（缓冲另计）"})

        exception = maps["decisions"].get(day["hotel_exception_decision_id"])
        approved = bool(exception and exception["kind"] == "hotel_exception" and did in exception["target_ids"]
                        and exception["details"].get("date") == day["date"])
        if day["hotel_exception_decision_id"] and not approved:
            errors.append({"code": "exception_scope", "target_id": did, "message": "酒店例外必须由用户确认并明确目标日及日期"})
        if approved:
            warn("hotel_exception", did, "已记录本次用户确认的酒店/跨夜例外：" + exception["summary"])
        hotel = maps["accommodations"].get(day["accommodation_id"])
        final_route = maps["routes"].get(day["hotel_route_id"])
        if approved and exception["details"].get("no_hotel") is True:
            hard("hotel_arrival", did, "pass", "当日无需酒店的单次例外已明确确认")
        elif not hotel or not final_route:
            hard("hotel_arrival", did, "unknown", "须安排到酒店的返程；无住宿日也须明确确认适用规则")
        else:
            if final_route["id"] not in day["route_ids"] or final_route["to_place_id"] != hotel["place_id"] or day["end_place_id"] != hotel["place_id"]:
                hard("hotel_route", did, "violation", "酒店返程必须纳入每日路线并以实际酒店为终点")
            if not hotel["check_in"] <= day["date"] < hotel["check_out"]:
                hard("hotel_date", did, "violation", "酒店日期未覆盖该晚住宿")
            arrival = route_arrival(final_route)
            cutoff = datetime.combine(date.fromisoformat(day["date"]), time(22), zone)
            if approved and exception["details"].get("arrival_before"):
                try:
                    cutoff = timestamp(exception["details"]["arrival_before"])
                except ValueError:
                    errors.append({"code": "exception_time", "target_id": did, "message": "例外抵达上限须为含时区的明确时间"})
            if hotel["latest_check_in"]:
                cutoff = min(cutoff, timestamp(hotel["latest_check_in"]))
            final_transport = maps["transports"].get(final_route["transport_id"])
            verified = (final_route["evidence"] == "verified" and sourced(final_route["source_ids"])
                        and not (final_transport and final_transport.get("rail_reference")))
            if not arrival or not verified:
                hard("hotel_arrival", did, "unknown", "返程耗时未知，不能断言早于酒店抵达上限")
            else:
                hard("hotel_arrival", did, "pass" if arrival < cutoff else "violation",
                     f"含缓冲预计抵达 {arrival.astimezone(zone).isoformat()}，必须早于 {cutoff.isoformat()}")
            if not final_route["buffers"]:
                hard("hotel_buffer", did, "unknown", "需列出停车、拥堵等适用缓冲及依据，不能只用理想耗时")

    ordered = sorted(trip["days"], key=lambda d: d["date"])
    for before, after in zip(ordered, ordered[1:]):
        if before["end_place_id"] != after["start_place_id"]:
            hard("cross_day", after["id"], "violation", "前一天终点与次日起点不一致，需展示跨日影响")
    if trip["status"] in DETAILED:
        if not trip["days"]:
            hard("itinerary", trip["trip_id"], "unknown", "详细计划尚无每日行程")
        if window:
            expected = set()
            current = date.fromisoformat(window["start"])
            end = date.fromisoformat(window["end"])
            while current <= end:
                expected.add(current.isoformat())
                current += timedelta(days=1)
            if window["flexible"]:
                hard("fixed_dates", trip["trip_id"], "unknown", "详细计划确认前须选择明确日期组合")
            if expected != seen_dates:
                hard("day_coverage", trip["trip_id"], "unknown", "每日行程须覆盖明确旅行日期，包括返程日")
        visited = {maps["activities"][aid]["place_id"] for aid in used_activities}
        for place in sorted(set(req["must_visit"]) - visited):
            hard("must_visit", place, "unknown", "必去地点尚未纳入行程")
        for transport in trip["transports"]:
            if active(trip, transport) and transport["mode"] == "rail":
                included = any(maps["routes"][rid]["transport_id"] == transport["id"] for rid in used_routes)
                hard("transport_included", transport["id"], "pass" if included else "unknown", "选中的固定交通必须纳入日程路线，不能只保留独立票务记录")
    result["budget"] = summarize(trip, as_of=as_of)
    if "budget_plan" in trip:
        from .allocation import fit_trip
        from .model import PlannerError
        try:
            result["budget"]["allocation"] = fit_trip(trip)
        except PlannerError as error:
            errors.append({"code": error.code, "message": str(error)})
    budget = result["budget"]
    for qid in budget["pending_quote_ids"]:
        result["pending"].append({"code": "quote", "target_id": qid, "message": "费用或适用条件未完整核实，未知金额不计为零"})
    if req["budget_minor"] is not None and budget["known_subtotal_minor"] is not None and budget["known_subtotal_minor"] > req["budget_minor"]:
        warn("over_budget", trip["trip_id"], "已知费用已超过预算；展示成本来源及备选，由用户选择")
    result["can_confirm"] = (not errors and trip["status"] in DETAILED
                             and all(c["result"] == "pass" for c in result["hard_constraints"]))
    return result
