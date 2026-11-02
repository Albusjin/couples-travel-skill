# MCP 接入、故障处理与验收

新机器安装先读 [AGENT_HANDOFF.md](../AGENT_HANDOFF.md)；宿主配置和凭证处理见 [harness-setup.md](harness-setup.md)。日常规划阅读 [调用与数据映射](mcp-usage.md)，按 [路由白名单](../config/mcp-routing.toml) 与当前可见工具交集调用。本文件不是发布者部署的导出，也不表示任何接收方已经配置成功。

## 服务和配置边界

高德、滴滴、RollingGo 酒店使用官方 HTTP，铁路为社区 12306-mcp@0.3.10 本地 stdio。三个 HTTP 服务无需额外本地 Node 进程。铁路需目标机 Node/npm、正确启动路径及访问铁路网站的网络。现有服务可复用，不重复安装。

config/mcp-codex.example.toml 与 config/mcp-deepseek.example.cordis.yml 是四服务无密钥模板，全部默认停用；目标宿主授权后选择启用。DSH 模板不含工具过滤，按宿主权限或审核网关执行查询白名单；尤其滴滴若无法过滤交易/定位工具则保持停用。

旧 config/mcp-servers.toml 和 runtime.py mcp-config 仅处理 Codex 高德/铁路，不是四服务生成器。mcp-config --transport http 只输出未启用且无 Key 的高德模板；stdio 输出可能含本机 PATH/代理环境，不公开分享。setup-amap --apply 仅合并 Codex 高德配置，不能用于其他 Harness。

## 定位故障阶段

1. **工具可见吗？** 检查目标宿主连接或新聊天，不把不可见解释为无房/无票。不打印完整配置、带 Key URL、Authorization 或备份。
2. **连接成功吗？** 进程、握手、工具发现只证明协议。铁路还受 cwd、绝对 Node/npm 路径和网络影响。不复制其他电脑的绝对路径。
3. **业务成功吗？** 区分鉴权、配额、网络、空结果和业务拒绝。瞬时网络最多再试一次，鉴权/配额引导用户本地控制台处理，不索要聊天中的 Key。
4. **条件相符吗？** 核对 POI/入口、车站/乘车日、酒店日期/房型/人数。条件错误不能标 verified。缺某项时保留独立可继续的规划。

## 少量只读业务验收

新增连接或变更供应商/版本/权限后执行，日常无需反复全测。使用公开地点和匿名条件：

- 高德：明确公共 POI 搜索/详情、同坐标体系路线及近期天气；检查 m/s 到 km/min 换算、实际覆盖日期、分店与入口。地图不证明票务可售或充电空闲。
- 铁路：工具取当前上海日期，选择当前可查日，先站码再直达/需要时中转。逐条核对实际站点和本段乘车日；中转核对等待、费用和余票。目标日未排班时参考日只作参考，不通过目标日硬约束。
- 滴滴：先用其地点搜索核对公共上下车点，再一次预估；只记录真实字段与缺口。不叫车、不保证有车、不把当前价说成未来锁价。无法落实工具权限时不启用该连接。
- 酒店：明确未来入离店、两成人一间房；标签/搜索后选择一间查详情。核对房型、大床、库存/申请状态、价税范围、早餐和退改。isOnRequest=true 不是确认库存，搜索价不是所选房型总价。

保存服务/工具、匿名条件、查询时间、字段覆盖、失败阶段及限定结论到用户私有目录。不记录凭证，不创建订单、锁价、支付或发布地图。工具发现、空结果或字段缺失分别报告；缺口仍为 unknown，不编造完整可用性。

## 目标机 Codex 高德辅助配置（可选）

仅在确需配置 Codex 高德时，复用已有 Python 环境，缺辅助依赖才安装 requirements-amap-setup.txt。用户本地创建 Web 服务 Key 后隐藏输入：

```sh
python3 scripts/runtime.py setup-amap --transport http --prompt-key --apply
```

从安装后的 Skill 根目录执行，Python 3.11+；Windows 可用 py -3。HTTP 不需要 Node。省略 --apply 只测试；工具会核验杭州公共地点/路线/近期天气，通过才备份合并高德服务表，保留其他配置。报告/错误脱敏，备份按含凭证文件保管，写入后仍须确认目标聊天实际加载。双击启动器默认 stdio 且带 --apply，不用来做通用环境探测。

官方来源：[高德](https://lbs.amap.com/api/mcp-server/gettingstarted)、[Key 创建](https://lbs.amap.com/api/mcp-server/create-project-and-key)、[社区铁路](https://github.com/Joooook/12306-mcp)、[滴滴](https://mcp.didichuxing.com/api)、[RollingGo 中国版](https://github.com/RollingGo-AI/RollingGo-hotel-MCP-CN)。收费、额度、授权与字段以实际控制台和返回为准，不继承免费或无限调用承诺。
