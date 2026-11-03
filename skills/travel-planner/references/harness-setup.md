# Codex、DeepSeek Harness 与其他 agent 接入

模板核对日期：2026-11-03。字段来自下方官方文档，目标版本仍须实际验证。模板不含 Key，四项连接均默认停用；本项目不承诺各平台免授权或自动全功能可用。

## 共用约定

先按 [AGENT_HANDOFF.md](../AGENT_HANDOFF.md) 完成环境与离线验收。业务入口始终为 `SKILL.md`，实际工具职责取 [mcp-routing.toml](../config/mcp-routing.toml)，输入和结果核验取 [mcp-usage.md](mcp-usage.md)。`travel_amap` 等是推荐本地服务名；命名不同的宿主按服务身份、实际工具名和参数建立映射，不把聊天前缀当协议字段。

| 服务名 | 连接与本地凭证名 | 提供方文档 |
| --- | --- | --- |
| travel_amap | HTTP，Key 在 URL 查询参数中；环境变量约定 `AMAP_MAPS_API_KEY` | [高德官方接入](https://lbs.amap.com/api/mcp-server/gettingstarted) |
| travel_rail | 本地 stdio，社区 `12306-mcp@0.3.10`，不需要铁路账号/证件 | [Joooook/12306-mcp](https://github.com/Joooook/12306-mcp) |
| travel_didi | HTTP，Key 在 URL 查询参数中；环境变量约定 `DIDI_MCP_KEY` | [滴滴官方接入与 Key 申请](https://mcp.didichuxing.com/api) |
| travel_hotel | HTTP，`Authorization: Bearer …`；环境变量约定 `ROLLINGGO_API_KEY` | [RollingGo 中国版接入及申请入口](https://github.com/RollingGo-AI/RollingGo-hotel-MCP-CN) |

三个 HTTP 服务不需要另外安装本地 Node MCP 服务。铁路才需要 Node/npm，运行层最低 Node 22.14，已有合适版本可直接复用。模板沿用项目固定的铁路版本，不能因 npx 启动失败自动改用 latest。

环境变量名称是本项目约定；是否自动加载 `.env` 取决于宿主，不能假定。优先由用户通过本地凭证界面或隐藏输入设置；不要让用户在聊天中粘贴 Key。不要用带 Key 的命令行启动或回显环境。URL 中的 Key 同样敏感，连接日志、错误和备份须脱敏。

## Codex

1. 安装完整目录至目标机确认可发现的 Skill 根目录。默认 `~/.agents/skills/travel-planner`；已有安装时选新版本目录或先备份，不覆盖真实数据。检查本机实际发现状态。
2. 以 [mcp-codex.example.toml](../config/mcp-codex.example.toml) 为四服务模板，将**选定的服务表**合并到实际的私有 Codex `config.toml`；默认用户级目录 `~/.codex`，尊重 `CODEX_HOME`。保留模型、其他 MCP、权限等原配置，备份同样按凭证保管。
3. 高德与滴滴 URL 的 `REPLACE_LOCALLY` 必须在私有配置中由本地安全流程替换，不能用 `${VAR}` 期待 TOML 自动展开。酒店的 `bearer_token_env_var` 则由 Codex 从进程环境读取，值不需要写入模板。
4. 铁路 `command/args` 只是便携示意。优先使用 `runtime.py mcp-config` 解析出的目标机启动方式，仅取铁路服务表。该生成器需要额外依赖，输出含本机 PATH，不可公开。Windows 使用绝对 `node.exe` 与 `npx-cli.js`，不能机械复制 macOS 的 npx 路径。
5. 凭证/路径就绪后仅将选定服务 `enabled` 改为 `true`，保留 `enabled_tools`。重载连接或新建聊天后检查真实工具；按验收指南做少量公开地点查询。

原 `config/mcp-servers.toml`、`runtime.py mcp-config` 与 `setup-amap --apply` 继续保留为 **Codex 高德/铁路辅助工具**，不负责 DeepSeek，也不是四服务导出。生成器只输出 TOML。高德 `setup-amap --transport http --prompt-key --apply` 需要 `requirements-amap-setup.txt`，会做业务检查，通过后备份合并高德表；只在确需配置 Codex 高德时使用。HTTP 方案不要求 Node。

官方来源：[Codex Skills](https://developers.openai.com/codex/skills)、[Codex MCP](https://developers.openai.com/codex/mcp)。供应商页面中关于 Codex 的示例可能过时；Codex 配置语法以 OpenAI Docs 为准。

## DeepSeek Harness（官方 deepseek-ai/deepseek-harness）

1. 默认可把完整 Skill 安装到 `~/.dsh/skills/travel-planner`，共享的 `~/.agents/skills/travel-planner` 也由默认文件提供方扫描。自定义 profile 可能关闭默认根目录，应检查其配置；不要把整个仓库嵌套放进 skills 根目录。
2. 复制 [mcp-deepseek.example.cordis.yml](../config/mcp-deepseek.example.cordis.yml) 到目标机私有位置；每个服务是独立的 `@deepseek-ai/dsh-mcp-client` 条目。确认所需环境变量在 **DSH 主进程**中存在；仅检查是否存在，不打印值。!!js 是 DSH 表达式语法，不交给 shell 执行。
3. HTTP 服务无需本地 Node 子服务。铁路的 command/args 按目标机重写：Windows 使用绝对 `node.exe`，args 依次为实际 `npx-cli.js`、`-y`、`12306-mcp@0.3.10`。不要使用带空格拼接的整条 shell 命令。DSH 对 stdio 会清理父环境中的常见密钥变量，若将来使用需 Key 的 stdio 服务，须显式在其 `config.env` 中传入必要变量。
4. `disabled: true` 是 Cordis 条目字段，改为 `false` 才会启用。`config` 中不要添加 Codex 专属的 `enabled_tools`、`bearer_token_env_var` 或 `env_vars`。
5. **工具权限单独处理。** 当前 DSH MCP 客户端字段不含 Codex 的工具白名单。按目标版本的宿主权限/工具过滤机制或经过审核的网关，只允许路由文件列出的查询工具；规则应默认拒绝新增工具。不能把 skill 的自然语言限制冒充宿主隔离。尤其滴滴可能同时暴露叫车、取消订单和司机定位工具；没有可验证的过滤措施时保持该连接停用，继续地图/酒店/铁路规划并报告打车缺口。不要为此临时部署未经审核的代理。酒店也只调用三项查询工具。
6. 用现有宿主加载 overlay；CLI/Web 示例（路径含空格时引号括起）：

   ```sh
   dsh web --patch "/absolute/private/travel-mcp.cordis.yml"
   ```

   不需要为安装 Skill 另开长期服务；已有 DSH 实例时按其方式合并配置并重载。持久化时将 overlay 的 insert 补丁合并进实际 `$DSH_HOME/profiles/<profile>/cordis.patch.yml`，或明确选择全局 `$DSH_HOME/cordis.patch.yml`；不要覆盖整个文件，不同时重复注册同名服务。
7. 发现成功后工具通常呈 `mcp__<serverName>__<tool>`。实际调用、错误、业务结果逐项验收；默认关闭断线自动重连以避免循环重试，网络瞬时问题最多再试一次。

官方来源：[MCP 客户端及字段](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)、[overlay 加载与持久化](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/mcp-memory.md)、[Skill 目录](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.zh.md)。此模板依据文档整理，未代表接收方 DSH/Windows/Linux 设备已实测通过。

## 其他 Harness 或远程容器

先查该宿主当前官方配置说明，复用服务 URL、stdio 参数和路由职责，转换为其支持的字段。没有统一的跨客户端 MCP 配置文件；不要把 DSH YAML 或 Codex TOML 强行套给其他应用。工具名可映射，输入 schema 以发现结果为准。

只有普通聊天、无法执行脚本或 MCP 的 agent 可以阅读规则和协助讨论，但不能宣称完成本地安装或实时查询。远程容器里的 home、磁盘和网络是远程环境，不能视作用户电脑的永久私有目录；先确认持久化和访问控制，未经确认只做不保存的讨论。
