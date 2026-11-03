#!/usr/bin/env python3
"""Machine-readable local CLI. The Skill, not this CLI, interprets natural language."""

import argparse
import json
import sys
from dataclasses import asdict

from travel_runtime import RuntimeConfigError
from travel_runtime.config import load_settings

try:
    from travel_planner.capabilities import CAPABILITIES, CapabilityRequest, ProvidedDataAdapter
    from travel_planner.model import PlannerError, load_json
    from travel_planner.render import output_status, render
    from travel_planner.store import Store
    from travel_planner.validation import validate
except ModuleNotFoundError as error:
    print(json.dumps({"ok": False, "error": {"code": "dependency", "message": "需要 Python 3.11+ 及 requirements.txt 中的依赖", "module": error.name}}, ensure_ascii=False))
    sys.exit(2)


def parser():
    root = argparse.ArgumentParser(description="Travel Planner V1 本地结构化数据工具")
    root.add_argument("--runtime-config", help="可选本机运行配置 TOML")
    root.add_argument("--data-dir", help="用户指定的仓库外私有目录；优先于运行配置")
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("trip_id")
    init.add_argument("--title", required=True)
    init.add_argument("--mock", action="store_true")
    init.add_argument("--profile-id")
    read = sub.add_parser("read")
    read.add_argument("trip_id")
    read.add_argument("--revision", type=int)
    check = sub.add_parser("validate")
    check.add_argument("--input", required=True)
    propose = sub.add_parser("propose")
    propose.add_argument("trip_id")
    propose.add_argument("--input", required=True, help="以当前 revision 为基线的完整候选 JSON")
    propose.add_argument("--scope", nargs="*", help="本次允许修改的 day ID，非日期字符串")
    propose.add_argument("--reason", required=True)
    commit = sub.add_parser("commit")
    commit.add_argument("trip_id")
    commit.add_argument("change_id")
    commit.add_argument("--decisions", help="用户确认记录的 JSON 数组")
    commit.add_argument("--no-render", action="store_true", help="仅提交数据，输出明确标为待生成")
    compare = sub.add_parser("compare")
    compare.add_argument("trip_id")
    compare.add_argument("old_revision", type=int)
    compare.add_argument("--new-revision", type=int)
    restore = sub.add_parser("restore")
    restore.add_argument("trip_id")
    restore.add_argument("revision", type=int)
    restore.add_argument("--scope", nargs="*")
    for command in ("render", "output-status"):
        sub.add_parser(command).add_argument("trip_id")
    web = sub.add_parser("render-web", help="仅为已确认计划生成网站，必须明确选择风格")
    web.add_argument("trip_id")
    web.add_argument("--theme", required=True, choices=("guide", "journal", "map"))
    web.add_argument("--map-config", help="私有地图接入配置 JSON；只含浏览器 amap_key 与安全代理 service_host")
    fit = sub.add_parser("budget-fit", help="只读预算额度试算，不修改报价或计划")
    fit.add_argument("--input", required=True, help="完整旅行 JSON")
    imported = sub.add_parser("budget-import", help="网页试算草稿转待审核候选，不自动提交")
    imported.add_argument("trip_id")
    imported.add_argument("--input", required=True)
    profile_read = sub.add_parser("profile-read")
    profile_read.add_argument("profile_id")
    profile_propose = sub.add_parser("profile-propose")
    profile_propose.add_argument("profile_id")
    profile_propose.add_argument("--input", required=True, help="长期偏好 values 对象，不包含单次需求或健康背景")
    profile_propose.add_argument("--expected-revision", type=int, default=0)
    profile_commit = sub.add_parser("profile-commit")
    profile_commit.add_argument("profile_id")
    profile_commit.add_argument("change_id")
    profile_commit.add_argument("--decisions", required=True)
    query = sub.add_parser("query")
    query.add_argument("capability", choices=CAPABILITIES)
    query.add_argument("--conditions", required=True, help="查询条件 JSON 文件")
    query.add_argument("--response", help="用户提供或模拟返回的 JSON 文件；省略则返回 unavailable")
    query.add_argument("--mock", action="store_true")
    return root


def execute(args):
    if args.command == "budget-fit":
        from travel_planner.allocation import fit_trip
        document = load_json(args.input)
        report = validate(document)
        if report["errors"]:
            raise PlannerError("validation", "旅行结构或预算分配无效", errors=report["errors"])
        return {"allocation": fit_trip(document), "budget": report["budget"]}, 0
    if args.command == "validate":
        report = validate(load_json(args.input))
        return report, 2 if report["errors"] else 0
    if args.command == "query":
        request = CapabilityRequest(args.capability, load_json(args.conditions))
        if not isinstance(request.conditions, dict):
            raise PlannerError("conditions", "查询条件必须为对象")
        result = ProvidedDataAdapter(load_json(args.response) if args.response else None, args.mock).query(request)
        return asdict(result), 0
    store = Store(args.data_dir)
    if args.command == "init":
        return store.init(args.trip_id, args.title, args.mock, args.profile_id), 0
    if args.command == "read":
        return store.read(args.trip_id, args.revision), 0
    if args.command == "propose":
        return store.propose(args.trip_id, load_json(args.input), args.scope, args.reason), 0
    if args.command == "commit":
        document = store.commit(args.trip_id, args.change_id, load_json(args.decisions) if args.decisions else None)
        result = {"document": document, "outputs": output_status(store, args.trip_id)}
        if not args.no_render:
            try:
                result["outputs"] = render(store, args.trip_id)
            except (OSError, PlannerError) as error:
                # HEAD committed successfully. Never imply rollback or advertise stale outputs.
                result["output_error"] = {"code": "render_failed", "message": str(error),
                                          "recovery": "数据已提交；原输出保留为历史，执行 render 重试"}
        return result, 0
    if args.command == "compare":
        return store.compare(args.trip_id, args.old_revision, args.new_revision), 0
    if args.command == "restore":
        return store.restore(args.trip_id, args.revision, args.scope), 0
    if args.command == "render":
        return render(store, args.trip_id), 0
    if args.command == "render-web":
        return render(store, args.trip_id, website=True, theme=args.theme,
                      map_config=load_json(args.map_config) if args.map_config else None), 0
    if args.command == "budget-import":
        from travel_planner.web import import_budget_draft
        return import_budget_draft(store, args.trip_id, load_json(args.input)), 0
    if args.command == "output-status":
        return output_status(store, args.trip_id), 0
    if args.command == "profile-read":
        return store.profile_read(args.profile_id), 0
    if args.command == "profile-propose":
        return store.profile_propose(args.profile_id, load_json(args.input), args.expected_revision), 0
    if args.command == "profile-commit":
        return store.profile_commit(args.profile_id, args.change_id, load_json(args.decisions)), 0
    raise PlannerError("command", "未知命令")


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        settings = load_settings(args.runtime_config)
        args.data_dir = args.data_dir or settings.data_dir
        result, status = execute(args)
        print(json.dumps({"ok": status == 0, "result": result}, ensure_ascii=False, indent=2))
        return status
    except PlannerError as error:
        print(json.dumps({"ok": False, "error": error.as_dict()}, ensure_ascii=False, indent=2))
        return 2
    except (OSError, ValueError, TypeError, KeyError, RuntimeConfigError) as error:
        print(json.dumps({"ok": False, "error": {"code": "input_or_io", "message": str(error)}}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
