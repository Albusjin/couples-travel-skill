# 接收方 Agent 安装与使用交接

适用版本：通用分享版 1.1.0；维护日期：2026-11-02。先读本文，再按当前宿主选择模板。安装请求授权的是本 Skill 的必要安装、配置及只读验收；它不授权交易、泄露凭证、覆盖其他应用配置或更改其他旅行。

## 1. 确认你拿到什么

本目录是完整 Skill：SKILL.md 为业务入口，scripts 为 Python 校验/存储核心，config 为运行设置和 MCP 模板，references 为规则与数据映射。模型和宿主不随包提供，也不含 API Key、账号、真实旅行、预装依赖或虚拟环境。

仓库内本文位于 skills/travel-planner；专用 ZIP 内位于 travel-planner。下文命令均从这个 **Skill 根目录**执行。用户无需学习命令，由 agent 执行并解释。新解压 ZIP 可先用 Python 3.11+ 执行 `scripts/verify_package.py` 校验内置清单；源码目录没有生成的 MANIFEST.json，不能执行此项发行包校验。校验证明文件一致性，不代替可信下载来源。

## 2. 轻量预检，保留原环境

检测实际运行位置、系统、架构、宿主名称/版本、Python、已有依赖、Node/npm（仅铁路需要）、磁盘及内存。Windows、macOS、Linux 共用业务代码；其他系统或普通网页聊天只能说明缺口，不宣称安装成功。远程机器不能冒充用户本地，未经确认的容器磁盘不作永久私有存储。

优先复用合适解释器和环境。不为本任务安装整套开发工具、模型、Docker 或浏览器。串行安装和查询，不后台刷新；资源不足先缩小到离线核心。Windows 可用 py -3 或实际 Python 路径，macOS/Linux 用实际 Python 3.11+；系统自带 python3 可能太旧，先检查。

必要人工作业集中询问：宿主无法检测时确认目标应用；用户未指定时确认私有数据目录；缺 Key/登录时引导本地安全输入。其余可检查事项自行完成，当前授权已覆盖的步骤不反复询问。

安装/更新与既有可用版本隔离。复制到空目录，不删除或覆盖现有 skill、venv、旅行快照和宿主配置；遇到同名版本先比较，保留旧版再切换。修改配置前备份，**只合并所需服务项**，保留模型与其他服务。含 Key 的备份也属私密文件。

## 3. 安装 Skill 与核心

Codex 常用 ~/.agents/skills/travel-planner；DeepSeek Harness 常用 ~/.dsh/skills/travel-planner，默认也扫描前者。其他宿主查官方发现机制，或明确加载 SKILL.md。不要把整个仓库嵌套放进 skills 目录。

```sh
python3 scripts/install.py --destination "<目标绝对路径>"
```

Windows 可改用 py -3；替换上述路径，不原样执行。安装器拒绝已有目标。复制后切换到 **安装后的 Skill 根目录**，不要再配置旧解压目录。按 config/runtime.local.example.toml 创建本机 config/runtime.local.toml，设置目标机 data_dir；真实数据必须在安装包及 Git 仓库外、获授权且能持久保存的私有目录。不复制发布者的路径、代理、Key 或档案。

已有合适 Python 且含 jsonschema/tzdata 时直接复用，否则检查资源后执行：

```sh
python3 scripts/runtime.py bootstrap --core-only
python3 scripts/runtime.py doctor --core-only
python3 scripts/runtime.py run validate --input examples/demo-trip.json
```

Windows 对应 py -3。bootstrap 只创建配置的 venv 并安装核心依赖，run 优先使用该环境，不必激活。已就绪不重复安装。doctor --core-only 中 Node/专用 venv 非必需项失败不等于核心失败，必需检查全过才算核心就绪。validate 的结构错误在 JSON result.errors，不能只看退出码；规划结果另查 can_confirm 和三态。

离线端到端演示：用有效解释器执行 `examples/walkthrough.py --data-dir "<全新仓库外临时目录>"`。若 bootstrap 创建了 venv，用 doctor 返回的 venv_python。应得到 mock 修订、确认/锁定/局部修改及三份输出。演示确认是虚构夹具，不能替代用户授权。核验后只清理本次创建的临时演示目录。

## 4. 连接并限制 MCP

阅读 [宿主配置指南](references/harness-setup.md)，再按宿主选择：

