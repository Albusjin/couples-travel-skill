# Travel Planner · 通用版 1.2.0

面向中国大陆双人自由行的 Agent Skill：用选择题完善需求，给出有理由和资料入口的景点组合，比较交通住宿，细化景区内部路线，分配总预算，管理确认、锁定和修改历史。

## 把安装交给你的 Agent

解压后用能访问文件、执行命令的 agent 打开本目录，并发送：

> 请先阅读 AGENT_HANDOFF.md，按当前电脑和宿主完成隔离安装、依赖检查、运行配置和分层验收。优先复用已有环境与 MCP，保留现有设置和旅行数据；必要时只向我收集宿主、私有存储位置或授权。凭证由我在本机安全输入。先完成离线核心，再接通我需要的实时查询，最后说明可用范围与使用方法。安装阶段不生成或发布网站。

完整规范：[AGENT_HANDOFF.md](AGENT_HANDOFF.md)。规划入口：[SKILL.md](SKILL.md)。版本变化：[CHANGELOG.md](CHANGELOG.md)。

## 安装后的用法

- “使用 travel-planner，我们想周末出去玩，用选择题了解偏好，先给景点和大致路线。”
- “帮我们细化张家界森林公园内部路线，包括入口、景点顺序、接驳、索道和体力。”
- “双人预算 6000 元，车票 1200 元、租车 800 元固定，分配剩余支出，先不生成网站。”
- “读取上次旅行，把第二天安排轻松一些，先展示对费用和其他日期的影响。”

先候选、再选择和细化，具体计划确认后保存。普通攻略与预算表已包含园内路线和额度分配，不依赖网站。网站/地图仅保留功能基础，视觉方向尚未定稿；具体计划确认并选定风格后才能显式生成，地图接入与真实路径另行验证。

## 环境与数据

Python 3.11+；核心依赖为 jsonschema/tzdata，优先复用。Windows、macOS、Linux 共用逻辑，本地铁路连接才需要 Node/npm。Codex、DeepSeek Harness 有默认停用的无密钥配置参考，其他宿主查其官方机制。

不含模型、Key、账号、真实旅行、发布者配置或虚拟环境。离线核心可先使用，实时服务在目标机分别授权和验证。需要网页搜索时由宿主提供，缺失字段保留未知；不执行交易、叫车、取消、定位跟踪或后台轮询。

默认两人一间大床，¥200–300/房晚及华住是软偏好，不是用户已确认档案。自动挡和早于 22:00 到酒店等规则见 [rules.md](references/rules.md)。真实数据仅放用户确认的安装包/仓库外私有目录。

## 给 Agent 的命令入口

以下从本 Skill 根目录执行，`python3` 代表实际 Python 3.11+，Windows 可用 `py -3`。所有占位路径由 agent 替换，用户不用学习命令。

```sh
python3 scripts/verify_package.py
python3 scripts/install.py --destination "<目标绝对路径>"
```

校验脚本仅用于带 MANIFEST.json 的新解压 ZIP；源码目录按 Git/发行来源核对。安装后切换到安装目录，按 `config/runtime.local.example.toml` 创建本机配置，然后执行：

```sh
python3 scripts/runtime.py doctor --core-only
python3 scripts/runtime.py run validate --input examples/demo-trip.json
python3 scripts/runtime.py run budget-fit --input examples/demo-trip.json
```

缺少依赖时才执行 `python3 scripts/runtime.py bootstrap --core-only`，之后重新检查。`validate` 同时检查 JSON `result.errors`；预算 `allocated` 只是额度可分配，不证明价格和库存已核实。不要将演示 mock 数据用于真实旅行。

## 按需阅读

- [交接规范](AGENT_HANDOFF.md)：安装、配置、验收报告、升级和回滚。
- [宿主配置](references/harness-setup.md)：Codex / DeepSeek Harness、工具范围与官方来源。
- [交互与推荐](references/interactive-planning.md)：选择题、实景/介绍与登录选择。
- [景区、地图与网站](references/scenic-and-web.md)：内部路线、地图数据和预算草稿。
- [数据与 CLI](references/data-and-cli.md)：数据契约、确认、版本与输出。
- [系统迁移](references/system-migration.md)、[MCP 验收](references/mcp-setup.md)：目标环境适配与失败分支。

[项目源码与最新下载](https://github.com/Albusjin/couples-travel-skill)。发行包版本 1.2.0，数据结构版本 1.0。
