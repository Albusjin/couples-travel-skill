# Windows / macOS 系统迁移与配置指南

本文对应运行层重构版，日期：2026-11-02。迁移操作系统不改变旅行规则、`schema_version=1.0` 或现有旅行修订。适用于仓库内使用及复制安装后的完整 Skill。本文路径示例应替换为目标机器的实际路径。

## 1. 共用内容与系统边界

```text
travel-planner/
├── SKILL.md                         # 唯一一份业务工作流
├── config/
│   ├── runtime.toml                 # 共用默认配置，含平台目录配置
│   ├── runtime.local.example.toml   # 本机覆盖模板，无凭证
│   ├── runtime.local.toml           # 用户自行创建，Git/安装器忽略
│   └── mcp-servers.toml             # 唯一一份 MCP 包、参数、超时、白名单
├── scripts/
│   ├── runtime.py                   # 共用 bootstrap/doctor/启动/生成配置入口
│   ├── travel_runtime/              # 配置解析、进程与 MCP 运行适配
│   ├── setup-amap.command           # macOS 薄启动器
│   ├── setup-amap.cmd               # Windows 薄启动器
│   ├── setup_amap.py                # 共用高德业务实测及条件写入流程
│   ├── travel.py                    # CLI 边界，读取已解析数据目录
│   ├── install.py                   # 复制安装边界，读取已解析安装目录
│   └── travel_planner/
│       ├── model.py                 # 共用模型/时区/结构检查
│       ├── budget.py                # 共用预算
│       ├── validation.py            # 共用业务约束
│       ├── store.py                 # 共用修订、锁、原子写入
│       └── render.py                # 共用视图
├── schemas/                         # 共用数据模型
└── requirements*.txt                # 共用依赖，含 Windows 所需 IANA tzdata
```

业务核心不依赖 `travel_runtime`，不判断 Windows/macOS，也不读取 MCP 运行配置。CLI/安装工具在边界解析配置后传入参数。模型加载显式使用 UTF-8，避免 Windows 默认编码影响含中文的 Schema。

macOS/Windows 的区别仅为初始解释器发现、默认目录、虚拟环境解释器位置及原生子进程启动方式。Windows 用 `node.exe` 执行 `npx-cli.js`，不把 `npx.cmd` 交给原生进程 API；路径始终作为独立参数，不拼接 shell 命令。macOS 默认直接使用已发现的 npx，也支持显式 `npx_cli`。二者使用同一包版本、白名单和高德检查流程。

## 2. 配置来源与优先级

从低到高：

1. `config/runtime.toml` 共用默认值。
2. 该文件 `platforms.darwin` / `platforms.win32` / `platforms.linux` 中当前系统的默认值。
3. 本机覆盖文件：`runtime.py --runtime-config <路径>` 指定的文件优先，否则使用 `TRAVEL_PLANNER_RUNTIME_CONFIG`，再否则自动寻找 Skill 内 `config/runtime.local.toml`。只选择一份覆盖文件，不叠加多份。
4. 下表列出的环境变量覆盖字段。
5. 业务 CLI 的 `--data-dir`、安装器的 `--destination`、高德辅助工具的 `--config` 等显式参数。

显式指定的配置文件不存在、TOML 不合法、未知字段或类型错误都会报错，避免静默退回旧路径。`--runtime-config` 是运行配置，`setup_amap.py --config` 是准备写入的 **Codex 配置文件**，两者用途不同。

配置文件支持 `{home}`、`{skill_root}`、`{local_app_data}` 三个路径占位符，支持开头的 `~`。不执行 shell 展开，不支持 `${VAR}`、`%VAR%` 或命令替换。相对路径以本机配置文件所在目录为基准；未选本机文件时以 Skill 根目录为基准。环境变量中的路径建议全部使用绝对路径，避免迁移后歧义。

TOML Windows 路径建议写 `"D:/Private/TravelPlanner"`，或用单引号 `'D:\Private\TravelPlanner'`，不必在双引号字符串里手动处理反斜杠。带空格和中文的路径作为整体字符串填写。

## 3. 迁移时逐项检查的配置

