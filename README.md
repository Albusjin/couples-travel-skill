# Couples Travel Skill

面向 Codex Desktop 的情侣双人自由行 Skill。已实现 V1 核心：自然语言工作流、结构化数据、约束校验、预算、确认/锁定、不可变版本及 Markdown 攻略、预算表和路线索引。实际理解与研究由 Codex 按 Skill 执行，脚本负责确定性校验和存储。

- [Travel Planner Skill 软件需求规格说明书 V1.0](docs/Travel-Planner-PRD-v1.0.md)：用户确认的正式需求基线。
- [实施补充与待决事项](docs/implementation-notes-v1.md)：实现建议、验证边界和待决问题，不修改正式基线。
- [设计与已确认决定](docs/design-v1.md)：架构、数据接口、事务和需求追踪。
- [Skill 安装与使用](skills/travel-planner/README.md)：Python 3.11+，复制安装、私有目录配置、命令及虚构演示。
- [验收追踪](docs/acceptance-v1.md)：AC-01–28 的自动化、对话与实际工具验收边界。
- [外部能力记录](docs/capability-verification-v1.md)：实际查询与模拟测试分别记录。
- [完整 MCP 选型清单](docs/mcp-selection-v1.md)：覆盖地图、铁路、酒店、网页核验、可选搜索及租车/补能缺口。
- [macOS / Windows MCP 接入指南](skills/travel-planner/references/mcp-setup.md)：候选筛选、真实协议实测、双平台启动工具、Key 设置和本机验收步骤。

快速验证（不保存真实数据）：

```sh
python3 -m pip install -r skills/travel-planner/requirements-amap-setup.txt
python3 -m unittest discover -s tests -v
python3 skills/travel-planner/scripts/travel.py validate --input skills/travel-planner/examples/demo-trip.json
```

本仓库公开，请勿提交真实行程、订单、健康信息、凭证等个人隐私。真实资料须在实际 Desktop 首用时指定仓库外的私有目录；未配置前不保存。云工作目录不默认视为私有永久存储。

高德/百度 MCP 已在云开发环境完成真实进程协议测试。用户本机回传的高德 v4 报告显示 `data_mode=live`、`passed=true`，覆盖辅助工具限定的杭州公共地点、驾车/步行路线和近期天气检查；证据来源是用户截图，完整结果未在云端复核。配置写入和 Codex 内加载仍待确认。社区 12306 初始化被当前环境网络代理拒绝，暂不默认启用；实时酒店、铁路和租车尚无业务验收通过结论。Word/PDF、手机执行版、网站和自动交易不属于首轮交付；旅行示例全部虚构。
