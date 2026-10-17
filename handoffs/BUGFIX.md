# 重构与缺陷修复交接（BUGFIX）

日期：2026-10-17（America/Toronto）。工作目录：`C:\Users\ol735\Desktop\YANZHENG_NI_HACKHARVARD2026`，分支 `dev`。
**没有提交、没有推送。** 改动叠加在共享工作区里其他任务未提交的修改之上，那些修改原样保留。

## 范围与取舍

- 检查范围：engine、contracts、api（不含 `benchmark/`、`advice/`）、web（不含 `PeerMirror.tsx`、`NextLever.tsx`、`ScenarioPage.tsx`）、validation、science。
- 先用 10 个只读检查代理扫描，得到 88 条候选（多条重复）。用户补充要求“代码已经足够好就不重构”，因此只保留：**已验证的缺陷**、**真实存在的重复/分叉路径**、**离线导入 → 审批主路径上的阻碍**。函数拆分、类型收紧、文件搬移等低收益改动全部放弃（列在文末）。
- 第一轮较宽的实施在中途停止；所有被它改过的文件已按改动前快照逐字恢复（核对结果：与快照 0 差异），再按收窄后的范围重新实施。
- 每条车道实施后都经过两名独立审查（行为漂移/不变量；测试/必要性），再由修复者处理确认的问题。
- contracts 未改动（没有需要修的问题）。

<!-- LANES -->

## 保持不变的外部行为

- **300 ms 门槛未放宽**：`test_compute_p50_latency_under_300ms` 的阈值、种子、抽样数未改；冷计算路径（`compute()`、`_resolve_design`、`_compute`、`EngineAdapter.compute`）未改。
- **碳排系数未调整**：`carbon.py`、`data/params`、`science/data` 未改；science 默认运行与已提交的 `science/out/results.json` 逐字一致（`test_checked_in_results_are_current` 通过）。
- **QA 未签字保持 “awaiting QA approval”**：`report.status` 与审批流程未改；`pending → awaiting approval` 映射未改。
- **模拟数据保留 simulated**：ops 输出与快照逐项相等（见 ops 车道）；mock 数据标签未改。
- **AI 草稿保留 “DRAFT — requires human review”**：未改任何草稿文字。
- **作者不能批准自己的记录**：服务器端 `self_approval_forbidden` 未改；D3 缺陷补丁仍可应用；mock 的 self-approval 分支逐字未改。
- HTTP 路径、状态码、错误信封 `{error,message,details}`、响应字段与头、生成的契约、web 测试与 e2e 断言的界面文字：除下文列出的缺陷修复外不变。
- 被排除文件导入的符号（`routes_scenarios.{LeversIn, validate_levers, _params_snapshot, _missing_field_warnings, _seed_draws}`、`routes_designs.load_design`、`EngineAdapter.compute/compare`、`settings.default_draws`，以及 web 的 `api`/`request`/组件 props）签名不变。
- 不可变的缺陷锚点（`routes_designs.py` 的 audited_write 段、`workflow.py` SOD 行、`audit.py` 导出循环、`settings.py`）逐字未改。

<!-- COMMANDS -->

## 考虑过但未做（代码已足够好或收益低）

engine 的 `_evaluate`/`_setup`/`update_with_actuals`/`simulate_supply` 拆分、carbon/cost 共用项、范围辅助函数合并；api 的 `map_study_report` 拆分、`extract_schedule` 分支合并、`link_visits` 拆分、导出类型化、错误处理器搬移、`svc: Any` 类型化、`workflow.sign_request` 拆分、`esign.reauthenticate` 拆分、WHERE 子句去重；ops 的模拟器拆分（`_supply`、`compute_health`）、`TrialState` 去重、周分桶合并；web 的 `RequestOptions` 收紧、共享 health 轮询、science 旧格式删除、ImportPage 状态机/文件搬移、endpoint 词表搬移、合同常量复用；validation 的 `package.build`/`execute` 拆分、哈希别名、需求分组去重。
