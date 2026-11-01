"""Schema boundary, time utilities, and safe defaults (not a saved profile)."""

import copy
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from . import SCHEMA_VERSION

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((PACKAGE_ROOT / "schemas/model-v1.schema.json").read_text())
FORMATS = FormatChecker()
DEFAULTS = {
    "travelers": 2, "planned_drivers": 2, "hotel_room_type": "double",
    "hotel_rooms": 1, "hotel_budget_minor": [20000, 30000],
    "preferred_brand": "华住会", "walking_km": [5, 10],
    "transport_preferences": ["self_drive", "rail_rental", "rail"],
}
SENSITIVE_KEYS = {
    "password", "token", "access_token", "api_key", "secret", "id_card",
    "id_card_number", "passport_number", "driver_license_number", "payment_card",
    "health", "medical_history", "menstrual_cycle", "身份证号", "驾驶证号", "健康信息",
}


class PlannerError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_dict(self):
        return {"code": self.code, "message": self.message, **self.details}


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("t", "T").replace("Z", "+00:00").replace("z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return parsed


@FORMATS.checks("date-time", raises=(ValueError, TypeError))
def valid_datetime(value):
    if not isinstance(value, str):
        return True  # JSON Schema's type constraint reports non-strings.
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", value)
                and timestamp(value.replace("t", "T").replace("z", "Z")))


@FORMATS.checks("date", raises=(ValueError, TypeError))
def valid_date(value):
    return not isinstance(value, str) or bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) and date.fromisoformat(value))


@FORMATS.checks("uri", raises=(ValueError, TypeError))
def valid_uri(value):
    if not isinstance(value, str):
        return True
    parsed = urlsplit(value)
    return bool(parsed.scheme in ("https", "http") and parsed.hostname and not parsed.username
                and not parsed.password and not any(c.isspace() for c in value))


def load_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise PlannerError("identifier", "ID 仅允许 1–80 位字母、数字、连字符和下划线")
    return value


def schema_errors(document, entity="trip"):
    schema = {**SCHEMA, "$ref": f"#/$defs/{entity}"}
    errors = [
        {"code": "schema", "path": "/" + "/".join(map(str, error.absolute_path)),
         "message": error.message}
        for error in Draft202012Validator(schema, format_checker=FORMATS).iter_errors(document)
    ]
    if not isinstance(document, dict):
        return errors
    if entity in ("trip", "profile") and document.get("schema_version") != SCHEMA_VERSION:
        errors.insert(0, {"code": "schema_version", "message": "未知模型版本；只读保留原文件，须显式迁移，禁止自动丢弃或改写"})
    def inspect(value, path=""):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in SENSITIVE_KEYS:
                    errors.append({"code": "sensitive_field", "path": f"{path}/{key}",
                                   "message": "敏感字段不得进入普通旅行数据"})
                inspect(item, f"{path}/{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                inspect(item, f"{path}/{index}")
    inspect(document)
    values = document.get("values", {}) if entity == "profile" else {}
    if isinstance(values, dict):
        for field in ("hotel_budget_minor", "walking_km"):
            bounds = values.get(field)
            if isinstance(bounds, list) and len(bounds) == 2 and all(isinstance(v, (int, float)) for v in bounds) and bounds[0] > bounds[1]:
                errors.append({"code": "preference_range", "message": f"{field} 的下限大于上限"})
        if isinstance(values.get("planned_drivers"), int) and isinstance(values.get("travelers", 2), int) and values["planned_drivers"] > values.get("travelers", 2):
            errors.append({"code": "planned_drivers", "message": "计划驾驶人数不能大于旅行人数"})
    if entity == "profile":
        decisions = document.get("decisions", [])
        decision_ids = [d.get("id") for d in decisions if isinstance(d, dict)] if isinstance(decisions, list) else []
        if len(decision_ids) != len(set(decision_ids)):
            errors.append({"code": "duplicate_id", "message": "偏好确认记录 ID 不能重复"})
    if entity == "trip" and isinstance(document.get("timezone"), str):
        try:
            ZoneInfo(document["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            errors.append({"code": "timezone", "message": "无法识别的 IANA 时区"})
    return errors


def new_trip(trip_id, title, mock=False, profile=None):
    identifier(trip_id)
    stamp = now()
    snapshot = {"profile_id": None, "revision": None, "values": {}}
    if profile:
        snapshot = {key: copy.deepcopy(profile[key]) for key in snapshot}
    preferences = {**DEFAULTS, **snapshot["values"]}
    count = preferences["travelers"]
    driver_count = min(preferences["planned_drivers"], count)
    trip = {
        "schema_version": SCHEMA_VERSION, "trip_id": trip_id, "revision": 1,
        "title": title, "status": "draft", "timezone": "Asia/Shanghai",
        "data_mode": "mock" if mock else "real", "created_at": stamp, "updated_at": stamp,
        "preferences_snapshot": snapshot,
        "request": {
            "origin": None, "destinations": [], "date_window": None,
            "travelers": [{"id": f"traveler-{i}", "label": f"旅行者 {i}", "planned_driver": i <= driver_count}
                          for i in range(1, count + 1)],
            "budget_minor": None, "currency": "CNY", "transport_preferences": copy.deepcopy(preferences["transport_preferences"]),
            "interests": copy.deepcopy(preferences.get("interests", [])), "must_visit": [], "excluded_places": [], "overrides": {}, "constraints": [],
        },
        "selected_proposal_id": None, "cost_scope_reviewed": False,
    }
    for key in ("places", "proposals", "transports", "vehicles", "accommodations", "activities",
                "routes", "days", "quotes", "bookings", "expenses", "sources", "decisions", "cost_quote_ids", "notes"):
        trip[key] = []
    return trip


def effective_preferences(trip):
    return {**DEFAULTS, **trip["preferences_snapshot"]["values"], **trip["request"]["overrides"]}