- Codex：config/mcp-codex.example.toml，四服务默认 enabled=false。
- DeepSeek Harness：config/mcp-deepseek.example.cordis.yml，四服务默认 disabled=true。
- 其他宿主：依官方文档转换；没有通用配置语法，不换掉用户现有宿主。

复用目标机已有、获授权的同身份服务，不为了统一名字重装。新接入按模板官方端点/固定版本配置，社区铁路不是铁路官方 MCP。替代供应商须核验官方来源、鉴权与 schema，并说明覆盖差异；不选陌生代理、不自动升级 latest，不继承发布者验收。缺某项时继续独立步骤。

Key 只通过本地凭证界面、隐藏输入或私有进程环境设置。不让用户在聊天粘贴，不回显已有凭证，不记录带 Key URL、Authorization、命令历史或整份配置。亲友专用 Key 也不进公开包。模型 Key 与旅游服务 Key 独立；铁路不需要铁路密码或证件。

工具白名单取 config/mcp-routing.toml。Codex 保留 enabled_tools；其他宿主按实际权限/过滤机制落实，不能伪造兼容字段。DSH 模板本身不执行工具过滤，尤其滴滴若无法限制到 maps_textsearch/taxi_estimate，保持停用并报告缺口。自然语言规则不等于宿主隔离。任何宿主均不调用发单、支付、锁价、取消、订单或司机跟踪工具。

原 runtime.py mcp-config 只生成 Codex 高德/铁路模板，setup-amap --apply 只写 Codex 高德；**不要在 DSH 或其他宿主用它配置 MCP**。不要用默认带 --apply 的双击启动器探测环境。

## 5. 分层验收

按 [接入与验收](references/mcp-setup.md) 对所需服务做少量匿名、只读真实查询，不创建真实旅行或交易。

| 层次 | 通过证据 |
| --- | --- |
| Skill 发现 | 当前会话可加载安装后的 SKILL.md 与相对引用 |
| 离线核心 | Python/依赖就绪，示例校验和 mock 全流程成功 |
| MCP 连接 | 当前会话实际发现工具/schema，权限范围正确 |
| 高德 | 公共 POI 搜索/详情及路线/天气，地点、单位、覆盖日期正确 |
| 铁路 | 当前日期→可查日→站码→车次，实际车站/乘车日/时刻正确 |
| 酒店 | 未来可查日，两成人一间房，搜索→一间详情，记录价税/房型/退改缺口 |
| 滴滴 | 自身地点检索后一次预估；当前价不当未来预约价，不保证有车 |

各项单独标 passed / partial / unavailable / not_tested，记录匿名条件、时间、覆盖字段和失败阶段。鉴权/配额不循环重试，瞬时网络最多重试一次。只返回模拟、错误条件或业务拒绝不算真实通过。工具发现不等于业务验收，历史成功不证明新机器成功。

报告写用户私有目录：安装路径、宿主/系统版本、实际解释器、核心结果、各服务状态、允许工具范围、待人工事项和启动方式。不得含凭证、带 Key URL、整份环境或真实订单。最终准确说“离线可用”“部分实时服务可用”或“所选实时服务已验收”，不能把缺失项报成全功能。

## 6. 使用、更新和清理

用户可说：“使用 travel-planner，从广州出发，两个人三天自由行，先比较高铁＋打车和自驾。”按 SKILL.md 先候选、再选择/细化；需要保存才在已确认的私有目录初始化真实旅行。不导入演示资料或将 mock 改成 real。

首次说明原包默认：两人一间大床、酒店 ¥200–300/晚及华住偏好，不是朋友已确认的长期档案。自动挡、到酒店早于 22:00 等现有硬规则保持；用户明确调整/日期例外按规则处理，不静默放松。非双人出行先说明本版范围。

实时 MCP 由 agent/宿主调用，Python CLI 不自动查询供应商。结果按 references/mcp-usage.md 映射、校验、保存。缺网页搜索时保留景区公告/票务等缺口；不凭空写 verified，不把当前估价或参考日铁路当目标日事实。

修改既有旅行先 read，确认、锁定、版本和输出按 SKILL.md。安装授权不是旅行确认或交易授权。不直接编辑 HEAD 或覆盖历史。更新时新目录安装验收后再切换，保留旧版及全部私有数据。结束后关闭自己启动且不再需要的进程，清理临时演示文件。
