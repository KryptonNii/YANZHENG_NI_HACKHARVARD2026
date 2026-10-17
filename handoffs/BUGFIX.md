# 重构与缺陷修复交接（BUGFIX）

日期：2026-10-17。分支：`main-k328fj`（起点 = `origin/main` 的 `fd0bb68`）。

## 做法

- 范围：engine、contracts、api（不含 `benchmark/`、`advice/`）、web（不含 `PeerMirror.tsx`、`NextLever.tsx`、`ScenarioPage.tsx`）、validation、science。
- 先做一遍只读审查（read-only review）。它用真实的 `create_app(Settings(demo_offline=True))`、真实引擎（engine）和 A7 合规层，把离线主路径完整跑了一遍：导入 → AI 草稿审阅 → 保存设计 → 杠杆/预报/供药 → 提交 → 审批与电子签名（e-signature）→ 审计与导出 → 指挥中心。主路径在服务器端全部能走通，不需要任何绕路操作。
- 只保留四类改动：**已复现的缺陷（defect）**、**已经分叉的重复路径（duplicate path）**、**主路径上的阻碍**、**缺失的测试（test gap）**。纯外观的拆分、改名、搬文件一律不做（见文末“考虑过但未做”）。
- 每条候选都先读代码核实，再实施。每个行为变化都补了测试，并确认新测试**在旧代码上失败、在新代码上通过**。
- engine、contracts、science 没有改动。

## 改了什么

| # | 类型 | 改动 | 文件 |
|---|---|---|---|
| F1 | 缺陷 + 重复路径 | 验证包（validation package）的 “QA sign-off” 一行原来是 `tpv package` 打包时的快照，同一响应里的交付物（deliverable）状态却是读取时实时刷新的。结果是 QA 签字后页面上一处显示 approved、另一处仍显示 awaiting QA approval；报告被改动后，一处显示 approval invalid、另一处仍显示 approved。修法：把 `report.status()` 里的标签映射原样移到 `compliance/workflow.py` 末尾的 `report_approval()`，tpv 和 API 共用这一份。`GET /api/validation/package` 读取时用它刷新报告一行。当前库里没有对应审批请求时保留打包时的标签，其中 “approved” 改为 “approval unconfirmed”，与交付物用的规则一致。 | `api/trialpilot_api/compliance/workflow.py`、`api/trialpilot_api/compliance/routes.py`、`validation/trialpilot_validation/report.py` |
| F2 | 缺陷 | `POST /api/scenarios/{id}/submit` 原来允许 admin 替作者提交，但审批请求和 `approval.submit` 审计条目记在作者名下（审计归属错误）。权限矩阵（`validation/ROLES.md`）里 admin 本来就没有 `approval.submit`，mock 也只允许作者提交。现在只允许作者本人提交；admin 编辑草稿（`PATCH`）的权限不变。 | `api/trialpilot_api/routes_scenarios.py` |
| F3 | 主路径阻碍 + 常量已分叉 | 导航栏 “Command center” 在没打开过设计时链接到 `/command/demo`，但演示试验的 id 是 `demo-40`，所以点 “Start simulation” 会报 `design_not_found`。改为使用 `DEMO_TRIAL_ID`。这个常量现在只在 `app/lastDesign.ts` 定义一次，`features/command/api.ts` 原样重新导出（re-export），对外接口不变，也不会把懒加载（lazy-loaded）的指挥中心代码拉进主包。 | `web/src/app/Layout.tsx`、`web/src/app/lastDesign.ts`、`web/src/features/command/api.ts` |
| F4 | 类型错误 | 已有的 `tsc` 报错：测试辅助函数把 `unit` 声明成 `string`，而契约要求 `MetricRangeUnit`。改了参数类型，并去掉两处为绕开这个错误写的 `as never`。只改测试文件的类型。 | `web/src/features/command/expectation.test.tsx` |
| F5 | 重复路径（已分叉） | `POST /api/approvals {record_type:"scenario"}` 是提交场景的第二条路，它不会冻结场景：审批通过后草稿仍可修改，签名随即失效。现在对已保存的场景返回 409 `submit_via_scenario`，并在 details 里给出正确的 `/submit` 路径。保存场景之外的记录（例如合规层独立测试里无法解析的记录 “B”）不受影响。 | `api/trialpilot_api/compliance/routes.py` |
| F6 | 缺陷 + 重复循环 | `GET /api/scenarios/{id}/versions` 不同步审批结果，审批通过后仍显示 `submitted`；`GET /api/scenarios` 和 `GET /api/scenarios/{id}` 都会同步。把列表里的同步循环提成 `_sync_submitted()`，两个端点共用。 | `api/trialpilot_api/routes_scenarios.py` |
| F7 | 测试缺口 | 计算缓存的 A3 键刻意排除 `NOT_READ_BY_A3` 里的三个杠杆，依据只有一行注释。新增测试：用真实引擎把这三个杠杆设为非默认值，断言 forecast 和 supply 的结果不变。将来引擎若开始读取这些杠杆，测试会失败，而不是悄悄复用过期的缓存。只加测试，计算路径未改。 | `api/tests/test_a3_cache_levers.py`（新增） |

