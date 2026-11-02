# 数据契约与 CLI

运行 `python3 <skill目录>/scripts/travel.py --help`。命令返回 UTF-8 JSON：成功为 `{"ok":true,"result":…}`，错误为 `{"ok":false,"error":…}`；结构/事务错误退出码 2。`validate` 的错误在 `result.errors`；规划问题不以非零退出码表示，必须检查 `can_confirm` 与三态列表。

## 数据

权威结构为 [JSON Schema](../schemas/model-v1.schema.json)，根对象是 Trip，其他实体位于 `$defs`。完整虚构文档见 [demo-trip.json](../examples/demo-trip.json)。未知值使用 null/unknown，不省略必需字段，不设置虚假默认数据。

- Trip：`schema_version="1.0"`、`revision`、`data_mode=real|mock`、`timezone`、request、只读偏好快照、实体集合、`cost_quote_ids` 与 `cost_scope_reviewed`。快照由初始化时的已确认档案产生，未选档案则为空；PRD 默认规则独立于长期档案。
- 请求：origin/destinations 是 place ID，date_window 保存 start/end/flexible；travelers 仅非敏感标识。固定日期不擅自改动，灵活窗口在详细确认前选定具体组合。`overrides` 保存本次条件；`hotel_room_type` 和 `hotel_rooms` 为脚本识别的房型覆盖，其他自然语言条件以约束/说明补充。
- 所有实体及 traveler ID 在旅行内全局唯一：1–80 位字母、数字、`-`、`_`。引用不能悬空或重复。时间为含偏移量的 ISO 8601，地点用稳定 ID，距离为道路或步行距离，未知用 null。
- 候选实体用 `proposal_id` 关联，null 表示共享安排；选择方案后仅相符及共享的交通、酒店和车辆参与当前规划。day 引用选中活动与路线，不把其他候选活动塞入日程。
- 每个 Proposal 独立保存 `cost_scope_reviewed`，候选对比也检查费用类别覆盖，不能用单项酒店报价冒充完整旅行费用。酒店的 `policies_verified` 表示已通过来源核验房型、双人入住、最晚到店及退改规则；它与房价核验独立。
- 路线保存 depart_at、duration_minutes、evidence、buffers、source_ids、导航入口和 depends_on_ids。固定交通用 transport_id 关联，其他路线为 null；关联段必须保留交通的起终点和出发时刻，不能通过改路线绕过票务锁定。预计抵达由耗时与缓冲计算；活动弹性时间也要给可校验的时间范围。day 的 hotel_route_id 必须属于当天 route_ids，实际终点必须是酒店。
- Quote 的 `unit_amount_minor * quantity + components` 为已知金额；components 按整个数量计。`conditions` 是实际报价条件，`expected_conditions` 是本次期望条件，二者需匹配。所有报价需包含 `trip_start`、`trip_end`、`travelers`；酒店附 check_in/check_out/rooms/room_type；车辆附 pickup_at/dropoff_at/drivers/transmission/pickup_place_id/dropoff_place_id。脚本还会与当前旅行实体比对，不能通过同步填写错误条件“绕过”过期检测。
- 报价状态、费用完整性和真实支付分别保存。零元只用于确有依据的免费/不适用项。`cost_quote_ids` 是本次全部适用费用的去重清单，不能因为某项价格未知而从清单删除。
- SourceRecord 保存 kind/provider/queried_at/conditions/url/reliable/note。mock 只能验证 mock 旅行中的逻辑；真实规划不接受 mock 作为核实证据。可靠性由 Codex 基于实际资料判断，不能仅因字段填写为 true 就宣称实际能力通过。
- Decision 保存 kind、target_ids、summary、confirmed_by、confirmed_at、change_id、details。它是用户明确表达的记录；脚本不鉴别用户身份，也不能替代真实确认。已有记录不能删改。

## 命令

所有持久化命令使用 `--data-dir /absolute/private/path`，须放在子命令前。数据路径不提供默认值。输入 JSON 和确认文件也应写在该私有目录；不要把真实候选复制进公开 examples。

