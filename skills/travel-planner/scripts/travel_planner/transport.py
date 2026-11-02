"""Shared transport evidence and per-vehicle pricing semantics. No network I/O."""


def reference_source(source):
    conditions = source["conditions"]
    return (source["kind"] == "reference" or bool(
        conditions.get("reference_date") and conditions.get("target_date")
        and conditions["reference_date"] != conditions["target_date"]))


def quote_transports(trip, quote):
    route_transport_ids = {r["transport_id"] for r in trip["routes"] if r["id"] == quote["target_id"]}
    return [item for item in trip["transports"]
            if item["id"] == quote["target_id"] or quote["id"] in item["quote_ids"] or item["id"] in route_transport_ids]


def taxi_label(trip, transport):
    details = transport.get("taxi_details", {})
    return f"{details.get('passengers', len(trip['request']['travelers']))} 人合乘 1 辆车（单程整车价，不乘人数）"


def rail_reference_label(transport):
    reference = transport.get("rail_reference")
    if not reference:
        return ""
    return (f"目标日期 {reference['target_date']}；参考日期 {reference['reference_date']}；"
            "参考班次/时刻/票价，目标日期待复核，参考日余票不适用于目标日")