新增或修改的测试：

- `api/tests/test_scenarios.py::test_admin_cannot_submit_someone_elses_draft`（F2）
- `api/tests/test_approval_export_sse.py::test_versions_listing_reports_the_decided_status`（F6）
- `api/tests/test_approval_export_sse.py::test_saved_scenario_cannot_be_submitted_through_the_approvals_route`（F5）
- `api/tests/compliance/test_compliance_api.py::test_validation_package_qa_signoff_line_follows_the_live_approval`（F1）
- `api/tests/test_a3_cache_levers.py`（F7）
- `web/src/app/layout.test.tsx`（F3，2 个测试）
- `web/src/features/command/expectation.test.tsx`（F4，只改类型）

## 对外行为变化（每条都有测试）

1. admin 提交别人的草稿：200 → 403 `not_author`（F2）。
2. 已保存的场景走 `POST /api/approvals`：201 → 409 `submit_via_scenario`（F5）。
3. `GET /versions` 返回审批后的实际状态。与列表端点一样，首次读取时可能写入 `scenario.approved` / `scenario.rejected` 审计条目（F6）。
4. 验证包报告一行的 `status`、`approval_id`、`signatures`、`qa_signature`、`reason` 跟随实时审批（F1）。标签文字未改。
5. 没打开过设计时，导航栏指挥中心链接变为 `/command/demo-40`（F3）。

## 保持不变的外部行为

- **300 ms 门槛未放宽**：engine 未改，门槛测试的阈值、种子、抽样数未改，冷计算路径未改。
- **碳排系数未调整**：`data/params`、`carbon.py`、science 数据都未改。
- **QA 未签字保持 “awaiting QA approval”**：标签映射逐字搬移、文字不变；F1 让它在 QA 签字后能正确变成 “approved”。tpv 测试 `test_report_states_real_counts_and_waits_for_qa` 仍然通过。
- **模拟数据保留 simulated**：ops 未改。
- **AI 草稿保留 “DRAFT — requires human review”**：未改任何草稿文字。
- **作者不能批准自己的记录**：SOD 检查未改。F2 刻意没有把 `author` 换成调用者，否则真正的作者就能批准自己的场景。
- 其余 HTTP 路径、状态码、错误信封 `{error,message,details}`、生成的契约都未改。被排除文件导入的符号（`routes_scenarios` 的 `LeversIn`、`validate_levers`、`_params_snapshot` 等）签名未改。
- 6 个 `validation/defects/D*.patch` 仍能 `git apply --check`。F1 的新函数追加在 `workflow.py` 末尾，没有碰 D3 补丁的上下文。

## 命令结果

基线（改动前，同一环境）：api 417 passed，engine 136，contracts 106，validation 55，science 37，web vitest 131；`pnpm typecheck` 有 1 个已有错误（F4）。

改动后（我改过的包）：

| 命令 | 结果 |
|---|---|
| `cd api && uv run pytest` | 422 passed（417 + 5 新增），0 failed |
| `cd validation && uv run pytest` | 55 passed |
| `cd web && corepack pnpm@9.15.9 test` | 15 files，133 passed（131 + 2 新增） |
| `cd web && corepack pnpm@9.15.9 typecheck` | 通过，0 error（原有 1 个错误已修） |
| `uv run ruff check .`（api、validation） | All checks passed |
| `uv run --project contracts python contracts/gen.py --check` | OK: 20 generated files are up to date |
| `git apply --check validation/defects/D1…D6` | 全部 OK |
| 新测试反向验证（临时换回旧源码） | F1、F2、F3、F5、F6 的新测试在旧代码上都失败，在新代码上都通过 |

未验证：

- engine、contracts、science 本轮没有改动，只在基线时跑过，改动后没有重跑。
- web e2e（Playwright）没有跑。F1 只影响验证页 “QA sign-off” 一行。`web/e2e/compliance.spec.ts:133` 断言的 “awaiting QA approval” 在未签字时保持不变，但没有实际跑 e2e 确认。
- `tpv defects-run` 没有跑，只用 `git apply --check` 确认了补丁能应用。

## 考虑过但未做

- 合并两份 `canonical_json`：可能改变已存的记录哈希，使现有签名失效；两份实现当前结果一致。
- 删除合规适配器的 stub、`EventBroker` / `sse_response`：会连带删除现有测试，收益低。
- `sign_request` / `create_request` / `sync_status` 的先检查后执行（check-then-act）竞态：需要并发请求才能出现；修复要改动 D3 补丁锚定的代码块。
- 重复的角色常量、`ai:` 前缀、指标常量、两个页面里的签名 UI：取值一致，属于外观问题。
- mock 缺少 ops、validation、reject 接口，3 个未缓存试验的离线抽取返回 503：补上就是新功能。
- ProtocolReview 的印章文字与 “DRAFT — requires human review” 不同：这是现有文字，按要求保留。
