"""Synthetic-only contract, invariant, and failure-injection tests."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/travel-planner"
sys.path.insert(0, str(SKILL / "scripts"))

from travel_planner.budget import quote_state, summarize
from travel_planner.capabilities import CapabilityRequest, ProvidedDataAdapter
from travel_planner.model import PlannerError, load_json, new_trip, now
from travel_planner.render import output_status, render, views
from travel_planner.store import Store
from travel_planner.validation import validate


def demo():
    return load_json(SKILL / "examples/demo-trip.json")


def approvals(change):
    return [dict(id=f"approval-{index}-{change['change_id'][-8:]}", kind=item["kind"],
                 target_ids=[item["target_id"]], summary="虚构测试用户确认了具体影响清单",
                 confirmed_by="虚构测试用户", confirmed_at=now(), change_id=change["change_id"], details={})
            for index, item in enumerate(change["required_approvals"])]


def populate(store):
    document = store.init("demo", "虚构三日旅行（仅测试）", mock=True)
    for status in ("researching", "proposals_ready", "selected", "detailed"):
        candidate = demo() if status == "researching" else copy.deepcopy(document)
        candidate.update(revision=document["revision"], created_at=document["created_at"], status=status,
                         selected_proposal_id="proposal-rail" if status in ("selected", "detailed") else None)
        change = store.propose("demo", candidate, reason="虚构验收")
        document = store.commit("demo", change["change_id"], approvals(change))
    return document


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.trip = demo()

    def constraint(self, code, target="day-1"):
        return next(c["result"] for c in validate(self.trip)["hard_constraints"]
                    if c["code"] == code and c["target_id"] == target)

    def test_demo_is_explicit_mock_and_valid(self):
        report = validate(self.trip)
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["can_confirm"])
        self.assertEqual(report["data_mode"], "mock")

    def test_missing_origin_and_dates_are_unknown(self):
        self.trip["request"].update(origin=None, date_window=None)
        report = validate(self.trip)
        self.assertFalse(report["can_confirm"])
        self.assertEqual({c["code"] for c in report["hard_constraints"] if c["result"] == "unknown"} & {"origin", "dates"}, {"origin", "dates"})

    def test_flexible_dates_cannot_be_finally_confirmed(self):
        self.trip["request"]["date_window"]["flexible"] = True
        self.assertFalse(validate(self.trip)["can_confirm"])

    def test_hotel_arrival_exclusive_boundary_and_buffer(self):
        route = self.trip["routes"][1]
        route["depart_at"] = "2030-05-10T21:00:00+08:00"
        for duration, expected in ((44, "pass"), (45, "violation"), (75, "violation")):
            with self.subTest(duration=duration):
                route["duration_minutes"] = duration
                self.assertEqual(self.constraint("hotel_arrival"), expected)

    def test_unknown_or_unverified_duration_does_not_pass(self):
        for field, value in (("duration_minutes", None), ("evidence", "estimated"), ("source_ids", [])):
            with self.subTest(field=field):
                self.trip = demo()
                self.trip["routes"][1][field] = value
                self.assertEqual(self.constraint("hotel_arrival"), "unknown")

    def test_no_buffer_is_unknown(self):
        self.trip["routes"][1]["buffers"] = []
        self.assertEqual(self.constraint("hotel_buffer"), "unknown")

    def test_no_hotel_day_requires_scoped_decision(self):
        self.trip["days"][2]["hotel_exception_decision_id"] = None
        self.assertEqual(self.constraint("hotel_arrival", "day-3"), "unknown")
        self.trip = demo()
        self.trip["decisions"][0]["details"]["date"] = "2030-05-11"
        self.assertTrue(validate(self.trip)["errors"])

    def test_explicit_overnight_exception(self):
        self.trip["routes"][1]["depart_at"] = "2030-05-10T23:30:00+08:00"
        self.assertEqual(self.constraint("overnight", "route-1-back"), "violation")
        decision = copy.deepcopy(self.trip["decisions"][0])
        decision.update(id="exception-night", target_ids=["day-1"], details={"date": "2030-05-10", "arrival_before": "2030-05-11T01:00:00+08:00"})
        self.trip["decisions"].append(decision)
        self.trip["days"][0]["hotel_exception_decision_id"] = decision["id"]
        self.assertEqual(self.constraint("hotel_arrival"), "pass")

    def test_mock_sources_cannot_verify_real_plan(self):
        self.trip["data_mode"] = "real"
        self.assertFalse(validate(self.trip)["can_confirm"])

    def test_timezone_and_unzoned_datetime(self):
        self.trip["routes"][0]["depart_at"] = "2030-05-10t01:00:00z"
        self.assertEqual(validate(self.trip)["errors"], [])
        self.trip["timezone"] = "not-a-timezone"
        self.assertTrue(validate(self.trip)["errors"])
        self.trip = demo()
        self.trip["routes"][0]["depart_at"] = "2030-05-10T09:00:00"
        self.assertTrue(validate(self.trip)["errors"])

    def test_wrong_day_and_overlap(self):
        self.trip["activities"][0]["start_at"] = "2030-05-10T10:00:00+08:00"
        self.assertEqual(self.constraint("overlap", "activity-1"), "violation")
        self.trip["routes"][0]["depart_at"] = "2030-05-11T09:00:00+08:00"
        self.assertTrue(validate(self.trip)["errors"])

    def test_closed_and_reservation_failed(self):
        for status in ("closed", "reservation_failed", "unknown"):
            self.trip["activities"][0]["access"] = status
            self.assertEqual(self.constraint("activity_access", "activity-1"), "unknown" if status == "unknown" else "violation")

    def test_missing_reference_duplicate_and_quote_double_count(self):
        self.trip["routes"][0]["to_place_id"] = "missing"
        self.assertTrue(validate(self.trip)["errors"])
        self.trip = demo()
        self.trip["cost_quote_ids"].append(self.trip["cost_quote_ids"][0])
        self.assertTrue(validate(self.trip)["errors"])
        self.trip = demo()
        self.trip["request"]["travelers"][1]["id"] = self.trip["request"]["travelers"][0]["id"]
        self.assertTrue(validate(self.trip)["errors"])

    def test_invalid_root_and_dependency_cycle_are_reported(self):
        self.assertTrue(validate([])["errors"])
        self.trip["routes"][0]["depends_on_ids"] = ["route-1-back"]
        self.trip["routes"][1]["depends_on_ids"] = ["route-1-out"]
        self.assertIn("dependency_cycle", {e["code"] for e in validate(self.trip)["errors"]})

    def test_schema_version_and_sensitive_keys(self):
        self.trip["schema_version"] = "99"
        self.assertEqual(validate(self.trip)["errors"][0]["code"], "schema_version")
        self.trip = demo()
        self.trip["request"]["overrides"]["health"] = "synthetic-prohibited-field"
        self.assertIn("sensitive_field", {e["code"] for e in validate(self.trip)["errors"]})

    def test_booking_requires_evidence_and_lock(self):
        self.trip["bookings"] = [dict(id="booking-hotel", target_id="hotel-stay", status="booked", confirmation_source_id=None, cancellation_terms="模拟", note="模拟")]
        self.assertTrue(validate(self.trip)["errors"])
        self.trip["accommodations"][0]["locked"] = True
        self.assertEqual(self.constraint("booking_evidence", "booking-hotel"), "unknown")

    def test_walking_hotel_budget_are_soft(self):
        self.trip["days"][0]["walking_km"] = 15
        self.trip["quotes"][1]["unit_amount_minor"] = 40000
        report = validate(self.trip)
        self.assertTrue(report["can_confirm"])
        self.assertTrue({"walking", "hotel_budget"} <= {w["code"] for w in report["warnings"]})

    def test_default_room_and_trip_override(self):
        self.trip["accommodations"][0]["room_type"] = "twin"
        self.assertEqual(self.constraint("room_type", "hotel-stay"), "violation")
        self.trip["request"]["overrides"]["hotel_room_type"] = "twin"
        self.assertEqual(self.constraint("room_type", "hotel-stay"), "pass")

    def test_unknown_hotel_policies_cannot_be_confirmed(self):
        self.trip["accommodations"][0]["policies_verified"] = False
        self.assertEqual(self.constraint("hotel_policies", "hotel-stay"), "unknown")


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.trip = demo()

    def test_room_nights_and_per_person(self):
        result = summarize(self.trip)
        self.assertEqual(result["known_subtotal_minor"], 140000)
        self.assertEqual(result["deposit_hold_minor"], 50000)
        self.assertEqual(result["per_person_minor"], {"numerator": 140000, "denominator": 2})
        self.assertIsNone(result["complete_verified_total_minor"])
        self.trip["quotes"][1]["quantity"] = 4
        self.assertIn("room_nights", {e["code"] for e in validate(self.trip)["errors"]})

    def test_unknown_is_not_zero_and_fees_must_be_complete(self):
        for q in self.trip["quotes"]:
            q["status"] = "queried"
        self.assertEqual(summarize(self.trip)["complete_verified_total_minor"], 140000)
        self.trip["quotes"][1]["unit_amount_minor"] = None
        result = summarize(self.trip)
        self.assertEqual(result["known_subtotal_minor"], 90000)
        self.assertIsNone(result["complete_verified_total_minor"])
        self.trip["quotes"][0]["components"] = [dict(label="强制服务费", amount_minor=None, mandatory=True)]
        self.assertIn("quote-rail", summarize(self.trip)["pending_quote_ids"])

    def test_quote_conditions_expiry_and_scope_coverage(self):
        q = self.trip["quotes"][0]
        q["status"] = "rechecked"
        self.assertEqual(quote_state(q, trip=self.trip), "rechecked")
        q["conditions"]["travelers"] = 1
        self.assertEqual(quote_state(q, trip=self.trip), "expired")
        q["conditions"]["travelers"] = 2
        q["valid_until"] = "2020-01-01T00:00:00Z"
        self.assertEqual(quote_state(q), "expired")
        self.trip["cost_quote_ids"].remove("quote-food")
        self.assertIn("category:food", summarize(self.trip)["pending_quote_ids"])

    def test_trip_date_change_expires_quotes_even_if_claimed_conditions_match(self):
        for q in self.trip["quotes"]:
            q["status"] = "queried"
        self.trip["request"]["date_window"]["end"] = "2030-05-13"
        self.assertEqual(summarize(self.trip)["verified_subtotal_minor"], 0)

    def test_entirely_unknown_budget_is_not_zero(self):
        for q in self.trip["quotes"]:
            q["unit_amount_minor"] = None
        self.assertIsNone(summarize(self.trip)["known_subtotal_minor"])
        self.assertIsNone(summarize(self.trip, [])["known_subtotal_minor"])
        self.assertIsNone(summarize(self.trip)["deposit_hold_minor"])

    def test_candidate_partial_costs_cannot_be_claimed_complete(self):
        proposal = self.trip["proposals"][0]
        proposal["quote_ids"] = ["quote-hotel"]
        self.trip["quotes"][1]["status"] = "queried"
        result = summarize(self.trip, proposal["quote_ids"], proposal=proposal)
        self.assertIsNone(result["complete_verified_total_minor"])
        self.assertIn("category:food", result["pending_quote_ids"])

    def test_mixed_currency_and_paid_deposit(self):
        self.trip["quotes"][0]["currency"] = "USD"
        self.trip["expenses"] = [dict(id="expense-deposit", target_id="hotel-stay", quote_id="quote-deposit", amount_minor=50000, currency="CNY", status="paid", paid_at=now(), kind="deposit", note="模拟")]
        result = summarize(self.trip)
        self.assertIn("quote-rail", result["pending_quote_ids"])
        self.assertEqual(result["known_subtotal_minor"], 100000)
        self.assertEqual(result["paid_consumption_minor"], 0)


class RentalAndEnergyTests(unittest.TestCase):
    def setUp(self):
        self.trip = demo()
        self.vehicle = dict(id="vehicle-test", proposal_id="proposal-rail", locked=False, completed=False,
                            **{"class": "模拟紧凑型"}, transmission="automatic", power="fuel", recommended=True,
                            driver_ids=["traveler-1", "traveler-2"], driver_rules_verified=True,
                            pickup_place_id="place-hotel", dropoff_place_id="place-hotel",
                            pickup_at="2030-05-10T12:00:00+08:00", dropoff_at="2030-05-12T12:00:00+08:00",
                            one_way_verified=False, same_group_only=True, range_km=None,
                            departure_energy_percent=None, reserve_percent=None, energy_stops=[],
                            quote_ids=[], source_ids=["source-mock"], notes=["模拟测试"])
        self.trip["vehicles"] = [self.vehicle]

    def state(self, code, target="vehicle-test"):
        report = validate(self.trip)
        self.assertEqual(report["errors"], [])
        return next(c["result"] for c in report["hard_constraints"] if c["code"] == code and c["target_id"] == target)

    def test_automatic_and_both_registered_drivers(self):
        self.assertEqual(self.state("automatic"), "pass")
        self.vehicle["transmission"] = "manual"
        self.assertEqual(self.state("automatic"), "violation")
        self.vehicle["transmission"] = "unknown"
        self.assertEqual(self.state("automatic"), "unknown")
        self.vehicle["driver_ids"].pop()
        self.assertEqual(self.state("drivers"), "unknown")

    def test_one_way_and_rental_period(self):
        self.vehicle["dropoff_place_id"] = "place-home"
        self.assertEqual(self.state("one_way"), "unknown")
        self.vehicle["one_way_verified"] = True
        self.assertEqual(self.state("one_way"), "pass")
        self.vehicle["dropoff_at"] = self.vehicle["pickup_at"]
        self.assertEqual(self.state("rental_period"), "violation")

    def test_electric_range_and_reserve(self):
        self.vehicle.update(power="electric", range_km=1000, departure_energy_percent=90, reserve_percent=20)
        self.trip["transports"] = []
        for day in self.trip["days"]:
            day["driving_minutes"] = 0
            for route in self.trip["routes"]:
                if route["id"] in day["route_ids"]:
                    route["mode"] = "drive"
                    route["transport_id"] = None
                    day["driving_minutes"] += route["duration_minutes"]
        self.assertEqual(self.state("energy_route"), "pass")
        self.vehicle["range_km"] = 100
        self.assertEqual(self.state("energy_route"), "violation")
        self.vehicle["range_km"] = None
        self.assertEqual(self.state("energy_inputs"), "unknown")

    def test_incomplete_charger_has_fallback_pending(self):
        self.vehicle.update(power="electric", range_km=1000, departure_energy_percent=90, reserve_percent=20)
        self.vehicle["energy_stops"] = [dict(place_id="place-market", compatible="unknown", availability="unknown", arrival_percent=30, departure_percent=None, backup_place_id=None, source_ids=[])]
        self.assertEqual(self.state("energy_stop", "place-market"), "unknown")


class InstallationTests(unittest.TestCase):
    def test_installed_copy_runs_independently_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "installed-skill"
            command = [sys.executable, str(SKILL / "scripts/install.py"), "--destination", str(destination)]
            copied = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(copied.returncode, 0, copied.stdout + copied.stderr)
            validated = subprocess.run([sys.executable, str(destination / "scripts/travel.py"), "validate", "--input", str(destination / "examples/demo-trip.json")], cwd=folder, text=True, capture_output=True)
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
            self.assertTrue(json.loads(validated.stdout)["result"]["can_confirm"])
            duplicate = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(duplicate.returncode, 2)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.document = populate(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def commit_candidate(self, document, scope=None):
        change = self.store.propose("demo", document, scope=scope)
        return self.store.commit("demo", change["change_id"], approvals(change))

    def test_output_hashes_survive_windows_text_newline_translation(self):
        self.document["status"] = "confirmed"
        change = self.store.propose("demo", self.document)
        self.store.commit("demo", change["change_id"], approvals(change))
        original_open = Path.open

        def windows_text_open(path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
            # Reproduce Windows text-mode writes on every CI host, rather than
            # relying on the developer's OS to expose byte/hash mismatches.
            if "w" in mode and "b" not in mode and newline is None:
                newline = "\r\n"
            return original_open(path, mode, buffering, encoding, errors, newline)

        for website in (False, True):
            with self.subTest(website=website), patch.object(Path, "open", windows_text_open):
                output = render(self.store, "demo", website=website, theme="guide" if website else None)
                status = output_status(self.store, "demo")
                self.assertTrue(status["outputs_current"])
                self.assertEqual(status["website_current"], website)
                for filename in output["files"]:
                    self.assertNotIn(b"\r\n", Path(filename).read_bytes())

    def test_full_cycle_and_versioned_outputs(self):
        self.document["status"] = "confirmed"
        change = self.store.propose("demo", self.document)
        with self.assertRaises(PlannerError) as ctx:
            self.store.commit("demo", change["change_id"])
        self.assertEqual(ctx.exception.code, "approval_required")
        confirmed = self.store.commit("demo", change["change_id"], approvals(change))
        self.assertTrue(all(a["locked"] for a in confirmed["activities"]))
        output = render(self.store, "demo")
        self.assertTrue(output_status(self.store, "demo")["outputs_current"])
        for file in output["files"]:
            text = Path(file).read_text()
            self.assertIn(f"修订 {confirmed['revision']}", text)
            self.assertIn("模拟", text)
            self.assertIn("未核实事项", text)
        edited = copy.deepcopy(confirmed)
        edited["status"] = "detailed"
        edited["activities"][1]["notes"].append("局部变更")
        change = self.store.propose("demo", edited, ["day-2"])
        self.assertIn({"kind": "unlock", "target_id": "activity-2"}, change["required_approvals"])
        revised = self.store.commit("demo", change["change_id"], approvals(change))
        self.assertEqual(confirmed["days"][0], revised["days"][0])
        self.assertEqual(confirmed["days"][2], revised["days"][2])
        self.assertFalse(output_status(self.store, "demo")["outputs_current"])
        self.assertTrue(all(Path(f).exists() for f in output["files"]))

    def test_unknown_hard_constraint_can_save_draft_but_not_confirm(self):
        self.document["routes"][1]["duration_minutes"] = None
        saved = self.commit_candidate(self.document)
        saved["status"] = "confirmed"
        with self.assertRaises(PlannerError) as ctx:
            self.store.propose("demo", saved)
        self.assertEqual(ctx.exception.code, "hard_constraints")

    def test_cross_day_scope_approval_for_shared_dependency(self):
        self.document["accommodations"][0]["comfort_notes"].append("共同住宿安排改变")
        change = self.store.propose("demo", self.document, ["day-2"])
        self.assertIn({"kind": "expand_scope", "target_id": "day-1"}, change["required_approvals"])
        self.assertIn("day-1", change["affected_day_ids"])

    def test_locked_booked_return_is_preserved(self):
        self.document["bookings"] = [dict(id="booking-rail", target_id="transport-rail", status="booked", confirmation_source_id="source-mock", cancellation_terms="模拟不可退", note="测试")]
        saved = self.commit_candidate(self.document)
        self.assertTrue(saved["transports"][0]["locked"])
        revised = copy.deepcopy(saved)
        revised["transports"][0]["depart_at"] = "2030-05-10T07:00:00+08:00"
        revised["transports"][0]["door_to_door_minutes"] = 300
        change = self.store.propose("demo", revised)
        self.assertIn({"kind": "unlock", "target_id": "transport-rail"}, change["required_approvals"])
        revised = copy.deepcopy(saved)
        revised["bookings"][0]["status"] = "cancelled"
        with self.assertRaises(PlannerError) as ctx:
            self.store.propose("demo", revised)
        self.assertEqual(ctx.exception.code, "booking_confirmation")

    def test_removing_locked_activity_from_day_requires_confirmation(self):
        self.document["activities"][1]["locked"] = True
        saved = self.commit_candidate(self.document)
        saved["days"][1]["activity_ids"] = []
        change = self.store.propose("demo", saved, ["day-2"])
        self.assertIn({"kind": "unlock", "target_id": "activity-2"}, change["required_approvals"])

    def test_linked_route_cannot_bypass_booked_transport_lock(self):
        self.document["bookings"] = [dict(id="booking-rail", target_id="transport-rail", status="booked", confirmation_source_id="source-mock", cancellation_terms="模拟", note="模拟")]
        saved = self.commit_candidate(self.document)
        saved["routes"][0]["depart_at"] = "2030-05-10T08:00:00+08:00"
        change = self.store.propose("demo", saved, ["day-1"])
        self.assertIn({"kind": "unlock", "target_id": "transport-rail"}, change["required_approvals"])
        self.assertFalse(change["report"]["can_confirm"])

    def test_completed_history_and_paid_records_are_immutable(self):
        self.document["activities"][0]["completed"] = True
        self.document["expenses"] = [dict(id="expense-1", target_id="hotel-stay", quote_id="quote-hotel", amount_minor=50000, currency="CNY", status="paid", paid_at=now(), kind="consumption", note="模拟")]
        saved = self.commit_candidate(self.document)
        edited = copy.deepcopy(saved)
        edited["activities"][0]["label"] = "重写过去"
        with self.assertRaises(PlannerError) as ctx:
            self.store.propose("demo", edited)
        self.assertEqual(ctx.exception.code, "completed_immutable")
        edited = copy.deepcopy(saved)
        edited["expenses"][0]["amount_minor"] = 1
        with self.assertRaises(PlannerError) as ctx:
            self.store.propose("demo", edited)
        self.assertEqual(ctx.exception.code, "payment_history")

    def test_concurrent_candidate_conflict(self):
        first = copy.deepcopy(self.document)
        first["notes"].append("第一候选")
        second = copy.deepcopy(self.document)
        second["notes"].append("第二候选")
        a = self.store.propose("demo", first)
        b = self.store.propose("demo", second)
        self.store.commit("demo", a["change_id"], approvals(a))
        with self.assertRaises(PlannerError) as ctx:
            self.store.commit("demo", b["change_id"], approvals(b))
        self.assertEqual(ctx.exception.code, "version_conflict")

    def test_head_failure_preserves_current_and_orphan(self):
        before = self.store.read("demo")
        self.document["notes"].append("写入失败测试")
        change = self.store.propose("demo", self.document)
        with patch("travel_planner.store.atomic_json", side_effect=OSError("simulated HEAD failure")):
            with self.assertRaises(OSError):
                self.store.commit("demo", change["change_id"], approvals(change))
        self.assertEqual(before, self.store.read("demo"))
        self.assertFalse(self.store.path(".trip-demo.lock").exists())
        saved = self.store.commit("demo", change["change_id"], approvals(change))
        self.assertEqual(saved["revision"], before["revision"] + 2)

    def test_render_failure_leaves_head_and_old_outputs(self):
        old = render(self.store, "demo")
        self.document["notes"].append("新版")
        saved = self.commit_candidate(self.document)
        with patch("travel_planner.render.os.rename", side_effect=OSError("simulated output publish failure")):
            with self.assertRaises(OSError):
                render(self.store, "demo")
        self.assertEqual(self.store.read("demo")["revision"], saved["revision"])
        self.assertFalse(output_status(self.store, "demo")["outputs_current"])
        self.assertTrue(all(Path(f).exists() for f in old["files"]))
        self.assertEqual(list(self.store.path("trip-demo", "outputs").glob(".render-*")), [])

    def test_rerender_refreshes_expired_evidence_without_overwriting_files(self):
        self.document["quotes"][0].update(status="queried", valid_until="2025-01-01T00:00:00Z")
        self.commit_candidate(self.document)
        with patch("travel_planner.render.now", return_value="2024-01-01T00:00:00Z"):
            first = render(self.store, "demo")
        self.assertFalse(output_status(self.store, "demo")["outputs_current"])
        refreshed = render(self.store, "demo")
        self.assertNotEqual(first["directory"], refreshed["directory"])
        self.assertTrue(output_status(self.store, "demo")["outputs_current"])
        self.assertTrue(all(Path(f).exists() for f in first["files"]))

    def test_restore_creates_revision_and_retains_confirmation_history(self):
        original = copy.deepcopy(self.document)
        self.document["notes"].append("后续修订")
        changed = self.commit_candidate(self.document)
        restoration = self.store.restore("demo", original["revision"])
        saved = self.store.commit("demo", restoration["change_id"], approvals(restoration))
        self.assertGreater(saved["revision"], changed["revision"])
        self.assertEqual(saved["notes"], original["notes"])
        self.assertEqual(self.store.read("demo", original["revision"]), original)
        self.assertTrue(self.store.compare("demo", changed["revision"])["changes"])

    def test_unrelated_trip_overrides_do_not_change_profile(self):
        profile = self.create_profile({"preferred_brand": "示例品牌"})
        new = self.store.init("other", "另一个虚构旅行", mock=True, profile_id="couple")
        self.assertEqual(new["preferences_snapshot"]["revision"], profile["revision"])
        new["request"]["overrides"]["vehicle_class"] = "SUV"
        change = self.store.propose("other", new)
        self.store.commit("other", change["change_id"])
        self.assertEqual(self.store.profile_read("couple"), profile)

    def create_profile(self, values):
        change = self.store.profile_propose("couple", values)
        with self.assertRaises(PlannerError):
            self.store.profile_commit("couple", change["change_id"], [])
        decisions = [dict(id="profile-approval", kind="profile_update", target_ids=list(values),
                          summary="虚构测试用户逐项确认新旧值及长期影响", confirmed_by="虚构测试用户",
                          confirmed_at=now(), change_id=change["change_id"], details={"items": {item["key"]: item for item in change["items"]}})]
        return self.store.profile_commit("couple", change["change_id"], decisions)

    def test_profile_requires_exact_per_item_confirmation(self):
        profile = self.create_profile({"vehicle_class": "compact", "preferred_brand": "示例"})
        self.assertEqual(profile["revision"], 1)
        with self.assertRaises(PlannerError):
            self.store.profile_propose("couple", {"vehicle_class": "SUV"}, expected_revision=0)

    def test_confirmed_profile_applies_to_new_trip_and_soft_rules(self):
        self.create_profile({"travelers": 3, "planned_drivers": 1, "hotel_budget_minor": [30000, 50000], "walking_km": [1, 3]})
        trip = self.store.init("profile-demo", "虚构偏好测试", mock=True, profile_id="couple")
        self.assertEqual(len(trip["request"]["travelers"]), 3)
        self.assertEqual(sum(t["planned_driver"] for t in trip["request"]["travelers"]), 1)
        sample = demo()
        sample["preferences_snapshot"]["values"] = {"walking_km": [1, 3], "hotel_budget_minor": [30000, 50000]}
        sample["quotes"][1]["unit_amount_minor"] = 40000
        warnings = validate(sample)["warnings"]
        self.assertNotIn("hotel_budget", {w["code"] for w in warnings})
        self.assertIn("walking", {w["code"] for w in warnings})

    def test_repository_and_missing_root_and_symlink_are_rejected(self):
        for root in (None, str(ROOT / "private")):
            with self.assertRaises(PlannerError):
                Store(root)
        with tempfile.TemporaryDirectory() as outside:
            self.store.path("escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(PlannerError):
                self.store.path("escape", "anything.json")

    def test_lock_prevents_concurrent_writes(self):
        self.document["notes"].append("新值")
        change = self.store.propose("demo", self.document)
        with self.store.lock("trip-demo"):
            with self.assertRaises(PlannerError) as ctx:
                self.store.commit("demo", change["change_id"], approvals(change))
        self.assertEqual(ctx.exception.code, "write_locked")

    def test_tampered_candidate_fails_integrity(self):
        self.document["notes"].append("新值")
        change = self.store.propose("demo", self.document)
        path = self.store.path("trip-demo", "pending", change["change_id"] + ".json")
        modified = load_json(path)
        modified["candidate"]["title"] = "候选被改变"
        path.write_text(json.dumps(modified))
        with self.assertRaises(PlannerError) as ctx:
            self.store.commit("demo", change["change_id"], approvals(change))
        self.assertEqual(ctx.exception.code, "candidate_integrity")


class CapabilityAndCliTests(unittest.TestCase):
    def test_unavailable_mismatched_and_mock_data(self):
        request = CapabilityRequest("hotels", {"date": "2030-05-10"})
        self.assertEqual(ProvidedDataAdapter().query(request).status, "unavailable")
        response = {"records": [{}], "sources": [{}], "conditions": {"date": "2030-05-11"}}
        self.assertEqual(ProvidedDataAdapter(response).query(request).status, "unavailable")
        response["conditions"] = request.conditions
        result = ProvidedDataAdapter(response, True).query(request)
        self.assertEqual(result.data_mode, "mock")
        self.assertIn("模拟", result.limitations[0])

    def test_cli_validate_without_storage_and_init_requires_root(self):
        command = [sys.executable, str(SKILL / "scripts/travel.py")]
        validated = subprocess.run(command + ["validate", "--input", str(SKILL / "examples/demo-trip.json")], text=True, capture_output=True)
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
        self.assertTrue(json.loads(validated.stdout)["result"]["can_confirm"])
        import os
        environment = {k: v for k, v in os.environ.items() if k != "TRAVEL_PLANNER_DATA_DIR"}
        missing = subprocess.run(command + ["init", "demo", "--title", "虚构"], text=True, capture_output=True, env=environment)
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout)["error"]["code"], "private_directory_required")


if __name__ == "__main__":
    unittest.main()