| 命令 | 用途 |
| --- | --- |
| `init <trip_id> --title … [--profile-id …] [--mock]` | 新建，不覆盖已存在旅行；mock 与 real 创建后不能互换 |
| `read <trip_id> [--revision N]` | 当前有效数据或指定历史修订 |
| `validate --input candidate.json` | 不写文件，检查结构、引用、规划规则与预算 |
| `propose <trip_id> --input candidate.json --reason … [--scope day-2 …]` | 基于当前 revision 的完整候选，返回 change_id、影响、所需确认和费用差异 |
| `commit <trip_id> <change_id> [--decisions decisions.json] [--no-render]` | 确认绑定具体 change_id；保存新修订，默认生成三份 Markdown |
| `compare <trip_id> <old_revision> [--new-revision N]` | 比较实体变化及费用；不完整差异标明仅已知金额 |
| `restore <trip_id> <revision> [--scope …]` | 生成恢复候选，仍需 commit |
| `render <trip_id>` / `output-status <trip_id>` | 生成同版本视图 / 判断输出是否对应当前版本 |
| `profile-read <profile_id>` | 读取已确认长期档案 |
| `profile-propose <profile_id> --input values.json --expected-revision N` | 新档案 N=0；返回逐项新旧值与后续影响 |
| `profile-commit <profile_id> <change_id> --decisions decisions.json` | 每项确认后保存长期档案新版本 |
| `query <capability> --conditions conditions.json [--response response.json] [--mock]` | 无存储要求；用户资料/模拟适配接口，省略 response 返回 unavailable |

## 修改与确认示例

先 `read` 当前版，用完整当前数据构造候选，保留 revision 和既有记录；改变 status 或实体后 `validate`，再 `propose`。`--scope` 使用 day ID；共享酒店、报价或依赖影响范围可能超出该天，返回 expand_scope 所需确认。没有 scope 表示用户本次要求针对整趟旅行，不能为了绕过范围确认而擅自扩大 scope。

针对返回的具体变更，在用户明确确认后保存以下数组（ID 需唯一，不能照抄示例当作真实确认）：

```json
[
  {
    "id": "decision-user-unique",
    "kind": "unlock",
    "target_ids": ["activity-2"],
    "summary": "用户确认变更该锁定活动及已展示的影响",
    "confirmed_by": "用户",
    "confirmed_at": "2030-05-01T12:00:00+08:00",
    "change_id": "change-实际返回的ID",
    "details": {}
  }
]
```

required_approvals 列出的每个 kind/target 均须匹配。`confirmed` 要求 plan_confirmation；待核实费用还需 accept_unknown_prices；改变方案需要 selection；扩大日期范围需要 expand_scope。数据提交成功后重试同一候选会版本冲突，应先 read，不能重复消费/预订记录。

酒店例外在构建候选时记录用户已确认的 `hotel_exception`，target_ids 为 day ID，details 为 `{"date":"2030-05-12","no_hotel":true}`，或 `{"date":"2030-05-10","arrival_before":"2030-05-11T01:00:00+08:00"}`；day.hotel_exception_decision_id 引用它。首次录入的例外可用 change_id=null，因为用户确认发生于候选生成之前；summary 必须记录具体适用场景。不存在自动豁免。

长期偏好确认 kind=profile_update，target_ids 为每个稳定偏好键（建议英文 snake_case），details.items 是逐项映射，必须完整包含 profile-propose 返回的该项 `{key,old,new,removed}`；summary 说明用户同意其长期影响。不能把单次旅行和健康背景放进档案。

## 存储与扩展

私有目录下按 `trip-<id>` / `profile-<id>` 分隔，包含 HEAD.json、revisions、pending；旅行另有 outputs 和带 revision 的 OUTPUTS.json。revisions 内每个 bundle 包含 document 与 change（原因、前后版本、修改、影响和费用差异）。HEAD 保存 bundle 哈希；历史只追加，异常中断可能产生修订跳号。每次渲染均保留独立生成记录，同一 revision 的报价随时间过期时也可重新生成；output-status 同时核对数据版本、文件完整性及当前校验结果，旧输出不会被重新标为最新。

外部适配协议为 CapabilityRequest(capability, conditions) → CapabilityResult(status, data_mode, queried_at, conditions, records, sources, failure_reason, limitations)。能力包括 maps/rail/hotels/rental/energy/attractions/weather。当前 ProvidedDataAdapter 只读取用户提供/模拟响应，不做网络请求，不自动把 records 导入主数据或提高证据等级。

响应文件为 `{"conditions":{…},"records":[…],"sources":[…]}`；条件不匹配返回 unavailable，记录或来源缺失返回 partial。未来供应商适配器需实现同一只读协议，并独立验证真实覆盖、费用、权限、时效和失败行为。
