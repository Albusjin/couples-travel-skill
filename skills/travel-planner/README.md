# Travel Planner Skill V1.0

可复制安装的 Codex Desktop Skill。Codex 负责中文需求理解和研究，Python 核心负责数据、校验、预算、版本与 Markdown。真实查询可由 Codex 编排另行配置的 MCP；本地 CLI 不内置供应商 SDK。核心无需账号；地图服务需本机 Key/AK。无自动下单、支付或发布。

已筛选高德官方 MCP（首选）、百度官方 MCP（备用）及社区 12306 MCP（待本机复测）。高德/百度真实进程的协议与工具发现已部分通过；用户本机高德 v4 截图显示限定的地点、驾车/步行和近期天气测试通过，配置写入与 Codex 内加载仍待确认。百度业务、真实房价及租车库存尚无验收通过结论。详见 [macOS / Windows MCP 配置与实测指南](references/mcp-setup.md) 和 [无凭证配置模板](examples/mcp-config.macOS.toml)。

高德本机辅助工具 `scripts/setup_amap.py --apply` 可在用户完成开发者注册并创建 Web 服务 Key 后，先执行真实地点/路线/天气测试，通过后才备份并合并 Codex 配置。需额外安装 `requirements-amap-setup.txt`；Key 在本机输入，步骤见接入指南。

已提供 macOS 启动器 `scripts/setup-amap.command` 和 Windows 启动器 `scripts/setup-amap.cmd`；两者共用 Python 校验与条件写入逻辑，使用各自用户目录下的独立依赖环境。Windows 适配原生 node.exe + npx-cli.js 启动，目录含空格也按独立参数处理。

## 安装

需要 Python 3.11+。从项目根目录执行：

```sh
python3 skills/travel-planner/scripts/install.py
```

默认安装到 `~/.agents/skills/travel-planner`；也可用 `--destination /absolute/path/to/skills/travel-planner` 选择 Codex 支持的 Skill 目录。目标存在时拒绝覆盖，更新时请备份旧安装并选新目标，不能删除真实旅行目录。Windows 使用 `python` 替代 `python3`。

在自己的 Python 环境安装依赖（建议使用虚拟环境）：

```sh
python3 -m venv /absolute/path/to/travel-planner-venv
/absolute/path/to/travel-planner-venv/bin/python -m pip install -r /absolute/path/to/installed/travel-planner/requirements.txt
```

Windows 虚拟环境解释器位于 `Scripts/python.exe`。让 Codex 在执行 Skill 脚本时使用该解释器；重新打开 Codex Desktop 会话以发现 Skill。可输入“使用 $travel-planner 帮我规划旅行”。这里提供安装包与脚本，不代表已在当前机器用户级目录激活或完成 Desktop UI 验收。

## 首次真实使用

用户选择仓库外的私有目录，例如自己电脑上受访问控制且有备份的目录，使用 `--data-dir` 或为当前会话设置 `TRAVEL_PLANNER_DATA_DIR`。脚本没有默认旅行数据路径，不把云端工作目录视为永久私有存储，不允许把数据写进 Git 仓库。

```sh
python3 /absolute/path/to/installed/travel-planner/scripts/travel.py --data-dir /absolute/private/travel-data init trip-example --title "旅行草稿"
```

所有其他命令及候选/确认格式见 [数据与命令](references/data-and-cli.md)。常规使用只需自然语言；由 Codex 在私有目录准备输入文件。真实数据与安装包、公开仓库始终分开。

## 无真实个人信息的演示

在仓库根目录校验示例，不写数据：

```sh
python3 skills/travel-planner/scripts/travel.py validate --input skills/travel-planner/examples/demo-trip.json
```

以下脚本创建**虚构**需求，经过候选、选择、详细规划、模拟确认、锁定、第二天局部修改，再输出攻略、预算与路线。它生成的确认仅是测试夹具，不能用于实际用户授权。请选择全新的仓库外临时目录：

```sh
python3 skills/travel-planner/examples/walkthrough.py --data-dir /tmp/travel-planner-demo-unique
```

测试：`python3 -m unittest discover -s tests -v`（从项目根目录执行）。样例含 `example.invalid` 占位入口，不可用于导航；所有视图均明确标为模拟。

## 恢复与限制

- `propose` 只保存候选；`commit` 写新修订，冲突时重新读取，不能强行覆盖。`restore` 生成恢复候选，保留当前订单、支付和确认事实；结构不兼容时明确拒绝。
- 写入中断可能留下未被 HEAD 引用的快照。它们保留原编号，后续提交跳号，不覆盖历史。锁目录残留时，确认已无写入进程后手工移除对应空锁目录，不能自动抢锁。
- HEAD 是唯一提交点。遇到磁盘/系统故障需先 `read` 核验实际当前版本再重试。离线备份应覆盖完整私有数据目录；脚本不会自动删除快照、候选或备份。
- `commit` 成功但渲染失败会返回 `output_error`；数据保持新版本，旧输出仍是历史。用 `output-status` 检查版本，用 `render` 重试。
- 未知 `schema_version` 可读取原始历史以诊断，不能提交或渲染。当前只有 1.0，无旧版迁移器；未来迁移须显式运行、备份原件并生成新修订，不能只改版本字符串。
- 规则检查不代替真实驾驶安全评估或实际供应商核验。对话理解仍依赖 Codex；无真实外部工具时，真实硬约束可能保持未知，因此不能确认整份计划。
