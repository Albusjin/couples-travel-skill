# Travel Planner · 通用分享版 1.1.0

供 AI agent 使用的中国大陆双人自由行 Skill：需求梳理、目的地/交通比较、地图/铁路/酒店/打车研究、行程预算、确认与局部修改。Python 核心负责校验、版本和 Markdown，实时查询由宿主 MCP 提供。

## 把这段话交给你的 agent

> 请阅读本目录 AGENT_HANDOFF.md，按实际系统和当前 Harness 完成隔离安装、依赖检查、MCP 配置与分层验收。复用可用环境，保留已有设置和真实数据；凭证仅本地安全输入。缺少某项授权时继续独立步骤，分别报告离线与各实时服务状态。完成后说明如何开始规划旅行。

完整规范：[Agent 交接](AGENT_HANDOFF.md)。安装后的业务入口：[SKILL.md](SKILL.md)。

## 包含与要求

- Windows、macOS、Linux 共用业务代码，Python 3.11+；本地铁路才需要 Node/npm。
- 提供 [Codex 四服务 TOML](config/mcp-codex.example.toml) 与 [DeepSeek Harness 四服务 YAML](config/mcp-deepseek.example.cordis.yml)，无密钥且默认停用。
- Agent 需能读文件、执行命令、连接 MCP。其他宿主按官方文档适配；不保证所有应用开箱即用。
- 不含模型、Key、账号、真实行程、虚拟环境或预装依赖。实时授权和查询在目标机验收。
- 不执行下单、支付、叫车、取消或定位跟踪，不后台轮询。

原包默认两人一间大床、酒店 ¥200–300/晚及华住偏好；首次说明自己的偏好，不把默认当作已确认档案。自动挡、到酒店早于 22:00 等硬规则及例外见 [规则](references/rules.md)。

## 使用

安装验收后说：“使用 travel-planner，从广州出发，两个人三天两晚，先比较高铁＋打车和自驾。”先比较候选，选择后细化。也可要求修改第二天、核对预算、恢复先前安排。未知费用不按零算，参考日铁路不当目标日排班，整车费不乘人数。真实数据只写用户确认的安装包/仓库外私有目录。

## 给 agent 的命令入口

从本目录执行，下列 python3 代表实际 Python 3.11+，Windows 可用 py -3：

```sh
python3 scripts/verify_package.py
python3 scripts/install.py --destination "<目标绝对路径>"
```

第一条仅用于带 MANIFEST.json 的新解压 ZIP，源码目录没有此生成文件。第二条需替换实际路径。安装后切换到安装目录，按 config/runtime.local.example.toml 配置本机路径及私有目录，再继续：

```sh
python3 scripts/runtime.py bootstrap --core-only
python3 scripts/runtime.py doctor --core-only
python3 scripts/runtime.py run validate --input examples/demo-trip.json
```

已有合适环境及依赖不重复 bootstrap。数据目录未确认前只讨论、不保存真实资料。mock 演示不代表真实服务或真实用户确认通过。

## 按需阅读

- [跨 Harness 配置](references/harness-setup.md)：宿主模板、授权、工具权限和官方来源。
- [MCP 调用与数据映射](references/mcp-usage.md)：查询时机和证据规范。
- [MCP 验收与故障](references/mcp-setup.md)：连接与业务分别验证。
- [系统迁移](references/system-migration.md)：解释器、路径、更新和回滚。
- [数据与 CLI](references/data-and-cli.md)：结构、确认、存储、输出。

原 mcp-config/setup-amap 只面向 Codex 高德/铁路，不负责 DSH。DSH 模板不自带工具过滤，未落实查询白名单时不启用滴滴等含交易能力的连接。

[项目源码与更新](https://github.com/Albusjin/couples-travel-skill)。接入说明核对于 2026-11-02，目标机仍需验证宿主版本、网络、授权和返回字段。数据结构版本为 1.0。
