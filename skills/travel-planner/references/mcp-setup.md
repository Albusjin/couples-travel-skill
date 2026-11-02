# MCP 筛选、实测与 macOS / Windows 接入

初次核对日期：2026-11-01。提供 macOS / Windows 独立启动器；云端 Linux 的协议与模拟测试不等于实际电脑已配置。用户本机高德 v4 报告截图已显示 `data_mode=live`、`passed=true`，仅证明辅助工具限定的杭州地点、驾车/步行和近期天气检查；配置写入与重启后 Codex 加载尚待确认。两台电脑的 MCP 配置、Node 安装和凭证都需分别处理，不自动同步真实旅行数据。

运行层重构版使用一份 [MCP 服务定义](../config/mcp-servers.toml) 和 `scripts/runtime.py` 共用入口。默认路径、Python/Node/npm 覆盖、代理与证书配置、跨系统迁移步骤详见 [系统迁移指南](system-migration.md)。以下真实能力记录保留原测试版本与日期；当前辅助工具版本为 v5，重构未代替新的业务验收。

## 1. 先接入什么

| 候选 | 来源/用途 | 本次实测 | 决定 |
| --- | --- | --- | --- |
| 高德 `@amap/amap-maps-mcp-server@0.0.8` | 官方文档指定的包；地点、驾车/步行/公交、距离、天气 | 云端协议测试通过；用户本机 v4 报告截图显示限定的真实地点、驾车/步行和天气检查通过 | 首选；配置写入及 Codex 加载待确认，公交等未测试 |
| 百度 `@baidumap/mcp-server-baidu-map@1.0.5` | 官方文档指定的包；地点、路线、天气、路况 | 同样完成协议测试（10 项）；缺 AK 启动失败 | 备用，不必同时装两套地图 |
| `12306-mcp@0.3.10` | Joooook 社区项目；车站、余票、经停/中转 | 初始化访问铁路网站，被云环境代理 CONNECT 403 拒绝，未拿到工具列表/真实车次 | 可选，本机复测前默认停用；不是铁路官方 MCP |
| Booking.com 官方 MCP | 酒店等能力按合作方账号开放 | 只核实官方接入文档；没有 Affiliate ID 和 Demand API Key，未连接/查询 | 暂不作为本项目默认酒店/租车源 |
| 携程/美团等境内酒店、租车 | 官方合作 API 与第三方项目需分别甄别 | 未验证到可直接用于本项目的消费者实时库存 MCP | 不宣称已经支持房价、房型库存或自动挡租车报价 |

原始测试摘要见 [MCP 实测记录](../examples/mcp-verification-2026-11-01.json)。占位 Key 只用于验证协议发现，没有通过它请求真实地图数据。高德 npm 包版本为 0.0.8，其握手自报服务版本为 0.1.0；百度对应为 1.0.5 / 1.0.0，记录时不能混同。

官方/项目来源：

