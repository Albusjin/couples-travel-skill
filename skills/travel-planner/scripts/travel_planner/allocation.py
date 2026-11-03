"""Budget allowances are separate from supplier quotes and payment facts."""

import copy
import hashlib

from .budget import quote_total
from .model import PlannerError, schema_errors

MAX_MONEY = 1_000_000_000_000
ITEM_FIELDS = ("id", "label", "quote_id", "amount_minor", "minimum_minor",
               "maximum_minor", "weight", "locked")


def allocate(total_minor, reserve_minor, items):
    """Integer weighted water filling, capped bounds, deterministic input-order ties.

    Keep this contract in sync with templates/web/budget.js; parity fixtures exercise
    both engines. No quote, order, expense or input item is mutated.
    """
    for value in (total_minor, reserve_minor):
        if value is not None and (type(value) is not int or not 0 <= value <= MAX_MONEY):
            raise PlannerError("budget_input", "预算金额须为非负整数分，且不超过支持范围")
    if reserve_minor is None:
        raise PlannerError("budget_input", "备用金额须明确，可填零")
    plan = {"reserve_minor": reserve_minor,
            "items": [{k: v for k, v in item.items() if k in ITEM_FIELDS} for item in items]}
    problems = schema_errors(plan, "budget_plan")
    if problems:
        raise PlannerError("budget_input", "预算分配输入无效", errors=problems)
    if len({i["id"] for i in items}) != len(items):
        raise PlannerError("budget_input", "预算项目 ID 不能重复")
    rows, unknown, fixed, minimum = [], [], 0, 0
    for item in items:
        low, high = item["minimum_minor"], item["maximum_minor"]
        if high is not None and high < low:
            raise PlannerError("budget_input", "项目上限不能小于下限", target_id=item["id"])
        value = item["amount_minor"] if item["locked"] else low
        if item["locked"]:
            if value is None:
                unknown.append(item["id"])
            else:
                fixed += value
        else:
            minimum += low
        rows.append({**copy.deepcopy(item), "allocated_minor": value})
    required = fixed + minimum + reserve_minor
    remaining = None if total_minor is None else max(0, total_minor - required)
    shortfall = None if total_minor is None else max(0, required - total_minor)
    if total_minor is not None and not shortfall and not unknown:
        eligible = [i for i, row in enumerate(rows) if not row["locked"]
                    and (row["maximum_minor"] is None or row["allocated_minor"] < row["maximum_minor"])]
        while remaining and eligible:
            weights = sum(rows[i]["weight"] for i in eligible)
            pool = remaining
            shares = {i: pool * rows[i]["weight"] // weights for i in eligible}
            residue = pool - sum(shares.values())
            order = sorted(eligible, key=lambda i: (-(pool * rows[i]["weight"] % weights), i))
            for i in order[:residue]:
                shares[i] += 1
            for i in eligible:
                cap = rows[i]["maximum_minor"]
                take = shares[i] if cap is None else min(shares[i], cap - rows[i]["allocated_minor"])
                rows[i]["allocated_minor"] += take
                remaining -= take
            eligible = [i for i in eligible if rows[i]["maximum_minor"] is None
                        or rows[i]["allocated_minor"] < rows[i]["maximum_minor"]]
    status = ("unknown_budget" if total_minor is None else "over_budget" if shortfall
              else "incomplete" if unknown else "allocated")
    return {"status": status, "total_minor": total_minor, "reserve_minor": reserve_minor,
            "fixed_minor": fixed, "minimum_required_minor": required,
            "shortfall_minor": shortfall, "unallocated_minor": remaining,
            "unknown_item_ids": unknown, "rows": rows,
            "fits_target": status == "allocated",
            "note": "仅为支出额度试算；不修改实际报价，不代表候选可订或全部费用已核实"}


def plan_document(plan):
    return {"reserve_minor": plan["reserve_minor"],
            "items": [{k: item[k] for k in ITEM_FIELDS} for item in plan["items"]
                      if not item.get("automatic")]}


def prepare_plan(trip, submitted=None):
    """Cover every selected cost and unmatched payment; recompute protected rows.

    Unknown fixed costs stay unknown. A payment matched to a selected quote is
    counted once, using at least its net paid consumption. Deposits stay separate.
    """
    plan = copy.deepcopy(submitted if submitted is not None else trip.get("budget_plan", {"reserve_minor": 0, "items": []}))
    problems = schema_errors(plan, "budget_plan")
    if problems:
        raise PlannerError("budget_input", "预算分配结构无效", errors=problems)
    selected = {q["id"]: q for q in trip["quotes"]
                if q["id"] in trip["cost_quote_ids"] and q["category"] != "deposit"}
    protected_targets = {item["id"] for group in ("activities", "accommodations", "vehicles", "transports")
                         for item in trip[group] if item["locked"] or item["completed"]}
    protected_targets.update(b["target_id"] for b in trip["bookings"]
                             if b["status"] in ("booked", "change_pending", "completed"))
    protected_quotes = {qid for group in ("activities", "accommodations", "vehicles", "transports")
                        for item in trip[group] if item["id"] in protected_targets for qid in item["quote_ids"]}
    paid, unmatched = {}, {}
    for expense in trip["expenses"]:
        if (expense["kind"] != "consumption" or expense["currency"] != trip["request"]["currency"]
                or expense["status"] not in ("paid", "refunded")):
            continue
        amount = expense["amount_minor"] * (-1 if expense["status"] == "refunded" else 1)
        qid = expense["quote_id"]
        if qid is None:
            matches = [q["id"] for q in selected.values() if q["target_id"] == expense["target_id"]]
            qid = matches[0] if len(matches) == 1 else None
        if qid in selected:
            paid[qid] = paid.get(qid, 0) + amount
            protected_quotes.add(qid)
        else:
            target = expense["target_id"]
            unmatched[target] = unmatched.get(target, 0) + amount
    rows, seen = [], set()
    for item in plan["items"]:
        qid = item["quote_id"]
        if qid is not None:
            if qid not in selected or qid in seen:
                raise PlannerError("budget_coverage", "预算报价必须属于当前费用清单且不能重复", target_id=qid)
            seen.add(qid)
        rows.append({**item, "protected": False, "automatic": False})
    for qid, quote in selected.items():
        if quote["currency"] != trip["request"]["currency"]:
            amount = None
        else:
            amount, complete = quote_total(quote)
            if not complete:
                amount = None
        net_paid = max(0, paid.get(qid, 0))
        if net_paid:
            amount = max(amount or 0, net_paid) if amount is not None else None
        protected = qid in protected_quotes or quote["target_id"] in protected_targets
        row = next((item for item in rows if item["quote_id"] == qid), None)
        if row is None:
            row = dict(id="allowance-" + hashlib.sha256(qid.encode()).hexdigest()[:24], label=quote["label"], quote_id=qid,
                       amount_minor=amount, minimum_minor=0, maximum_minor=None, weight=1,
                       locked=True, protected=protected, automatic=False)
            rows.append(row)
        elif protected and (not row["locked"] or row["amount_minor"] != amount):
            raise PlannerError("budget_protected", "已锁定、预订或支付项目不能通过预算试算改价或解锁", target_id=qid)
        row["protected"] = protected
    for target, amount in sorted(unmatched.items()):
        if amount > 0:
            rows.append(dict(id="paid-" + hashlib.sha256(target.encode()).hexdigest()[:24], label="未关联报价的已付消费：" + target,
                             quote_id=None, amount_minor=amount, minimum_minor=amount,
                             maximum_minor=amount, weight=1, locked=True, protected=True, automatic=True))
    # This also catches generated-ID collisions and invalid bounds.
    allocate(trip["request"]["budget_minor"], plan["reserve_minor"], rows)
    return {"reserve_minor": plan["reserve_minor"], "items": rows}


def fit_trip(trip, submitted=None, total_minor=None):
    plan = prepare_plan(trip, submitted)
    return allocate(trip["request"]["budget_minor"] if total_minor is None else total_minor,
                    plan["reserve_minor"], plan["items"])
