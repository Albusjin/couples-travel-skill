#!/usr/bin/env python3
"""Run the entire synthetic lifecycle; confirmations here are test fixtures only."""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from travel_planner.model import load_json, now
from travel_planner.render import render
from travel_planner.store import Store


def confirm_fixture(change):
    return [dict(id=f"mock-approval-{index}-{change['change_id'][-8:]}", kind=r["kind"], target_ids=[r["target_id"]],
                 summary="仅模拟：虚构用户确认影响清单", confirmed_by="虚构测试用户", confirmed_at=now(),
                 change_id=change["change_id"], details={}) for index, r in enumerate(change["required_approvals"])]


def run(data_dir):
    store = Store(data_dir)
    initial = store.init("demo", "虚构三日旅行（仅测试）", mock=True)
    revisions = [initial["revision"]]
    fixture = load_json(Path(__file__).with_name("demo-trip.json"))
    for state in ("researching", "proposals_ready", "selected", "detailed", "confirmed"):
        candidate = copy.deepcopy(fixture) if state == "researching" else copy.deepcopy(initial)
        candidate.update(revision=initial["revision"], created_at=initial["created_at"], status=state,
                         selected_proposal_id="proposal-rail" if state in ("selected", "detailed", "confirmed") else None)
        change = store.propose("demo", candidate, reason="模拟工作流")
        initial = store.commit("demo", change["change_id"], confirm_fixture(change))
        revisions.append(initial["revision"])
    confirmed_revision = initial["revision"]
    initial["status"] = "detailed"
    initial["activities"][1]["notes"].append("仅修改第二天：增加市集自由活动提示")
    change = store.propose("demo", initial, ["day-2"], "模拟局部修改")
    revised = store.commit("demo", change["change_id"], confirm_fixture(change))
    output = render(store, "demo")
    return {"data_mode": "mock", "revisions": revisions + [revised["revision"]],
            "comparison": store.compare("demo", confirmed_revision), "outputs": output,
            "note": "仅模拟；不能证明真实查询或真实用户确认。再次运行请选择新目录。"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="仅存放虚构数据的仓库外临时目录")
    args = parser.parse_args()
    print(json.dumps(run(args.data_dir), ensure_ascii=False, indent=2))
