"""Synthetic coverage for budget drafts, scenic timelines and gated websites."""

import copy
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_core import SKILL, approvals, demo, populate
from travel_planner.allocation import allocate, fit_trip, plan_document, prepare_plan
from travel_planner.model import PlannerError, now
from travel_planner.render import output_status, render, views
from travel_planner.store import Store, digest
from travel_planner.validation import validate
from travel_planner.web import import_budget_draft, map_configuration, map_data


def item(identifier="flex", amount=None, locked=False, low=0, high=None, weight=1):
    return dict(id=identifier, label=identifier, quote_id=None, amount_minor=amount,
                locked=locked, minimum_minor=low, maximum_minor=high, weight=weight)


def draft_for(trip, plan=None):
    return dict(format="travel-budget-draft/1", trip_id=trip["trip_id"], base_revision=trip["revision"],
                base_hash=digest(trip), currency=trip["request"]["currency"],
                total_minor=trip["request"]["budget_minor"],
                plan=plan_document(prepare_plan(trip)) if plan is None else plan)


class AllocationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node 不在 PATH；跨引擎测试需 Node，Python 预算功能不依赖它")
    def test_browser_engine_matches_python(self):
        rng=random.Random(7);cases=[]
        for n in range(60):
            rows=[]
            for i in range(rng.randint(1,6)):
                low=rng.randint(0,500);high=None if rng.randrange(2) else low+rng.randint(0,2000)
                rows.append(item("i"+str(i),amount=rng.randint(0,1000) if rng.randrange(5) else None,
                                 low=low,high=high,weight=rng.randint(1,1000),locked=bool(rng.randrange(2))))
            total=None if n%13==0 else rng.randint(0,10000);reserve=rng.randint(0,500)
            cases.append(dict(total=total,reserve=reserve,items=rows,expected=allocate(total,reserve,rows)))
        script="""const fs=require('node:fs'),vm=require('node:vm');
          const context=vm.createContext({});vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
          const cases=JSON.parse(fs.readFileSync(0,'utf8'));
          const failures=cases.map((c,i)=>JSON.stringify(context.TravelBudget.allocate(c.total,c.reserve,c.items))===JSON.stringify(c.expected)?null:i).filter(i=>i!==null);
          console.log(JSON.stringify(failures));process.exit(failures.length?1:0);"""
        result=subprocess.run([shutil.which("node"),"-e",script,str(SKILL/"templates/web/budget.js")],
                              input=json.dumps(cases),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_fixed_and_reserve_then_weighted_remainder(self):
        rows = [item("tickets", 260000, True), item("hotel", low=90000, weight=2), item("food", low=50000)]
        before = copy.deepcopy(rows)
        result = allocate(600000, 40000, rows)
        self.assertTrue(result["fits_target"])
        self.assertEqual(sum(r["allocated_minor"] for r in result["rows"]) + 40000, 600000)
        self.assertEqual(result["rows"][0]["allocated_minor"], 260000)
        self.assertEqual(rows, before)

    def test_increase_fixed_cost_reduces_flexible_pool(self):
        rows = [item("tickets", 10000, True), item("food", low=1000), item("fun", low=1000)]
        first = allocate(50000, 5000, rows)
        rows[0]["amount_minor"] += 3000
        second = allocate(50000, 5000, rows)
        self.assertEqual(sum(r["allocated_minor"] for r in first["rows"][1:]) - sum(r["allocated_minor"] for r in second["rows"][1:]), 3000)

    def test_caps_redistribute_and_leave_unspent(self):
        result = allocate(100, 0, [item("a", high=10, weight=100), item("b", high=20)])
        self.assertEqual([r["allocated_minor"] for r in result["rows"]], [10, 20])
        self.assertEqual(result["unallocated_minor"], 70)

    def test_unknown_fixed_is_not_free(self):
        result = allocate(100, 0, [item("unknown", None, True), item("flex")])
        self.assertEqual(result["status"], "incomplete")
        self.assertFalse(result["fits_target"])
        self.assertIsNone(result["rows"][0]["allocated_minor"])

    def test_shortfall_no_negative_allowances(self):
        result = allocate(100, 10, [item("fixed", 100, True), item("flex", low=20)])
        self.assertEqual(result["shortfall_minor"], 30)
        self.assertTrue(all(r["allocated_minor"] >= 0 for r in result["rows"]))

    def test_integer_remainder_is_stable(self):
        result = allocate(2, 0, [item("a"), item("b"), item("c")])
        self.assertEqual([r["allocated_minor"] for r in result["rows"]], [1, 1, 0])

    def test_missing_budget_remains_unknown(self):
        self.assertEqual(allocate(None, 0, [item()])["status"], "unknown_budget")

    def test_invalid_inputs_and_duplicate_ids(self):
        for total, rows in ((True, [item()]), (-1, [item()]), (100, [item(low=3, high=2)]),
                            (100, [item(), item()]), (100, [item(weight=0)])):
            with self.subTest(total=total, rows=rows), self.assertRaises(PlannerError):
                allocate(total, 0, rows)

    def test_conservation_across_many_bounds(self):
        for total in range(0, 100):
            result = allocate(total, 0, [item("a", high=13, weight=3), item("b", high=9), item("c", weight=2)])
            self.assertEqual(sum(r["allocated_minor"] for r in result["rows"]) + result["unallocated_minor"], total)
            self.assertLessEqual(result["rows"][0]["allocated_minor"], 13)

    def test_quote_coverage_and_unknown_fees(self):
        trip = demo()
        plan = prepare_plan(trip, {"reserve_minor": 0, "items": []})
        self.assertEqual({r["quote_id"] for r in plan["items"]}, {q["id"] for q in trip["quotes"] if q["id"] in trip["cost_quote_ids"] and q["category"] != "deposit"})
        trip["quotes"][0]["mandatory_fees_complete"] = False
        self.assertEqual(fit_trip(trip)["status"], "incomplete")

    def test_matched_payment_not_double_counted(self):
        trip = demo(); before = fit_trip(trip)["fixed_minor"]
        q = trip["quotes"][0]
        trip["expenses"] = [dict(id="payment", target_id=q["target_id"], quote_id=q["id"], amount_minor=100,
                                 currency="CNY", status="paid", paid_at=now(), kind="consumption", note="模拟")]
        self.assertEqual(fit_trip(trip)["fixed_minor"], before)
        row = next(r for r in prepare_plan(trip)["items"] if r["quote_id"] == q["id"])
        self.assertTrue(row["protected"])

    def test_unmatched_payment_is_added_once_and_not_exported_twice(self):
        trip=demo(); before=fit_trip(trip)["fixed_minor"]
        trip["expenses"]=[dict(id="payment",target_id=trip["trip_id"],quote_id=None,amount_minor=500,
                               currency="CNY",status="paid",paid_at=now(),kind="consumption",note="模拟")]
        plan=prepare_plan(trip)
        self.assertEqual(fit_trip(trip)["fixed_minor"],before+500)
        self.assertEqual(fit_trip(trip, plan_document(plan))["fixed_minor"],before+500)


class ScenicTests(unittest.TestCase):
    def scenic(self):
        trip=demo(); day=trip["days"][0]; route=trip["routes"][0]
        for place in trip["places"]:
            place["parent_place_id"]="place-scenic"
        trip["places"].append(dict(id="place-scenic",name="虚构景区",provider_id=None,latitude=None,longitude=None))
        # Group the first day's existing chain, preserving all real time constraints.
        trip["scenic_visits"]=[dict(id="scenic-test",day_id=day["id"],scenic_place_id="place-scenic",
            entry_place_id=route["from_place_id"],exit_place_id=trip["routes"][1]["to_place_id"],
            activity_ids=day["activity_ids"],route_ids=day["route_ids"],effort="moderate",notes=[],alternatives=["缩短停留"],source_ids=["source-mock"])]
        return trip

    def test_old_data_and_flat_scenic_group_validate(self):
        self.assertEqual(validate(demo())["errors"],[])
        self.assertTrue(validate(self.scenic())["can_confirm"])

    def test_route_not_in_day_rejected(self):
        trip=self.scenic();trip["scenic_visits"][0]["route_ids"]=[trip["routes"][2]["id"]]
        self.assertIn("scenic_day",{e["code"] for e in validate(trip)["errors"]})

    def test_reversed_route_chain_fails(self):
        trip=self.scenic();trip["scenic_visits"][0]["route_ids"].reverse()
        self.assertTrue(any(c["code"]=="scenic_chain" and c["result"]=="violation" for c in validate(trip)["hard_constraints"]))

    def test_scenic_transport_needs_operating_evidence(self):
        trip=self.scenic();r=trip["routes"][0];r["mode"]="cable_car"
        self.assertTrue(any(c["code"]=="scenic_operation" and c["result"]=="unknown" for c in validate(trip)["hard_constraints"]))
        r["operating_window"]={"first_departure_at":r["depart_at"],"last_departure_at":r["depart_at"],"source_ids":["source-mock"]}
        self.assertEqual(validate(trip)["errors"],[])
        self.assertTrue(any(c["code"]=="scenic_operation" and c["result"]=="pass" for c in validate(trip)["hard_constraints"]))
        r["operating_window"]["last_departure_at"]="2030-05-10T00:00:00+08:00"
        self.assertFalse(validate(trip)["can_confirm"])

    def test_parent_cycles_rejected(self):
        trip=demo();trip["places"][0]["parent_place_id"]=trip["places"][0]["id"]
        self.assertIn("place_cycle",{e["code"] for e in validate(trip)["errors"]})

    def test_missing_group_does_not_bypass_special_transport_hours(self):
        trip=demo();trip["routes"][0]["mode"]="shuttle"
        self.assertTrue(any(c["code"]=="scenic_operation" and c["result"]=="unknown"
                            for c in validate(trip)["hard_constraints"]))

    def test_internal_nodes_must_belong_to_scenic_place(self):
        trip=self.scenic();trip["places"][0].pop("parent_place_id")
        self.assertTrue(any(c["code"]=="scenic_membership" and c["result"]=="unknown"
                            for c in validate(trip)["hard_constraints"]))

    def test_scenic_detail_is_available_without_a_website(self):
        trip=self.scenic();output=views(trip)
        self.assertIn("虚构景区 · 景区内部路线",output["overview.md"])
        self.assertIn("缩短停留",output["routes.md"])

    def test_unknown_coordinates_not_guessed_and_actual_paths_need_sources(self):
        trip=demo();mapping=map_data(trip)
        self.assertTrue(all(value is None for value in mapping["points"].values()))
        r=trip["routes"][0]
        r["geometry"]={"kind":"actual","coordinate_system":"gcj02","coordinates":[[110,29],[111,30]],"source_ids":[]}
        self.assertIn("geometry_source",{e["code"] for e in validate(trip)["errors"]})

    def test_unreliable_or_wrong_path_degrades_to_schematic(self):
        trip=demo();r=trip["routes"][0]
        for p in trip["places"]:
            p.update(coordinate_system="gcj02",longitude=110,latitude=29)
        r["geometry"]={"kind":"actual","coordinate_system":"gcj02","coordinates":[[120,39],[121,40]],"source_ids":["source-mock"]}
        self.assertEqual(map_data(trip)["routes"][0]["kind"],"schematic")
        r["geometry"]["coordinates"]=[[110,29],[110,29]]
        self.assertEqual(map_data(trip)["routes"][0]["kind"],"actual")


class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.trip=populate(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def confirm(self):
        self.trip["status"]="confirmed";change=self.store.propose("demo",self.trip)
        self.trip=self.store.commit("demo",change["change_id"],approvals(change))
        return self.trip

    def test_website_not_generated_by_default_and_draft_is_blocked(self):
        out=render(self.store,"demo")
        self.assertFalse(any(f.endswith("index.html") for f in out["files"]))
        with self.assertRaises(PlannerError) as error:
            render(self.store,"demo",website=True,theme="guide")
        self.assertEqual(error.exception.code,"website_confirmation_required")

    def test_style_is_required_and_default_md_still_works(self):
        self.confirm()
        with self.assertRaises(PlannerError) as error:
            render(self.store,"demo",website=True)
        self.assertEqual(error.exception.code,"website_style_required")
        self.assertEqual(len(render(self.store,"demo")["files"]),3)

    def test_website_same_revision_and_detects_corruption(self):
        self.confirm();out=render(self.store,"demo",website=True,theme="guide")
        status=output_status(self.store,"demo")
        self.assertTrue(status["website_current"]);self.assertFalse(status["website"]["map_configured"])
        directory=Path(out["directory"])
        html=(directory/"index.html").read_text()
        payload=json.loads(html.split('<script id="travel-data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(payload["revision"],self.trip["revision"])
        self.assertEqual(payload["base_hash"],digest(self.trip))
        self.assertNotIn("decisions",payload);self.assertNotIn("expenses",payload)
        (directory/"app.js").write_text("tampered")
        self.assertFalse(output_status(self.store,"demo")["outputs_current"])

    def test_hostile_text_cannot_close_payload_script(self):
        self.trip["title"]='</script><script>alert("x")</script>'
        self.confirm();out=render(self.store,"demo",website=True,theme="journal")
        html=(Path(out["directory"])/"index.html").read_text()
        self.assertNotIn(self.trip["title"],html)
        self.assertIn("\\u003c/script>",html)

    def test_map_config_refuses_secrets_and_unsafe_urls(self):
        for config in ({"api_key":"secret"},{"amap_key":"a"*32,"service_host":"http://example.com"},
                       {"amap_key":"a"*32,"service_host":"https://a:b@example.com"},
                       {"amap_key":"a"*32,"service_host":"https://example.com","securityJsCode":"secret"}):
            with self.subTest(config=config),self.assertRaises(PlannerError):map_configuration(config)
        self.assertEqual(map_configuration({"amap_key":"a"*32,"service_host":"https://example.com/_AMapService"})["amap_key"],"a"*32)

    def test_draft_import_only_proposes_and_preserves_quote_payment_facts(self):
        trip=self.confirm();before=copy.deepcopy(trip);draft=draft_for(trip);draft["total_minor"]+=10000
        draft["plan"]["items"].append(item("flexible-extras",low=1000))
        result=import_budget_draft(self.store,"demo",draft)
        self.assertEqual(self.store.read("demo"),before)
        candidate=result["change"]["candidate"]
        self.assertEqual(candidate["status"],"detailed")
        self.assertEqual(candidate["quotes"],before["quotes"])
        self.assertEqual(candidate["expenses"],before["expenses"])
        self.assertTrue(result["allocation"]["fits_target"])
        saved=self.store.commit("demo",result["change"]["change_id"],approvals(result["change"]))
        self.assertGreater(saved["revision"],before["revision"])
        with self.assertRaises(PlannerError):render(self.store,"demo",website=True,theme="guide")

    def test_stale_or_wrong_currency_draft_rejected(self):
        trip=self.confirm()
        for key,value in (("base_revision",1),("base_hash","wrong"),("currency","USD"),("trip_id","other")):
            draft=draft_for(trip);draft[key]=value
            with self.subTest(key=key),self.assertRaises(PlannerError):import_budget_draft(self.store,"demo",draft)

    def test_protected_budget_cannot_be_unlocked_or_repriced(self):
        trip=self.confirm()
        for field in ("locked","amount_minor"):
            draft=draft_for(trip)
            row=next(r for r in draft["plan"]["items"] if next(q for q in trip["quotes"] if q["id"]==r["quote_id"])["category"]=="hotel")
            row[field]=False if field=="locked" else 1
            with self.subTest(field=field),self.assertRaises(PlannerError) as error:
                import_budget_draft(self.store,"demo",draft)
            self.assertEqual(error.exception.code,"budget_protected")

    def test_budget_cli_is_read_only(self):
        result=subprocess.run([sys.executable,str(SKILL/"scripts/travel.py"),"budget-fit","--input",str(SKILL/"examples/demo-trip.json")],text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("allocation",json.loads(result.stdout)["result"])

    def test_budget_allowances_are_visible_in_markdown(self):
        trip=demo();trip["budget_plan"]=plan_document(prepare_plan(trip))
        trip["budget_plan"]["items"].append(item("flex-extra",low=1000))
        text=views(trip)["budget.md"]
        self.assertIn("支出额度试算",text)
        self.assertIn("不修改实际报价",text)
        self.assertIn("flex-extra",text)


if __name__ == "__main__":
    unittest.main()
