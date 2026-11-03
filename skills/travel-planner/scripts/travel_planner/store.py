"""Immutable revisions and reviewed changes, with a single atomic HEAD commit point."""

import copy
import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .budget import difference, summarize
from .model import PlannerError, identifier, load_json, new_trip, now, schema_errors
from .validation import COLLECTIONS, LOCKABLE, active, validate

TRANSITIONS = {
    "draft": {"researching", "cancelled"},
    "researching": {"draft", "proposals_ready", "cancelled"},
    "proposals_ready": {"researching", "selected", "cancelled"},
    "selected": {"researching", "detailed", "cancelled"},
    "detailed": {"selected", "researching", "confirmed", "cancelled"},
    "confirmed": {"detailed", "in_progress", "cancelled"},
    "in_progress": {"detailed", "completed", "cancelled"},
    "completed": set(), "cancelled": {"draft", "researching"},
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def exclusive_json(path, value):
    """Revision/pending files are never overwritten, including after interrupted writes."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def diff(before, after):
    changed = []
    for key in before.keys() | after.keys():
        if key in ("revision", "updated_at"):
            continue
        if before.get(key) == after.get(key):
            continue
        if key in COLLECTIONS:
            old = {v["id"]: v for v in before.get(key, [])}
            new = {v["id"]: v for v in after.get(key, [])}
            for item_id in sorted(old.keys() | new.keys()):
                if old.get(item_id) != new.get(item_id):
                    changed.append({"collection": key, "id": item_id, "before": old.get(item_id), "after": new.get(item_id)})
        else:
            changed.append({"collection": key, "id": before.get("trip_id", before.get("profile_id")),
                            "before": before.get(key), "after": after.get(key)})
    return sorted(changed, key=lambda c: (c["collection"], c["id"]))


def references(value):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("_id") and isinstance(item, str):
                found.add(item)
            elif key.endswith("_ids") and isinstance(item, list):
                found.update(v for v in item if isinstance(v, str))
            found.update(references(item))
    elif isinstance(value, list):
        for item in value:
            found.update(references(item))
    return found


def change_impact(before, after, changes):
    changed = {c["id"] for c in changes}
    # Dependency closure across both old and new versions catches removed dependencies too.
    entities = [item for trip in (before, after) for group in COLLECTIONS for item in trip.get(group, [])]
    while True:
        extra = {item["id"] for item in entities if references(item) & changed}
        updated = changed | extra
        if updated == changed:
            break
        changed = updated
    days = {d["id"] for trip in (before, after) for d in trip["days"]
            if d["id"] in changed or references(d) & changed}
    return sorted(changed), sorted(days)


def normalize(trip):
    trip = copy.deepcopy(trip)
    booked = {b["target_id"] for b in trip["bookings"] if b["status"] in ("booked", "change_pending", "completed")}
    explicit = {target for decision in trip["decisions"] if decision["kind"] in ("selection", "plan_confirmation")
                for target in decision["target_ids"]}
    for group in LOCKABLE:
        for item in trip[group]:
            if item["id"] in booked | explicit or (trip["status"] == "confirmed" and active(trip, item)):
                item["locked"] = True
    return trip


class Store:
    def __init__(self, data_dir):
        if not data_dir:
            raise PlannerError("private_directory_required", "请先指定安装包与仓库外的私有持久目录；不默认使用临时云目录")
        self.root = Path(data_dir).expanduser().resolve()
        for parent in (self.root, *self.root.parents):
            # Managed sandboxes may mount an empty .git placeholder; it is not a repository.
            marker = parent / ".git"
            if marker.is_file() or (marker / "HEAD").exists():
                raise PlannerError("public_repository", "旅行数据目录不能位于 Git 仓库内")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, *parts):
        path = self.root.joinpath(*parts)
        if not path.resolve().is_relative_to(self.root):
            raise PlannerError("path_escape", "数据路径越界（包含符号链接）")
        return path

    @contextmanager
    def lock(self, namespace):
        lock = self.path(f".{identifier(namespace)}.lock")
        try:
            lock.mkdir(mode=0o700)
        except FileExistsError:
            raise PlannerError("write_locked", "另一个写入或未恢复的中断占用锁；核验无写入后手工移除锁目录") from None
        try:
            yield
        finally:
            lock.rmdir()

    def _entity_path(self, namespace, revision=None):
        root = self.path(namespace)
        if revision is None:
            head = load_json(self.path(namespace, "HEAD.json"))
            path = self.path(namespace, "revisions", head["file"])
            if not path.resolve().is_relative_to(root.resolve()):
                raise PlannerError("path_escape", "无效 HEAD 路径")
            bundle = load_json(path)
            if digest(bundle) != head["sha256"]:
                raise PlannerError("integrity", "当前版本校验失败；保留文件并从历史恢复")
            return bundle
        if not isinstance(revision, int) or revision < 1:
            raise PlannerError("revision", "修订号须为正整数")
        matches = list((root / "revisions").glob(f"{revision:08d}-*.json"))
        if len(matches) != 1:
            raise PlannerError("revision", "指定修订不存在或不唯一")
        if not matches[0].resolve().is_relative_to(root.resolve()):
            raise PlannerError("path_escape", "历史版本路径越界")
        return load_json(matches[0])

    def read(self, trip_id, revision=None):
        return self._entity_path("trip-" + identifier(trip_id), revision)["document"]

    def _publish(self, namespace, document, change):
        root = self.path(namespace)
        revisions = root / "revisions"
        # Orphan snapshots after HEAD failure are retained; next commit skips their numbers.
        maximum = max([int(p.name.split("-", 1)[0]) for p in revisions.glob("*.json")] or [0])
        document = copy.deepcopy(document)
        document["revision"] = maximum + 1
        document["updated_at"] = now()
        change = {**change, "new_revision": document["revision"]}
        bundle = {"document": document, "change": change}
        filename = f"{document['revision']:08d}-{uuid.uuid4().hex}.json"
        exclusive_json(self.path(namespace, "revisions", filename), bundle)
        atomic_json(self.path(namespace, "HEAD.json"), {"file": filename, "revision": document["revision"], "sha256": digest(bundle)})
        return document

    def init(self, trip_id, title, mock=False, profile_id=None):
        namespace = "trip-" + identifier(trip_id)
        with self.lock(namespace):
            if self.path(namespace, "HEAD.json").exists():
                raise PlannerError("exists", "旅行已存在，不可重新初始化覆盖")
            profile = self.profile_read(profile_id) if profile_id else None
            if profile:
                problems = schema_errors(profile, "profile")
                if problems:
                    raise PlannerError("validation", "长期档案模型无效或版本未知；不能用于创建旅行", errors=problems)
            document = new_trip(trip_id, title, mock, profile)
            return self._publish(namespace, document, {"kind": "initialize", "base_revision": None, "reason": "创建旅行"})

    def propose(self, trip_id, candidate, scope=None, reason="用户请求修改", restore_revision=None):
        before = self.read(trip_id)
        if not isinstance(candidate, dict):
            raise PlannerError("validation", "候选须为旅行对象")
        if candidate.get("revision") != before["revision"]:
            raise PlannerError("version_conflict", "候选基于旧版本；请读取最新版并重新生成")
        for key in ("trip_id", "created_at", "data_mode", "preferences_snapshot"):
            if candidate.get(key) != before[key]:
                raise PlannerError("identity", f"不能修改 {key}")
        candidate = normalize(candidate) if not schema_errors(candidate) else copy.deepcopy(candidate)
        report = validate(candidate)
        if report["errors"]:
            raise PlannerError("validation", "结构或引用校验失败，不保存候选", errors=report["errors"])
        if before["status"] != candidate["status"] and candidate["status"] not in TRANSITIONS[before["status"]]:
            # Historical content can be restored into a draft, never resurrect a final state silently.
            if restore_revision is None or candidate["status"] != "detailed" or before["status"] == "completed":
                raise PlannerError("transition", "不允许的旅行状态转换")
        if candidate["status"] in ("confirmed", "in_progress", "completed") and not report["can_confirm"]:
            raise PlannerError("hard_constraints", "硬约束须全部通过后才能确认或执行计划", report=report)
        changes = diff(before, candidate)
        if not changes:
            raise PlannerError("no_changes", "没有变更")
        required = []
        protected = {item["id"]: item for group in LOCKABLE for item in before[group]
                     if item["locked"] or item["completed"]}
        for c in changes:
            old = c["before"]
            if c["collection"] in LOCKABLE and old:
                if old["completed"]:
                    raise PlannerError("completed_immutable", "已完成活动或安排不得改写", target_id=c["id"])
                if old["locked"]:
                    required.append({"kind": "unlock", "target_id": c["id"]})
            if c["collection"] == "decisions" and old is not None:
                raise PlannerError("decision_history", "已有确认记录不得改写或删除")
            if c["collection"] == "bookings" and old and old["status"] in ("booked", "change_pending", "completed"):
                if not c["after"]:
                    raise PlannerError("booking_history", "预订事实不得删除")
                if c["after"] != old:
                    if c["after"]["status"] in ("not_booked", "booking_pending") or old["status"] == "completed":
                        raise PlannerError("booking_history", "不可抹去已预订或已完成的订单事实")
                    sid = c["after"]["confirmation_source_id"]
                    if not sid or sid == old["confirmation_source_id"]:
                        raise PlannerError("booking_confirmation", "更改外部预订事实须有新的可靠确认来源")
                    source = next(s for s in candidate["sources"] if s["id"] == sid)
                    if not source["reliable"] or source["kind"] not in ("user", "official", "provider"):
                        raise PlannerError("booking_confirmation", "订单变更须有用户或可信平台的新确认")
            if c["collection"] == "expenses" and old and old["status"] in ("paid", "refunded"):
                raise PlannerError("payment_history", "已支付及退款记录不可改写，使用新的更正记录")
            if c["collection"] in ("days", "routes"):
                protected_refs = (references(old) ^ references(c["after"])) & protected.keys()
                if c["collection"] == "routes":
                    protected_refs |= {r["transport_id"] for r in (old, c["after"]) if r and r["transport_id"] in protected}
                for target in protected_refs:
                    if protected[target]["completed"]:
                        raise PlannerError("completed_immutable", "不得从历史日程移除已完成安排或改写其交通段", target_id=target)
                    required.append({"kind": "unlock", "target_id": target})
        affected, affected_days = change_impact(before, candidate, changes)
        scope = set(scope or [d["id"] for d in before["days"]] + [d["id"] for d in candidate["days"]])
        unknown_scope = scope - {d["id"] for t in (before, candidate) for d in t["days"]}
        if unknown_scope:
            raise PlannerError("scope", "修改范围引用未知日期对象", target_ids=sorted(unknown_scope))
        for did in set(affected_days) - scope:
            required.append({"kind": "expand_scope", "target_id": did})
        if candidate["selected_proposal_id"] is not None and candidate["selected_proposal_id"] != before["selected_proposal_id"]:
            required.append({"kind": "selection", "target_id": candidate["selected_proposal_id"]})
        # Moving a day's endpoint affects the following day even if its JSON was not touched.
        days = sorted(before["days"], key=lambda d: d["date"])
        new_days = {d["id"]: d for d in candidate["days"]}
        for index, day in enumerate(days[:-1]):
            updated = new_days.get(day["id"])
            if updated and updated["end_place_id"] != day["end_place_id"]:
                next_day = days[index + 1]["id"]
                if next_day not in scope:
                    required.append({"kind": "expand_scope", "target_id": next_day})
        if candidate["status"] == "confirmed":
            required.append({"kind": "plan_confirmation", "target_id": trip_id})
            if report["budget"]["pending_quote_ids"]:
                required.append({"kind": "accept_unknown_prices", "target_id": trip_id})
        state_decision = {"cancelled": "cancel_plan", "in_progress": "start_trip", "completed": "complete_trip"}
        if candidate["status"] != before["status"] and candidate["status"] in state_decision:
            required.append({"kind": state_decision[candidate["status"]], "target_id": trip_id})
        change_id = "change-" + uuid.uuid4().hex
        old_budget, new_budget = summarize(before), report["budget"]
        change = {
            "change_id": change_id, "trip_id": trip_id, "base_revision": before["revision"],
            "base_hash": digest(before), "candidate_hash": digest(candidate), "candidate": candidate,
            "reason": reason, "created_at": now(), "scope_day_ids": sorted(scope),
            "affected_ids": affected, "affected_day_ids": affected_days, "changes": changes,
            "required_approvals": list({(r["kind"], r["target_id"]): r for r in required}.values()),
            "budget_delta_minor": difference(old_budget, new_budget),
            "budget_delta_is_complete": not (old_budget["pending_quote_ids"] or new_budget["pending_quote_ids"]),
            "restore_revision": restore_revision, "report": report,
        }
        exclusive_json(self.path("trip-" + trip_id, "pending", change_id + ".json"), change)
        return change

    def commit(self, trip_id, change_id, decisions=None):
        namespace = "trip-" + identifier(trip_id)
        identifier(change_id)
        with self.lock(namespace):
            change = load_json(self.path(namespace, "pending", change_id + ".json"))
            before = self.read(trip_id)
            if before["revision"] != change["base_revision"] or digest(before) != change["base_hash"]:
                raise PlannerError("version_conflict", "当前版本已改变，请重新生成候选及影响报告")
            candidate = copy.deepcopy(change["candidate"])
            if digest(candidate) != change["candidate_hash"]:
                raise PlannerError("candidate_integrity", "候选内容校验失败，请重新生成")
            decisions = decisions or []
            if not isinstance(decisions, list):
                raise PlannerError("decision", "确认记录须为 JSON 数组")
            for decision in decisions:
                problem = schema_errors(decision, "decision")
                if problem or decision["change_id"] != change_id:
                    raise PlannerError("decision", "确认须符合 Decision 结构并绑定当前 change_id", errors=problem)
            for required in change["required_approvals"]:
                if not any(d["kind"] == required["kind"] and required["target_id"] in d["target_ids"] for d in decisions):
                    raise PlannerError("approval_required", "缺少具体变更的明确确认", required_approval=required)
            candidate["decisions"].extend(copy.deepcopy(decisions))
            candidate = normalize(candidate)
            # Do not trust cached validation: time-sensitive quote validity may have changed.
            report = validate(candidate)
            if report["errors"]:
                raise PlannerError("validation", "候选校验失败", errors=report["errors"])
            if candidate["status"] in ("confirmed", "in_progress", "completed"):
                if not report["can_confirm"]:
                    raise PlannerError("hard_constraints", "当前硬约束不允许确认", report=report)
                if report["budget"]["pending_quote_ids"] and candidate["status"] == "confirmed":
                    if not any(d["kind"] == "accept_unknown_prices" and trip_id in d["target_ids"] for d in decisions):
                        raise PlannerError("approval_required", "报价状态已变化，需确认当前待核实费用", report=report)
            return self._publish(namespace, candidate, {k: v for k, v in change.items() if k not in ("candidate", "report")})

    def restore(self, trip_id, revision, scope=None):
        current = self.read(trip_id)
        historical = copy.deepcopy(self.read(trip_id, revision))
        # Preserve order/payment/decision facts accumulated since the historical revision.
        for key in ("bookings", "expenses", "decisions"):
            historical[key] = copy.deepcopy(current[key])
        for source in current["sources"]:
            if source["id"] not in {s["id"] for s in historical["sources"]}:
                historical["sources"].append(copy.deepcopy(source))
        historical["revision"] = current["revision"]
        historical["status"] = "detailed" if historical["days"] else "draft"
        return self.propose(trip_id, historical, scope, f"恢复修订 {revision} 的规划内容，保留当前订单及支付事实", revision)

    def compare(self, trip_id, old_revision, new_revision=None):
        before, after = self.read(trip_id, old_revision), self.read(trip_id, new_revision)
        old, new = summarize(before), summarize(after)
        return {"base_revision": before["revision"], "new_revision": after["revision"],
                "changes": diff(before, after),
                "budget_delta_minor": difference(old, new),
                "budget_delta_is_complete": not (old["pending_quote_ids"] or new["pending_quote_ids"])}

    def profile_read(self, profile_id):
        return self._entity_path("profile-" + identifier(profile_id))["document"]

    def profile_propose(self, profile_id, values, expected_revision=0):
        namespace = "profile-" + identifier(profile_id)
        head = self.path(namespace, "HEAD.json")
        before = self.profile_read(profile_id) if head.exists() else None
        if (before["revision"] if before else 0) != expected_revision:
            raise PlannerError("version_conflict", "长期偏好版本已变化")
        if not isinstance(values, dict):
            raise PlannerError("profile_values", "偏好必须为对象")
        old = before["values"] if before else {}
        items = [{"key": key, "old": old.get(key), "new": values.get(key), "removed": key not in values}
                 for key in sorted(old.keys() | values.keys()) if old.get(key) != values.get(key) or (key in old) != (key in values)]
        if not items:
            raise PlannerError("no_changes", "长期偏好没有变更")
        change_id = "profile-change-" + uuid.uuid4().hex
        change = {"change_id": change_id, "profile_id": profile_id, "base_revision": expected_revision,
                  "before_hash": digest(before), "values": values, "items": items,
                  "candidate_hash": digest(values),
                  "impact": "这些规则会影响后续新建旅行；既有旅行的偏好快照保持不变"}
        candidate = {"schema_version": "1.0", "profile_id": profile_id, "revision": expected_revision + 1,
                     "updated_at": now(), "values": values, "decisions": []}
        problems = schema_errors(candidate, "profile")
        if problems:
            raise PlannerError("validation", "偏好校验失败", errors=problems)
        exclusive_json(self.path(namespace, "pending", change_id + ".json"), change)
        return change

    def profile_commit(self, profile_id, change_id, decisions):
        namespace = "profile-" + identifier(profile_id)
        identifier(change_id)
        if not isinstance(decisions, list):
            raise PlannerError("decision", "偏好确认记录须为数组")
        for decision in decisions:
            problems = schema_errors(decision, "decision")
            if problems:
                raise PlannerError("decision", "偏好确认记录无效", errors=problems)
        with self.lock(namespace):
            change = load_json(self.path(namespace, "pending", change_id + ".json"))
            before = self.profile_read(profile_id) if self.path(namespace, "HEAD.json").exists() else None
            if digest(change["values"]) != change["candidate_hash"]:
                raise PlannerError("candidate_integrity", "长期偏好候选校验失败；重新展示差异并确认")
            if digest(before) != change["before_hash"]:
                raise PlannerError("version_conflict", "长期偏好已变化，请重新展示逐项差异")
            for item in change["items"]:
                if not any(d.get("kind") == "profile_update" and d.get("change_id") == change_id
                           and item["key"] in d.get("target_ids", []) and d.get("details", {}).get("items", {}).get(item["key"]) == item
                           for d in decisions):
                    raise PlannerError("approval_required", "每项长期偏好须确认新旧值和影响", key=item["key"])
            profile = {"schema_version": "1.0", "profile_id": profile_id, "revision": change["base_revision"] + 1,
                       "updated_at": now(), "values": change["values"],
                       "decisions": (before["decisions"] if before else []) + decisions}
            problems = schema_errors(profile, "profile")
            if problems:
                raise PlannerError("validation", "偏好确认记录无效", errors=problems)
            return self._publish(namespace, profile, {k: v for k, v in change.items() if k != "values"})
