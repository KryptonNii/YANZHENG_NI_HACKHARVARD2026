# 本轮交接：让方案推荐有明确依据和边界

日期：2026-10-17（America/Toronto）。工作目录：`C:\Users\ol735\Desktop\YANZHENG_NI_HACKHARVARD2026`。

按用户最新指示停止 553 同伴扩库工作，本轮集中完成方案推荐和新增国家假设的深化。没有提交或推送。验收对象是共享工作区当前未提交代码，基准 HEAD 为 `ba22027d1d7445d19414410a44afb0aa068bbe1a`；不是一次干净克隆验收。其他任务已有的修改继续保留。

## 已完成

1. **推荐相对于用户当前方案计算。** 请求绑定设计版本和全部当前 levers；候选只返回需要改变的字段，保留其他选择。页面切换版本或选择后立即清除旧建议，取消旧请求并拒绝迟到或基线不符的回包。预览合并候选后重新计算，不自动保存设计或情景。
2. **推荐可以明确拒绝。** 访视表仍缺失或属于假设、缺少真实锁库预测、成本中位数没有改善、工期中位数增加、适用的供药风险未知或超限时，返回理由。计划工期回退值不能充当锁库预测。200 次初筛后，对通过者以 2000 次请求抽样重新计算配对差值并复核约束，最多展示三个候选；供药仍遵循引擎自己的抽样上限。手动 70% 入组压力测试不再作为推荐行动。
3. **程序删除需要人工审查。** 包括标为 `not_linked` 的操作，终点未关联不等于对安全、入选或治疗决策没有价值。推荐不新增或取消用户的删除选择；前端同时阻止清空、缩减已有数组选择的补丁。
4. **修复新增国家的单位错误。** 原实现把每站患者数误当作每国新增站点数。现在每个新增国家仅代表一个假设站点，入组权重取剩余有效站点的正有限值中位数，缺失时使用现有参数；页面、警告和来源说明均披露假设。

方法及限制见 `docs/DECISION_METHOD.md`。各部分的文件范围和技术说明见 `ADVICE_BACKEND.md`、`ADVICE_FRONTEND.md`、`COUNTRY_ASSUMPTION.md`。

## 本轮修改范围

- `api/trialpilot_api/advice/{candidates,ranking,routes,schemas}.py`
- `api/tests/test_advice.py`
- `engine/trialpilot_engine/levers.py`
- `engine/tests/test_levers.py`、`engine/tests/test_forecast.py`
- `web/src/features/scenario/components/{NextLever,LeversPanel}.tsx`
- `web/src/features/scenario/ScenarioPage.tsx` 的建议预览接入
- `web/src/features/scenario/nextLever.test.tsx`
- `web/e2e/next-lever.spec.ts`
- `docs/DECISION_METHOD.md` 及本轮四份 handoff

导入器、同伴数据、benchmark、共享契约及其已有修改不属于本轮实现范围。浏览器测试只在临时数据库里经过现有导入和协议审查流程。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| API 完整测试目录 | 335 通过 |
| Engine 完整测试目录 | 131 通过 |
| Contracts 完整测试目录 | 106 通过 |
| Web 全部 Vitest 测试 | 84 通过，9 个文件 |
| 真实 API + Edge 的 BOREAS 浏览器流程 | 1 通过 |
| TypeScript 项目检查、Vite 生产构建 | 通过 |
| 20 个生成契约文件一致性 | 通过 |
| 本轮 Python 文件 Ruff、Git diff 空白检查 | 通过 |
| 独立只读复查 | 未发现阻塞问题 |

共 656 项单元/集成测试及 1 条真实浏览器流程通过；各子任务的定向测试已包含在这些数量内，不重复计数。没有声称重跑所有历史 E2E 或正式验证套件。前端测试仍输出 React `act(...)` 和 Router future-flag 提示；构建输出目录位于临时目录，Vite 提示不会清空该目录；所有相关命令退出码均为 0。

浏览器实际观察：

- 未审核的 BOREAS 访视表返回 `reviewed_schedule_required`，无推荐。
- 在临时数据库应用缓存协议审查后，锁库 P50 为约 24.876 月；把入组速度调为 70% 后为约 26.170 月。
- 当前方案为 70% 入组、1 个新增假设国家时，按需供药的模型缺货概率约 0.167，高于 0.05 门槛而被拒绝；再增加两个假设国家因成本 P50 不改善被拒绝。
- 点击 50% 远程监查建议预览成功，重新计算保留了 70% 入组和已有 1 个新增假设国家。

这些数字是该临时演示输入和参数快照的模型输出，不是对 BOREAS 真实运营效果的验证。自动化测试中的“接受提取结果”不构成人工临床审批。

## 可复查证据

本机证据目录：`C:\Users\ol735\AppData\Local\Temp\trialpilot-decision-depth-20261017`。

- `api.log`、`api-junit.xml`、`engine.log`、`web-unit.log`、`web-build.log`
- `browser.log`：首轮真实浏览器验收输出
- `browser-evidence.log`、`browser-evidence.json`、`browser-report/index.html`：带截图的浏览器证据；使用另一份临时数据库重新采集，仍是同一条测试，不增加测试数量
- `verification.json`：本轮实现文件的 SHA-256 快照及结果摘要
- `playwright.evidence.config.ts`：独立端口和临时数据库的浏览器配置

复现使用仓库现有虚拟环境及 `web/node_modules` 的已安装程序。未改依赖策略或锁文件。默认 Playwright 配置的依赖启动步骤受现有包发布等待策略影响，因此证据配置直接运行已安装的 Python、Vite 和 Playwright。

## 深度边界与下一步

本轮使推荐过程可解释、可拒绝、可复算，但尚未证明成本准确度、预测区间覆盖率或行动的因果效果。0 月工期 P50 增量和 5% 供药风险门槛是可审查的模型规则；每国一个站点仍是显式假设。

下一步最有价值的是建立独立的真实完成项目验证集：固定登记时可见信息，隐藏后续结果，测量锁库预测误差、区间覆盖率以及对关键假设的敏感性，再决定哪些建议有足够证据展示。当前测试通过不能代替这项校准。