| 配置字段 | 环境变量覆盖 | 默认值/语义 | 迁移时的处理 |
| --- | --- | --- | --- |
| `paths.codex_home` | `CODEX_HOME` | `{home}/.codex` | 自定义 Codex 目录时改为目标机目录；实际 MCP 文件为其中的 `config.toml` |
| `paths.skill_destination` | `TRAVEL_PLANNER_SKILL_DESTINATION` | `{home}/.agents/skills/travel-planner` | 使用自定义 Skill 发现目录时调整；只影响安装器，不会移动当前代码 |
| `paths.venv_dir` | `TRAVEL_PLANNER_VENV_DIR` | 见下表 | 重新创建目标系统虚拟环境；不能复制旧 venv |
| `paths.data_dir` | `TRAVEL_PLANNER_DATA_DIR` | 空，必须由用户指定 | 指向迁移后的仓库外私有数据目录；不要放在 Git 仓库内 |
| `executables.python` | `TRAVEL_PLANNER_PYTHON` | 空，使用启动入口的 `sys.executable` | 自定义解释器时填写目标机 Python **可执行文件**，不能填写 `py -3` 这样的整条命令 |
| `executables.node` | `TRAVEL_PLANNER_NODE` | 空，从 PATH 查找 node | GUI 找不到 node、Node 来自版本管理器时，填写实际绝对路径 |
| `executables.npx` | `TRAVEL_PLANNER_NPX` | 空，从 PATH 查找 npx | 填写目标机实际 npx 路径；Windows 可以发现 npx.cmd，运行层负责转换 |
| `executables.npx_cli` | `TRAVEL_PLANNER_NPX_CLI` | 空，按 Node/npm 安装位置推导 | npm 来自自定义/分离安装时指定真实 `npm/bin/npx-cli.js`；显式设置时两平台都用 node 执行它 |
| `[environment]` | 同名系统环境变量作为基础，本节覆盖它们 | 默认 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` | 按机器设置代理、CA 文件路径等，不放 API Key；代理和证书文件不能沿用旧机路径 |
| 本机配置文件路径 | `TRAVEL_PLANNER_RUNTIME_CONFIG` 或 `--runtime-config` | Skill 内 `config/runtime.local.toml`（可不存在） | 建议在每台机器独立维护；不复制旧路径，不提交到仓库 |

| 系统 | 默认依赖环境 | 环境内的 Python |
| --- | --- | --- |
| macOS | `~/Library/Application Support/TravelPlanner/amap-setup-venv` | `bin/python` |
| Windows | `%LOCALAPPDATA%\TravelPlanner\amap-setup-venv` | `Scripts\python.exe` |
| Linux（开发与测试） | `~/.local/share/TravelPlanner/amap-setup-venv` | `bin/python` |

Windows 缺少 LOCALAPPDATA 时运行层使用用户目录下 `AppData/Local`；特殊账号或受管理设备建议明确设置 `paths.venv_dir`。

`executables.python` 决定创建虚拟环境的初始解释器。正常 `run` / `setup-amap` 优先使用已有的 `paths.venv_dir` 环境，不存在时才使用初始解释器。更换 Python 主次版本时选择全新的 `venv_dir` 并重新 bootstrap，避免继续使用旧 venv。

运行层不会代替修改系统 PATH、安装 Node、设置 Windows ACL 或为 GUI 注入登录环境。`doctor` 会报告解析后的路径、离线版本及环境变量名称，不打印环境变量值，也不访问服务商。没有虚拟环境、Node 或 npm 时相应检查为失败，退出码为 2；仅使用核心时可根据报告忽略 Node 项。`bootstrap --core-only` 无需 Node。

## 4. 两种系统的首次配置示例

从完整 Skill 的根目录执行，需先安装 Python 3.11+；需要 MCP 时另装 Node.js 24 LTS（最低 22.14）。

macOS 终端：

```sh
cp config/runtime.local.example.toml config/runtime.local.toml
```

编辑 `config/runtime.local.toml`，例如：

```toml
[paths]
data_dir = "{home}/Private/TravelPlanner/data"
# codex_home = "{home}/.codex"

[executables]
# 以下是自定义示意，先检查本机实际安装位置再启用。
# python = "/opt/homebrew/bin/python3.13"
# node = "/opt/homebrew/bin/node"
# npx = "/opt/homebrew/bin/npx"
```

Windows PowerShell：

```powershell
Copy-Item config/runtime.local.example.toml config/runtime.local.toml
```

编辑同一个格式的配置，例如：

```toml
[paths]
data_dir = "{home}/Private/TravelPlanner/data"
# venv_dir = "D:/Tools/TravelPlanner/venv"

