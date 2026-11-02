"""Integer money arithmetic; evidence and completeness never inferred from a sum."""

from .model import timestamp, now


def quote_state(quote, as_of=None, trip=None):
    state = quote["status"]
    if quote["conditions"] != quote["expected_conditions"]:
        return "expired"
    if trip is not None:
        window = trip["request"]["date_window"]
        expected = {"travelers": len(trip["request"]["travelers"])}
        if window:
            expected.update(trip_start=window["start"], trip_end=window["end"])
        else:
            return "expired"
        for hotel in trip["accommodations"]:
            if hotel["id"] == quote["target_id"]:
                expected.update(check_in=hotel["check_in"], check_out=hotel["check_out"],
                                rooms=hotel["rooms"], room_type=hotel["room_type"])
        for vehicle in trip["vehicles"]:
            if vehicle["id"] == quote["target_id"]:
                expected.update(pickup_at=vehicle["pickup_at"], dropoff_at=vehicle["dropoff_at"],
                                drivers=len(vehicle["driver_ids"]), transmission=vehicle["transmission"],
                                pickup_place_id=vehicle["pickup_place_id"], dropoff_place_id=vehicle["dropoff_place_id"])
        if any(quote["conditions"].get(key) != value for key, value in expected.items()):
            return "expired"
    if quote["valid_until"] and timestamp(quote["valid_until"]) <= timestamp(as_of or now()):
        return "expired"
    return state


def quote_total(quote):
    # Components are surcharges for the whole quantity, never per-unit implicitly.
    amount = quote["unit_amount_minor"]
    known = None if amount is None else amount * quote["quantity"]
    component_sum = sum(c["amount_minor"] for c in quote["components"] if c["amount_minor"] is not None)
    if known is not None or any(c["amount_minor"] is not None for c in quote["components"]):
        known = (known or 0) + component_sum
    complete = (amount is not None and quote["mandatory_fees_complete"]
                and all(c["amount_minor"] is not None for c in quote["components"] if c["mandatory"]))
    return known, complete


def summarize(trip, quote_ids=None, as_of=None, proposal=None):
    selected = set(trip["cost_quote_ids"] if quote_ids is None else quote_ids)
    quotes = {q["id"]: q for q in trip["quotes"]}
    sources = {s["id"]: s for s in trip["sources"]}
    currency = trip["request"]["currency"]
    known, verified, deposits, priced_count, deposit_count = 0, 0, 0, 0, 0
    missing, reference, rows = [], [], []
    for qid in sorted(selected):
        q = quotes.get(qid)
        if not q:
            missing.append(qid)
            continue
        amount, complete = quote_total(q)
        state = quote_state(q, as_of, trip)
        allowed_sources = {"official", "provider", "user"} | ({"mock"} if trip["data_mode"] == "mock" else set())
        reliable = bool(q["source_ids"]) and all(
            sid in sources and sources[sid]["reliable"]
            and sources[sid]["kind"] in allowed_sources
            for sid in q["source_ids"])
        current = state in ("queried", "rechecked") and reliable and q["queried_at"] is not None
        comparable = q["currency"] == currency
        if q["category"] == "deposit":
            if amount is not None and comparable:
                deposits += amount
                deposit_count += 1
            if amount is None or not complete or not current or not comparable:
                missing.append(qid)
        else:
            if amount is not None and comparable:
                known += amount
                priced_count += 1
            if complete and current and comparable:
                verified += amount
            else:
                missing.append(qid)
            if not current:
                reference.append(qid)
        rows.append({"quote_id": qid, "label": q["label"], "category": q["category"],
                     "currency": q["currency"], "known_amount_minor": amount,
                     "effective_status": state, "complete": complete,
                     "verified": current and complete and comparable, "unit": q["unit"],
                     "quantity": q["quantity"], "unit_amount_minor": q["unit_amount_minor"],
                     "components": q["components"]})
    # An empty cost list is not evidence that a journey is free.
    if not selected:
        missing.append("cost_scope_not_defined")
    if quote_ids is None or proposal is not None:
        proposal_id = proposal["id"] if proposal else trip["selected_proposal_id"]
        scoped = [item for group in ("transports", "vehicles", "accommodations", "activities")
                  for item in trip[group] if item.get("proposal_id") in (None, proposal_id)] + (trip["days"] if proposal is None else [])
        for item in scoped:
            missing.extend(qid for qid in item["quote_ids"] if qid not in selected)
        if not (proposal["cost_scope_reviewed"] if proposal else trip["cost_scope_reviewed"]):
            missing.append("cost_scope_not_reviewed")
        required = {"transport", "food", "contingency"}
        if any(item.get("proposal_id") in (None, proposal_id) for item in trip["accommodations"]):
            required.add("hotel")
        if any(item.get("proposal_id") in (None, proposal_id) for item in trip["activities"]):
            required.add("ticket")
        proposal = proposal or next((p for p in trip["proposals"] if p["id"] == proposal_id), None)
        if proposal and proposal["mode"] in ("self_drive", "rail_rental"):
            required.update(("toll", "parking"))
            if proposal["mode"] == "rail_rental":
                required.add("rental")
            vehicles = [v for v in trip["vehicles"] if v["proposal_id"] in (None, proposal_id)]
            required.add("charging" if vehicles and all(v["power"] == "electric" for v in vehicles) else "fuel")
        present = {quotes[qid]["category"] for qid in selected if qid in quotes}
        missing.extend("category:" + c for c in sorted(required - present))
    missing = sorted(set(missing))
    paid = sum(e["amount_minor"] for e in trip["expenses"]
               if e["currency"] == currency and e["status"] == "paid" and e["kind"] == "consumption")
    refunded = sum(e["amount_minor"] for e in trip["expenses"]
                   if e["currency"] == currency and e["status"] == "refunded" and e["kind"] == "consumption")
    count = len(trip["request"]["travelers"])
    subtotal = known if priced_count else None
    return {"currency": currency, "known_subtotal_minor": subtotal, "verified_subtotal_minor": verified,
            "per_person_minor": {"numerator": subtotal, "denominator": count},
            "complete_verified_total_minor": known if not missing else None,
            "deposit_hold_minor": deposits if deposit_count or not any(r["category"] == "deposit" for r in rows) else None,
            "paid_consumption_minor": paid,
            "refunded_consumption_minor": refunded, "pending_quote_ids": missing,
            "reference_quote_ids": reference, "rows": rows}


def difference(before, after):
    if before["currency"] != after["currency"] or any(b["known_subtotal_minor"] is None for b in (before, after)):
        return None
    return after["known_subtotal_minor"] - before["known_subtotal_minor"]
