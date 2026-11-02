"""Synthetic transport scenarios; no live queries, bookings or personal data."""

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/travel-planner"
sys.path.insert(0, str(SKILL / "scripts"))

from travel_planner.budget import quote_state, summarize
from travel_planner.capabilities import CapabilityRequest, ProvidedDataAdapter
from travel_planner.model import load_json
from travel_planner.render import views
from travel_planner.validation import validate


def demo():
    return load_json(SKILL / "examples/demo-trip.json")


def taxi_trip():
    trip = demo()
    transport = trip["transports"][0]
    transport.update(mode="taxi", taxi_details={"passengers": 2, "vehicle_count": 1,
                     "service_name": "虚构普通车型", "passenger_capacity": 4})
    trip["routes"][0]["mode"] = "taxi"
    trip["proposals"][0]["mode"] = "rail_taxi"
    quote = next(q for q in trip["quotes"] if q["id"] == transport["quote_ids"][0])
    quote.update(target_id=transport["id"], unit="trip", quantity=1, unit_amount_minor=4000, status="queried")
    quote["conditions"].update(passengers=2, vehicle_count=1, from_place_id=transport["from_place_id"],
                               to_place_id=transport["to_place_id"], depart_at=transport["depart_at"],
                               pricing_basis="current_estimate")
    quote["expected_conditions"] = copy.deepcopy(quote["conditions"])
    return trip, transport, quote


def reference_trip():
    trip = demo()
    transport = trip["transports"][0]
    transport["rail_reference"] = {"target_date": "2030-05-10", "reference_date": "2030-05-03",
                                   "reason": "schedule_unpublished"}
    quote = next(q for q in trip["quotes"] if q["id"] == transport["quote_ids"][0])
    quote["status"] = "queried"  # A mistaken label must not elevate the evidence.
    return trip, transport, quote


class TaxiTests(unittest.TestCase):
    def test_one_car_forty_yuan_is_total_forty_not_eighty(self):
        trip, _, quote = taxi_trip()
        self.assertEqual(validate(trip)["errors"], [])
        budget = summarize(trip, [quote["id"]])
        self.assertEqual(budget["known_subtotal_minor"], 4000)
        self.assertEqual(budget["per_person_minor"], {"numerator": 4000, "denominator": 2})
        self.assertEqual(budget["verified_subtotal_minor"], 0)
        self.assertIsNone(budget["complete_verified_total_minor"])
        self.assertEqual(budget["rows"][0]["effective_status"], "reference")

    def test_person_price_or_two_cars_cannot_be_saved_as_single_taxi_leg(self):
        for unit, quantity in (("person", 2), ("trip", 2)):
            trip, _, quote = taxi_trip()
            quote.update(unit=unit, quantity=quantity)
            self.assertIn("taxi_quantity", {e["code"] for e in validate(trip)["errors"]})

    def test_target_id_cannot_bypass_count_check_by_omitting_quote_ids(self):
        trip, transport, quote = taxi_trip()
        transport["quote_ids"] = []
        quote["quantity"] = 2
        self.assertIn("taxi_quantity", {e["code"] for e in validate(trip)["errors"]})

    def test_route_target_cannot_bypass_single_car_check(self):
        trip, transport, quote = taxi_trip()
        transport["quote_ids"] = []
        quote.update(target_id=trip["routes"][0]["id"], quantity=2)
        self.assertIn("taxi_quantity", {e["code"] for e in validate(trip)["errors"]})

    def test_conditions_are_invalidated_when_departure_or_destination_changes(self):
        for field, value in (("depart_at", "2030-05-10T10:00:00+08:00"), ("to_place_id", "place-home")):
            trip, transport, quote = taxi_trip()
            transport[field] = value
            self.assertEqual(quote_state(quote, trip=trip), "expired")

    def test_single_vehicle_passenger_count_and_capacity(self):
        trip, transport, _ = taxi_trip()
        transport["taxi_details"]["passengers"] = 1
        self.assertIn("taxi_passengers", {e["code"] for e in validate(trip)["errors"]})
        transport["taxi_details"].update(passengers=2, passenger_capacity=1)
        report = validate(trip)
        self.assertFalse(report["can_confirm"])
        self.assertIn("taxi_capacity", {c["code"] for c in report["hard_constraints"] if c["result"] == "violation"})
        transport["taxi_details"]["vehicle_count"] = 2
        self.assertTrue(validate(trip)["errors"])

    def test_unselected_taxi_capacity_does_not_block_selected_plan(self):
        trip, transport, _ = taxi_trip()
        transport.update(proposal_id="proposal-drive")
        transport["taxi_details"]["passenger_capacity"] = 1
        self.assertNotIn("taxi_capacity", {c["code"] for c in validate(trip)["hard_constraints"]})

    def test_legacy_taxi_route_is_preserved_with_missing_transport_warning(self):
        trip, _, _ = taxi_trip()
        trip["routes"][0]["transport_id"] = None
        self.assertIn("taxi_transport", {c["code"] for c in validate(trip)["warnings"]})

    def test_views_explain_single_car_and_non_binding_estimate(self):
        trip, _, _ = taxi_trip()
        output = views(trip)
        self.assertIn("2 人合乘 1 辆车", output["overview.md"])
        self.assertIn("2 人合乘 1 辆车", output["routes.md"])
        self.assertIn("trip × 1", output["budget.md"])
        self.assertIn("当前打车预估价", output["budget.md"])

    def test_taxi_capability_remains_unavailable_without_response(self):
        result = ProvidedDataAdapter().query(CapabilityRequest("taxi", {"passengers": 2, "vehicle_count": 1}))
        self.assertEqual(result.status, "unavailable")