- [高德快速接入](https://lbs.amap.com/api/mcp-server/gettingstarted)、[创建 Web 服务 Key](https://lbs.amap.com/api/mcp-server/create-project-and-key)。官方同时支持 Streamable HTTP 与本地 stdio；这里优先给出本次实际测试过的 stdio 固定版本。
- [百度快速接入](https://lbsyun.baidu.com/docs/ai?title=mcpserver/quickstart)、[官方仓库](https://github.com/baidu-maps/mcp)。注意 Node 包使用 `BAIDU_MAP_API_KEY`，Python 包文档使用 `BAIDU_MAPS_API_KEY`，不能混用。
- [12306 社区仓库](https://github.com/Joooook/12306-mcp)。本次发布包会先获取查询页面和车站列表，才能启动 MCP；“无需铁路账号”不等于“离线可启动”。
- [Booking 官方接入](https://developers.booking.com/mcp-server/docs/implementation-guide)。账号可用工具取决于合作方配置，酒店/租车覆盖需另验，不能用普通 Booking 登录账号代替合作方授权。
- [Codex 官方 MCP 配置说明](https://developers.openai.com/codex/mcp)。本次也用实际 `codex-cli 0.163.0` 的帮助及临时配置覆盖检查了 TOML 字段，没有改写用户配置。

API 配额、价格、认证要求以服务商控制台和账号实际权限为准；本次没有验证免费额度或无限调用承诺。

## 2. 在这台 Mac 上准备

在 **Mac 本机“终端”App** 执行，不能把本聊天的云终端当成本机：

```sh
node --version
npx --version
command -v npx
```

推荐 [Node.js 24 LTS](https://nodejs.org/)。高德官方建议至少 22.14.0，社区铁路文档标注 Node 18+，但其当前发布依赖含 Inspector，实际选择 24 LTS 可满足本次测试所用依赖。没有 Node 时先按官网安装，完全退出并重开 Codex。

在高德开放平台创建应用，添加 **Web 服务** 类型 Key，查看所需接口、账号权限与配额。不要申请成仅适用于浏览器的 JS API Key，也不要把 Key 发到聊天、提交到 Git 或放进旅行 JSON。

## 3. 添加私有 Codex 配置

### 推荐：先真实测试，通过后自动合并

已提供 `scripts/setup_amap.py`，在用户自己的电脑运行。它不会注册账号；请先在官方控制台完成开发者注册，创建 Travel Planner 应用及 Web 服务 Key。登录、验证码和实名验证由用户本人处理，无须向聊天发送 Key。

在已解压的项目根目录，用本机终端执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r skills/travel-planner/requirements-amap-setup.txt
.venv/bin/python skills/travel-planner/scripts/setup_amap.py --apply
```

macOS 也可在本机终端运行 `bash skills/travel-planner/scripts/setup-amap.command`。薄启动器转交共用 `runtime.py` 检查与安装流程，默认在本机 `~/Library/Application Support/TravelPlanner/amap-setup-venv` 创建独立依赖环境；不会预先写入 MCP 配置。目录可通过本机运行配置覆盖。

Windows 使用 `scripts/setup-amap.cmd`：解压后双击，或在命令提示符运行。启动器找到初始 Python（可用 `TRAVEL_PLANNER_PYTHON` 指定，否则优先 `py -3`，其次 `python.exe`），随后转交同一 `runtime.py` 流程，默认在 `%LOCALAPPDATA%\TravelPlanner\amap-setup-venv` 创建独立依赖环境。默认配置路径为 `%USERPROFILE%\.codex\config.toml`；`CODEX_HOME` 或本机运行配置可覆盖。Key 仍在 Python 本机隐藏提示中输入，不进入批处理参数。

Windows 下测试与最终 MCP 配置都使用 node.exe 执行 npm 的 npx-cli.js，避免把 npx.cmd 直接交给原生进程启动器；官方 Node 安装包的常规目录受支持，缺少 npm 文件时明确失败。Windows 文件访问权限使用用户目录的 NTFS ACL，不能将 POSIX 的 0600 描述当成 Windows 权限保证。无需修改 PowerShell 执行策略，也不要求管理员权限。

脚本会在本机静默读取 Key（也支持已有 AMAP_MAPS_API_KEY 环境变量），完成握手/工具发现后，实际执行 7 次公共地点业务查询：杭州东站与西湖的地点搜索和详情、两地驾车/步行路线、杭州近期天气。结果需满足名称/城市/坐标、路线起终点和正数距离耗时、有效天气日期等检查；缺失、歧义、网络、权限或配额错误均不写配置。

两个启动器均添加 `--prompt-key`，每次在本机重新输入，不使用已有环境变量中的旧 Key。直接调用 Python 时也可加该参数；不加则仍支持显式环境变量工作流。报告只记录 credential_source（local_prompt/environment），不显示 Key。高德返回 INVALID_USER_KEY 时表示此次使用的 Key 不正确或已过期，请重新复制控制台的 Key 字段（不要复制安全密钥），并核对有效状态与 Web 服务类型；工具列表加载成功不代表鉴权通过。官方错误说明：https://lbs.amap.com/api/webservice/guide/tools/info/

如果已确认控制台字段与状态，MCP 仍返回 INVALID_USER_KEY，工具会追加一次同 Key 的高德地理编码接口直连诊断（公共地标杭州东站），记录 direct_key_diagnostic 的 status/info/infocode、输入长度及是否为 32 位十六进制，不记录 Key 或带查询参数的 URL。直连成功而 MCP 失败时重点检查 MCP 链路/接口差异；直连也返回 10001 时说明高德后端同样拒绝该输入值；网络/证书错误则标为诊断未完成，不能推断 Key 错误。直连成功不替代全套 MCP 业务验收，仍不强行写配置。

地点测试支持“杭州/杭州市”前缀、5A 等级标签及明确景区别名，并按 POI ID 去重。若仍有多个候选或名称不匹配，工具会在本机列出实际搜索结果，要求输入编号选择（0/回车取消）；不会默选第一条。选定后还须核对详情 ID、名称、杭州城市及坐标，才能继续道路和天气查询。此选择只用于连通性测试，不写入个人偏好或真实行程。

全部检查通过且带 `--apply` 时，才备份并合并本机 `~/.codex/config.toml` 的 travel_amap 表，保留其他模型/服务器配置。Key 保存在本机 env 表中，macOS 文件权限为 0600，Windows 依用户目录 NTFS ACL 保护；不要分享配置或备份。测试期间配置发生变化会停止，写入失败保留原文件。省略 `--apply` 只测试。通过后完全退出并重开 Codex，新聊天复测；脚本成功不代表已经验证 App 的实际加载。

可选 `--report <全新的私有JSON路径>` 保存脱敏测试记录；已有报告不覆盖。输出不会包含 Key，也不会自动上传到本项目或聊天。自动化测试使用模拟夹具；用户已创建 Web 服务 Key，并回传 v4 真实测试通过截图。应继续检查完整报告的 `configuration_written` 及 Codex 内工具发现，不能把模拟测试或 `passed=true` 单独当作 Desktop 已完成接入。

### 手工配置参考

配置文件默认是本机 `~/.codex/config.toml`，自定义时遵循 `CODEX_HOME` / `paths.codex_home`。在 Skill 目录运行 `python3 scripts/runtime.py mcp-config`（Windows 初始命令为 `py -3`）从 [共用定义](../config/mcp-servers.toml) 生成目标机 TOML。先备份已有文件，再合并生成的两个表；不要覆盖已有模型、项目或其他 MCP 配置。同名表已存在时修改原表，不要重复添加。生成命令不会写入 Codex 配置；输出仍需在本机保管，可能含 PATH 和代理配置。配置是 TOML，不是 Cursor 的 `mcpServers` JSON。

最小高德配置如下，工具白名单建议使用完整模板：

```toml
[mcp_servers.travel_amap]
command = "npx"
args = ["-y", "@amap/amap-maps-mcp-server@0.0.8"]
env_vars = ["AMAP_MAPS_API_KEY"]
startup_timeout_sec = 45
tool_timeout_sec = 60
```

### 凭证方式 A：从环境注入

模板用 env_vars 转发 Key。Mac 的 Finder/Dock 启动的 App 不一定继承终端 export 或 `.zshrc`；只执行 export 不能保证已运行的 Codex 拿到 Key。可在本机默认 zsh 终端静默输入，再注入当前登录会话：

```sh
read -rs "AMAP_MAPS_API_KEY?输入高德 Web 服务 Key："
printf '\n'
export AMAP_MAPS_API_KEY
launchctl setenv AMAP_MAPS_API_KEY "$AMAP_MAPS_API_KEY"
```

Key 不会以字面量出现在这组命令的历史里。随后 **Cmd+Q 完全退出 Codex，再重新打开**。launchctl 的设置不保证注销/重启后仍存在，之后需重新注入；不要在共享机器上使用此方式。

### 凭证方式 B：本机私有配置持久保存

若不想每次登录重新注入，可在同一个私有 config.toml 中添加：

```toml
[mcp_servers.travel_amap.env]
AMAP_MAPS_API_KEY = "只在本机填入真实Key"
```

这会将 Key 明文保存在本机用户配置，需自行保护文件并避免同步到公开仓库或分享完整配置。该方式不依赖 GUI 继承 shell 环境；可去掉对应 env_vars 项。模板本身不含真实 Key。不要把 `${AMAP_MAPS_API_KEY}` 写进 TOML 值期待自动插值。

### npx 找不到的情况

如果 Codex 报 `No such file or directory`，将 command 改为 `command -v npx` 返回的实际绝对路径。若报 `env: node: No such file or directory`，还需让 Codex 的服务器进程 PATH 包含 `command -v node` 所在目录；只改 npx 的绝对路径并不能解决缺 node。Homebrew、官网安装与 nvm 的路径不同，不要照抄其他电脑的路径。

## 4. 验收真实高德查询

新开一个 **本机** Codex 聊天，先检查 MCP 工具是否可见，然后发送：

> 只读测试 travel_amap。先列出实际可用工具；用高德查询“杭州市杭州东站”和“杭州市西湖风景名胜区”的位置，确认城市与坐标。使用这次返回的同一坐标体系坐标查询驾车及步行路线，并查询杭州天气。逐项记录工具名、输入、查询时间、原始来源、实际距离/耗时、天气覆盖日期与错误。不要创建旅行、预订、发布地图或查询我的实时位置。没有真实结果就标记未通过，不用常识或估算补齐。

通过条件：

- 工具实际调用成功，不仅是列表里有名字；结果城市/地点正确，路线距离和耗时有真实返回。
- 保留原始单位：高德道路 distance 常以米、duration 常以秒返回，入主数据时显式换成 km/min；不要把直线距离当成驾驶距离。
- 高德和百度坐标体系/坐标参数顺序不同；保存来源与坐标体系，不能把两个服务的坐标直接混用。始终从同一服务检索地点再规划路线。
- 天气只采用实际返回的日期范围，不把短期预报延伸到尚未覆盖的旅行日期。当前查询的路程耗时也不能包装成未来某天的保证。
- 本次 npm 高德服务列出的 12 项工具没有直接生成专属地图链接的工具；不能据此宣布导航入口或可视化地图已通过。导航入口另行按实际提供的工具/官方 URI 能力验证。
- 房间日期价格、库存、退改及自动挡租车条件不能从“酒店/租车门店 POI”推断出来。

`tools/list` 成功但 INVALID_USER_KEY、接口无权限、超配额、网络或业务错误均不算业务通过。高德 Key 问题应检查类型/启用服务/配额；不要通过生成虚构结果绕过。

## 5. 再测试铁路 MCP

完整模板里的 travel_rail 默认 `enabled=false`。准备在 Mac 的实际网络复测时改为 true，完全重启/新建会话。若失败，恢复 false，避免影响其他规划。该服务不需要把铁路账号、密码、证件或订单提供给 MCP。

```toml
[mcp_servers.travel_rail]
command = "npx"
args = ["-y", "12306-mcp@0.3.10"]
startup_timeout_sec = 60
tool_timeout_sec = 60
enabled = true
```

先运行以下本机聊天验收提示，余票测试日期以实际运行时中国标准时间为准，不使用本指南编写日期：

> 只读测试 travel_rail。先完成连接并列工具，查询“杭州东”和“上海虹桥”的站点编码；再获取当前上海时区日期，选择明天查询两站间高铁车次，最多返回 3 条。区分车次时刻、席别余票和票价是否真的返回，记录日期、来源和查询时间。遇到超售票期、网站风控、空结果或解析错误要如实报告，不登录、不下单、不重试刷接口。

本次云环境的 403 是 CONNECT 代理拒绝，不能据此断言你的 Mac 或铁路服务一定不可用；反过来，本地启动成功也不保证查询成功。铁路站点/页面变化可能导致社区包解析失败，须保留人工去官方平台核对的降级方式。

## 6. 接入 Travel Planner 与第二台电脑

连接后的调用由 **Codex Skill 编排 MCP**，并将核验过的结果规范化为 SourceRecord、RouteSegment、Quote 等，再交给 Python 校验/保存。`travel.py query` 目前仍是资料/模拟适配接口，不会因为添加 MCP 配置就自动变成供应商 SDK；也没有静默抓取浏览器账号的逻辑。

开始规划时可以说：

> 使用 $travel-planner，先检查 travel_amap 和 travel_rail 的连接与已验证能力，再规划我的旅行。只使用真实调用结果提升证据等级；缺失房价/余票等继续标注待核实。

把本机验收摘要另存到用户私有目录；公共仓库只能保存匿名公共地点的脱敏测试摘要，不上传 Key、完整订单或真实私人行程。若这仍是云任务，必须先确认所需 MCP 在该聊天中可见，不能因本机配置过就假设云执行器能访问本地服务。

另一台电脑需要独立安装 Node、合并配置和配置自己的 Key/AK。建议每台设备单独 Key，便于撤销与排错；配额仍按提供商账号规则计算。复用同一 Skill 和服务定义，在目标机运行配置中填写实际 Python/Node/npm 路径，再由共用运行层生成命令，不能直接复制旧机绝对路径。完整步骤见 [系统迁移指南](system-migration.md)。两台电脑的旅行主数据仍应分别指定私有位置，本次不自动建立云同步或公开发布。

## 7. 可选远程高德 / 百度

高德官方还提供 Streamable HTTP：`https://mcp.amap.com/mcp?key=本机真实Key`；百度为 `https://mcp.map.baidu.com/mcp?ak=本机真实AK`。Codex 使用相应 `[mcp_servers.<name>] url = "…"` 表，不能把 SSE 地址当作 Streamable HTTP 地址。

远程方式未在本次完成认证或 tools/list，返回工具可能与上述 npm 固定版本不同，需重新发现并建立只读白名单；不要直接套用 npm 白名单导致误判工具缺失。真实 Key 在 URL 中，完整 URL 同样是凭证，不放进公开配置、日志或聊天。优先从本次 stdio 配置开始，一次只验证一个地图提供商。
