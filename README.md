# Couples Travel Skill · 情侣自由行规划

一份交给 AI agent 使用的中文旅行规划 Skill：从需求和目的地比较开始，研究高铁、自驾、租车及两人合乘打车，生成带来源、预算和待核实事项的行程，并保存确认、锁定与局部修改的版本。

**通用分享版 1.1.0**：业务规则与 Python 核心共用，提供 Codex / DeepSeek Harness 无密钥 MCP 模板及接收方 agent 交接文档。Windows、macOS、Linux 按宿主适配；账号授权、网络与供应商覆盖仍需目标机验证，不承诺所有应用免配置即用。

## 下载后交给 Agent

1. 下载 [通用 Skill ZIP](https://github.com/Albusjin/couples-travel-skill/raw/refs/heads/main/releases/travel-planner-universal-1.1.0.zip)，解压得到完整 travel-planner 文件夹。[SHA-256 校验文件](releases/SHA256SUMS)
2. 在能操作文件、运行命令并连接 MCP 的 agent 中打开解压目录。
3. 把下面这段话交给它：

> 请阅读当前 travel-planner 目录中的 AGENT_HANDOFF.md，按实际操作系统与当前 Harness 完成隔离安装、依赖检查、MCP 配置和分层验收。复用可用环境，保留已有应用设置、Key 和旅行数据；凭证仅在本地安全输入。缺少某项授权时继续独立步骤，分别报告离线与各实时服务的可用性。完成后告诉我如何开始规划旅行。

完整规范：[Agent 安装与使用交接](skills/travel-planner/AGENT_HANDOFF.md)。下载整个 GitHub 源码 ZIP 也可以，Skill 根目录是 skills/travel-planner，不要把整个仓库安装成一个 skill。

## 能做什么

- 比较 2–3 个目的地或交通方案，说明双人费用、门到门时间、驾驶负担和住宿取舍。
- 查询地图、路线、近期天气、铁路、酒店和打车预估；不具备的字段透明保留未知。
- 两人合乘一辆车时整车费只计一次。远期铁路未排班时可用较早日期参考，保留目标日复核事项。
- 生成同一版本的 Markdown 攻略、预算与路线索引；区分已知、参考、待核实、实际支出和押金。
- 保存候选、用户确认、锁定项目和不可变修订；修改某一天时检查相邻依赖，支持受控恢复。

面向中国大陆双人自由行。默认一间大床房、酒店 ¥200–300/晚和华住偏好，可在首次使用说明个人偏好，不能视为朋友已确认的长期档案。自动挡、到酒店早于 22:00 等规则及例外机制见 [规则](skills/travel-planner/references/rules.md)。

不包含预订、支付、叫车、取消订单、定位跟踪、后台盯价、网站、Word/PDF 或手机独立执行版。普通网页聊天如无执行/MCP 能力，只能协助讨论。

## 运行方式与环境

```text
用户自然语言 → agent 读取 SKILL.md → 宿主调用已授权 MCP
                              ↓
                 Python 校验、预算、版本和 Markdown
```

Skill 不内置模型或完整实时客户端。模型调用宿主可见工具，再规范化结果交给 Python 核心。文件安装、MCP 连接、真实业务查询成功分别验收。

| 环境 | 要求与边界 |
| --- | --- |
| Windows / macOS / Linux | Python 3.11+，路径/启动方式由目标机配置，复用已有环境 |
| Codex | TOML 模板，保留 enabled_tools，只合并选定服务 |
| DeepSeek Harness | Cordis YAML overlay，目标机单独落实工具权限 |
| 其他 Harness | 支持文件/skill、命令、MCP，按官方文档转换并验收 |
| HTTP 服务 | 高德、滴滴、RollingGo 酒店，不另装本地 Node MCP 服务 |
| 铁路服务 | 社区 12306-mcp@0.3.10，需要 Node/npm 与目标网络可达性 |

四服务模板均默认停用且无 Key。模型 API Key 与旅游服务凭证独立。DSH 模板本身不执行工具过滤；尤其滴滴未落实查询白名单时保持停用。安装器不会自动寻找陌生代理或替换用户现有服务。

## 开始使用

安装验收后直接说：

> 使用 travel-planner，从广州出发，两个人三天两晚，先比较高铁＋打车和自驾，酒店希望干净舒适。

也可以说“第二天少走一点，其他已确认安排保持”“读取上次旅行，核对预算和待复核事项”。Agent 先读当前数据，展示方案，再取得必要的具体确认。

真实旅行、偏好和导出文件只写用户指定的仓库外私有目录。不要将本机配置、带 Key URL、订单、证件或虚拟环境重新压缩上传。亲友分享优先另建可撤销专用 Key，单独私下交付，不放公开包。

## 文件与文档

| 文档 | 用途 |
| --- | --- |
| [SKILL.md](skills/travel-planner/SKILL.md) | 旅行工作流入口 |
| [AGENT_HANDOFF.md](skills/travel-planner/AGENT_HANDOFF.md) | 安装、配置、验收、使用规范 |
| [Skill README](skills/travel-planner/README.md) | 随 ZIP 提供的使用入口 |
| [跨 Harness 配置](skills/travel-planner/references/harness-setup.md) | Codex、DSH、其他宿主及官方来源 |
| [Codex 模板](skills/travel-planner/config/mcp-codex.example.toml) | 四服务 TOML，默认停用 |
| [DSH 模板](skills/travel-planner/config/mcp-deepseek.example.cordis.yml) | 四服务 Cordis YAML，默认停用 |
| [MCP 路由](skills/travel-planner/config/mcp-routing.toml) | 服务职责、查询工具与缺口 |
| [系统迁移](skills/travel-planner/references/system-migration.md) | 本机路径、跨系统适配、回滚 |
| [数据与 CLI](skills/travel-planner/references/data-and-cli.md) | Schema、命令、确认、存储 |
| [原始 PRD](docs/Travel-Planner-PRD-v1.0.md) | 原项目需求基线 |

原 runtime.py mcp-config/setup-amap 继续保留为 Codex 高德/铁路辅助工具，不负责 DeepSeek，也不是四服务导出。

## 验证与重新打包

已有合适 Python 环境时，从仓库根目录执行，不启动外部服务：

```sh
python -m unittest discover -s tests -v
python scripts/build_release.py
```

这里 python 代表实际 Python 3.11+，Windows 可用 py -3。测试环境依赖见 skills/travel-planner/requirements-amap-setup.txt；接收方通常只需核心依赖。

打包器只读取 [发行白名单](release-files.json)，生成确定性 ZIP、逐文件 MANIFEST.json 和 SHA256SUMS，拒绝符号链接、过大文件和可识别凭证；白名单与内容仍需维护者审核，扫描不保证识别所有秘密。它不改已安装环境、原始项目或真实数据。校验值用于一致性检查，不是数字签名。

CI 配置包含三系统矩阵，是否通过以 Actions 为准，不代表接收方授权或真实业务验收。数据结构仍为 schema_version=1.0；分享包版本 1.1.0 不改变旧旅行结构。历史能力记录不外推到新机器。