class RailReferenceTests(unittest.TestCase):
    def test_reference_schedule_stays_draft_even_if_route_was_marked_verified(self):
        trip, transport, _ = reference_trip()
        report = validate(trip)
        self.assertEqual(report["errors"], [])
        self.assertFalse(report["can_confirm"])
        self.assertIn(("rail_schedule", transport["id"], "unknown"),
                      {(c["code"], c["target_id"], c["result"]) for c in report["hard_constraints"]})
        self.assertIn(("route_time", trip["routes"][0]["id"], "unknown"),
                      {(c["code"], c["target_id"], c["result"]) for c in report["hard_constraints"]})

    def test_reference_quote_does_not_count_as_verified_target_date_price(self):
        trip, _, quote = reference_trip()
        self.assertEqual(quote_state(quote, trip=trip), "reference")
        summary = summarize(trip, [quote["id"]])
        self.assertEqual(summary["known_subtotal_minor"], quote["unit_amount_minor"] * 2)
        self.assertEqual(summary["verified_subtotal_minor"], 0)
        self.assertIsNone(summary["complete_verified_total_minor"])

    def test_source_reference_dates_cannot_be_elevated_by_official_label(self):
        trip = demo()
        source = trip["sources"][0]
        source.update(kind="official", conditions={"target_date": "2030-05-10", "reference_date": "2030-05-03"})
        quote = trip["quotes"][0]
        quote["status"] = "queried"
        self.assertEqual(quote_state(quote, trip=trip), "reference")
        self.assertFalse(validate(trip)["can_confirm"])

    def test_reference_day_must_precede_actual_target_and_match_trip(self):
        for reference_date, target_date in (("2030-05-10", "2030-05-10"),
                                            ("2030-05-11", "2030-05-10"),
                                            ("2030-05-03", "2030-05-11"),
                                            ("2030-05-03", "2030-05-15")):
            trip, transport, _ = reference_trip()
            transport["rail_reference"].update(reference_date=reference_date, target_date=target_date)
            self.assertIn("rail_reference_dates", {e["code"] for e in validate(trip)["errors"]})

    def test_rechecking_target_removes_reference_block_only_with_new_evidence(self):
        trip, transport, quote = reference_trip()
        transport.pop("rail_reference")
        # Fixture stands in for fresh target-date evidence, never a real query.
        trip["sources"][0]["conditions"] = {"date": "2030-05-10", "scenario": "synthetic-recheck"}
        self.assertEqual(quote_state(quote, trip=trip), "queried")
        self.assertTrue(validate(trip)["can_confirm"])

    def test_reference_dates_and_limitations_visible_in_all_views(self):
        trip, _, _ = reference_trip()
        output = views(trip)
        for name in ("overview.md", "routes.md", "budget.md"):
            self.assertIn("参考日期 2030-05-03", output[name])
            self.assertIn("目标日期 2030-05-10", output[name])
            self.assertIn("参考日余票不适用于目标日", output[name])
        self.assertIn("参考（目标条件待核验）", output["routes.md"])

    def test_existing_documents_remain_valid_without_extension_fields(self):
        self.assertEqual(validate(demo())["errors"], [])
        self.assertTrue(validate(demo())["can_confirm"])


if __name__ == "__main__":
    unittest.main()