[executables]
# node = "C:/Program Files/nodejs/node.exe"
# npx = "C:/Program Files/nodejs/npx.cmd"
# npx_cli = "C:/Program Files/nodejs/node_modules/npm/bin/npx-cli.js"
```

完成配置后：

| 操作 | macOS 终端 | Windows PowerShell |
| --- | --- | --- |
| 安装共用依赖 | `python3 scripts/runtime.py bootstrap` | `py -3 scripts/runtime.py bootstrap` |
| 离线诊断 | `python3 scripts/runtime.py doctor` | `py -3 scripts/runtime.py doctor` |
| 校验虚构样例 | `python3 scripts/runtime.py run validate --input examples/demo-trip.json` | `py -3 scripts/runtime.py run validate --input examples/demo-trip.json` |
| 查看业务命令 | `python3 scripts/runtime.py run --help` | `py -3 scripts/runtime.py run --help` |
| 输出本机 MCP TOML | `python3 scripts/runtime.py mcp-config` | `py -3 scripts/runtime.py mcp-config` |
| 高德只测试 | `python3 scripts/runtime.py setup-amap --prompt-key` | `py -3 scripts/runtime.py setup-amap --prompt-key` |
| 测试通过后合并高德配置 | `python3 scripts/runtime.py setup-amap --apply --prompt-key` | `py -3 scripts/runtime.py setup-amap --apply --prompt-key` |

Windows 没安装 Python launcher 时可以用 `python` 代替 `py -3`，先用 `python --version` 检查版本。

外部配置文件示例：

```sh
python3 scripts/runtime.py --runtime-config /absolute/private/runtime.toml run read trip-example
```

全局 `--runtime-config` 放在 `run`/`bootstrap` 等命令前；该路径会传给子进程。业务参数保持原顺序传递，显式数据目录示例：`runtime.py run --data-dir <绝对私有目录> read trip-example`。这些数据命令读取已有资料，不会自动创建真实旅行或改变长期偏好。

双击/快捷启动继续可用：Mac 运行 `bash scripts/setup-amap.command`，Windows 运行 `scripts\setup-amap.cmd`。两个薄启动器都转交 `runtime.py setup-amap --bootstrap --apply --prompt-key`，每次本机重新输入 Key；`TRAVEL_PLANNER_PYTHON` 可以指定启动器的初始 Python。要给薄启动器选外部配置，设置 `TRAVEL_PLANNER_RUNTIME_CONFIG`。高德真实测试步骤见 [MCP 接入指南](mcp-setup.md)。

## 5. MCP 哪些共用，哪些必须重新生成

`config/mcp-servers.toml` 是两系统的唯一服务定义源，包含高德与默认停用的铁路服务。修改包版本、超时或工具白名单只改此文件。原 `examples/mcp-config.macOS.toml` 已由该共用定义取代，不再分别维护 macOS/Windows 模板。

`runtime.py mcp-config` 根据共用定义和当前机器路径生成 TOML，**只输出，不写入** `~/.codex/config.toml`。先 bootstrap 安装生成器所需 tomlkit。输出不包含高德 Key，使用 `env_vars=["AMAP_MAPS_API_KEY"]`，但包含本机 PATH 和配置的代理/证书等环境值，保存在本机即可。手工合并时只合并目标服务表，保留其他模型/项目/服务配置，避免同名表重复。

高德辅助工具也从同一份定义生成实际测试进程和写入的服务表。仍须真实杭州地点、道路路线和近期天气检查全通过，带 `--apply` 才能备份并合并 `travel_amap`，不会自动启用铁路。测试失败、模拟结果、配置并发修改、文件写入失败的原有保护保持有效。高德辅助工具的 `--config <路径>` 可单次覆盖 Codex 配置目标。

| 项目 | 可复用 | 目标机器必须检查 |
| --- | --- | --- |
| MCP 名称、包版本、白名单、超时 | 共用服务定义 | 变更供应商版本后重新验收 |
| command / args 前缀 / PATH | 由运行层生成 | 重建目标机 Node/npm 路径，不复制 Mac/Windows 绝对路径 |
| Key/AK | 不进入共用文件 | 在目标机本地输入/配置；推荐每台机器单独 Key |
| `AMAP_MAPS_API_KEY` | 环境变量名称共用 | GUI App 是否确实继承；或者用辅助工具写本机私有 env 表 |
| `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` | 配置字段名称共用 | 目标机端口、网络策略、GUI 继承；必要时填入本机 `[environment]` |
| `NODE_EXTRA_CA_CERTS` / `SSL_CERT_FILE` / `SSL_CERT_DIR` | 配置字段名称共用 | 证书文件是否存在，指向目标机信任证书；不关闭 TLS 验证 |
| 文件权限 | 应用流程共用 | Mac POSIX 权限与 Windows NTFS ACL 分别核实；0600 不能当作 Windows ACL 保证 |

不要把 Key 放进 `runtime.local.toml`、公共 MCP 定义、启动参数或旅行 JSON。高德辅助工具直接调用时仍支持原有环境变量 Key；两个快捷启动器默认强制本机隐藏输入。Codex 配置备份也可能含 Key，需要按私有文件处理。生成配置不表示 Desktop 已加载，完全退出并重新打开 App 后，仍须在新聊天检查工具并做只读真实查询。

## 6. 从旧系统迁移到新系统

1. **停止写入并备份。** 结束两个设备上的旅行修改进程。离线备份完整私有数据目录、旧版安装包和本机 Codex 配置。记录当前旅行 revision 与输出状态；不要在同步尚未完成时复制。
2. **获取同一版本代码。** 在目标机 clone/pull 仓库，或用 `scripts/install.py --destination <新目录>` 复制完整 Skill。安装器拒绝覆盖已有目标，并排除 `*.local.toml`，本机配置需重新建立。如果希望继续使用同机设置，备份后人工将合适字段填入新安装；不要假设安装器会迁移配置。
3. **安装目标系统的 Python/Node。** 不复制 `.venv`、旧系统 site-packages、node_modules 或 npm 缓存。初始 Python 命令不同由启动方式处理，业务脚本保持共用。
4. **新建本机配置。** 按第 3 节逐项填写，尤其是 `data_dir`、自定义 Codex 目录、Python/Node/npm 路径、代理和证书。默认目录适用时不必填全部字段。检查是否遗留 `TRAVEL_PLANNER_*` 或 `CODEX_HOME` 环境变量覆盖了文件中的新值。
5. **迁移完整数据。** 将备份复制到目标机用户授权的仓库外私有目录，配置 `paths.data_dir`。保留所有 HEAD、revisions、pending、profiles、change sets 和派生文件及原目录关系；不要只复制最新导出，不修改版本号或 HEAD 校验和。残留锁先核实已无写入再手工处理。操作系统迁移不需要模型迁移；未知 schema 仍按既有机制拒绝写入，不能改个字符串冒充升级。
6. **重建环境并离线验证。** 运行 bootstrap、doctor 和虚构样例校验。用 `run read <trip_id>`、`run output-status <trip_id>` 核对迁移前后的 revision 和输出状态；不要用 init 覆盖已有旅行。必要时另用 `run render <trip_id>` 重建派生输出。
7. **重建 MCP。** 重新生成目标机配置或运行高德真实检查后合并，保留其他 Codex 配置。Key 本地输入，不从聊天转发。铁路保持停用，直到目标网络实测通过。
8. **完成 Desktop 验收。** 完全退出重开 Codex，确认 Skill 与工具可见，按 MCP 指南执行真实只读检查。确认新设备数据、版本与查询都正常后，再决定旧设备的保留策略；不要在这一步自动删除旧数据或旧配置。

本重构不提供双机实时同步或合并冲突功能。两台机器不能各自修改后直接覆盖同一旅行目录；应先确定当前唯一写入端，再离线迁移。数据字段里的外部文件入口或用户自行保存的绝对路径也需要逐项检查，MCP/运行配置更新不会改写旅行事实或第三方订单。

## 7. 验证与回滚

仓库根目录执行 `python -m unittest discover -s tests -v`。CI 使用 Ubuntu/macOS/Windows × Python 3.11/3.13，统一安装 Node 24 和同一套依赖，运行全量测试。测试覆盖配置优先级、空格/中文路径、参数透传、独立复制安装、本机配置排除、共用服务定义、Windows npm 适配及原有业务规则。

当前云端执行的是 Linux 自动化与离线 Node/npm 检查；新增 CI 的定义不等于其远端已经运行成功，也不等于两台用户设备的 Key、GUI 环境或真实查询已验收。目标机需按第 6 节完成实际验证。

回滚时先停止新设备写入，保留新产生的资料和配置备份，再切换回旧安装与其配套本机配置。高德配置写入前会产生 `config.toml.backup-*`；恢复前检查备份之后其他服务是否被修改，优先只恢复相关 MCP 表。需要恢复旅行内容时使用现有 restore/propose/commit 流程保留修订历史，不直接覆盖唯一数据副本。没有真实执行过高德 `--apply` 的迁移，仅需修正运行配置或切回原安装即可。
