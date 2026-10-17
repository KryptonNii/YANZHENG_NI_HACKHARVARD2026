import { translate } from "@/app/i18n";

// Display labels only; persisted values and API identifiers stay unchanged.
const labels: Record<string, string> = {
  "Command center": "指挥中心", "Cost": "成本", "Carbon": "碳排放", "Delay": "延迟", "Site hours": "中心工时",
  "On track": "按计划进行", "Watch": "需关注", "At risk": "存在风险", "Unknown": "未知", "unknown": "未知",
  "Never enrolled": "从未入组", "Not started": "尚未开始", "Active": "活跃", "Stalled": "停滞",
  "Likely worked": "很可能有效", "Inconclusive": "结论不明确", "Likely coincidence": "很可能是巧合", "No effect": "无效果",
  "Travel": "差旅", "Courier": "快递", "Finance": "财务", "Vendor": "供应商",
  "critical": "严重", "warning": "警告", "info": "提示", "open": "待处理", "acknowledged": "已确认", "action planned": "已规划行动", "resolved": "已解决", "dismissed": "已解除",
  "planned": "已规划", "in progress": "进行中", "done": "已完成", "cancelled": "已取消",
  "pending": "待审批", "approved": "已批准", "rejected": "已拒绝", "all": "全部", "draft": "草稿", "executed": "已执行", "missing": "缺失", "approval unconfirmed": "审批尚未确认",
  "authored": "编写", "reviewed": "审核", "QA approved": "质量保证批准", "qa approved": "质量保证批准", "approved for use": "批准使用", "scenario": "情景", "validation report": "验证报告",
  "author": "作者", "reviewer": "审核人", "qa": "质量保证", "admin": "管理员", "viewer": "查看者",
  "pass": "通过", "passed": "通过", "fail": "失败", "failed": "失败", "error": "错误", "skipped": "已跳过", "not run": "未运行", "not generated": "未生成", "no stage": "无阶段",
  "low": "低", "medium": "中", "high": "高", "requirements": "需求", "tests": "测试", "covered": "已覆盖", "untested": "未测试",
  "Enrollment": "入组", "Enrolled": "已入组", "Open queries": "未解决质疑", "Site status": "中心状态", "Sites status": "中心状态", "Milestones": "里程碑", "Database lock": "数据库锁定", "Drug supply": "药物供应", "Cost to date": "累计成本", "Carbon to date": "累计碳排放", "Site workload": "中心工作量", "Missed visits": "漏访", "Query rate": "质疑率", "Missed-visit rate": "漏访率", "query rate": "质疑率", "missed visit rate": "漏访率",
  "countries": "国家", "sites": "中心", "North America": "北美", "Europe": "欧洲", "Asia Pacific": "亚太", "Latin America": "拉丁美洲",
  "Enrollment vs plan band": "入组人数与计划范围", "Enrollment rate (trailing 8 weeks)": "入组率（过去 8 周）", "Sites active / stalled / not activated": "活跃 / 停滞 / 未启动中心", "Missed visits (trailing 8 weeks)": "漏访（过去 8 周）", "Withdrawals": "退出人数", "Open queries and median age": "未解决质疑及中位持续时间", "Queries per 100 visits (trailing 8 weeks)": "每 100 次访视的质疑数（过去 8 周）", "Drug on hand vs projected need": "现有药物与预测需求", "Spend to date vs plan": "累计支出与计划", "Carbon to date vs plan": "累计碳排放与计划", "Site staff hours to date vs plan": "中心累计工时与计划", "Patient burden hours to date vs plan": "患者累计负担时长与计划", "Milestone forecasts vs targets": "里程碑预测与目标", "Open alerts by severity": "按严重程度划分的待处理警报",
  "enrollment lag": "入组滞后", "query backlog": "质疑积压", "drug overstock": "药物库存过剩", "drug shortfall": "药物短缺", "costly shipping mode": "运输方式成本过高", "monitoring inefficiency": "监查效率低", "vendor delay": "供应商延迟", "milestone at risk": "里程碑存在风险",
  "enrollment rate per month": "每月入组率", "query rate percent": "质疑率", "kits on hand": "现有药盒", "air shipment share percent": "空运占比", "monitoring co2e kg per month": "每月监查碳排放", "milestone slip days": "里程碑延迟天数", "patients/month": "患者/月", "queries": "质疑", "alerts": "警报",
  "Hold a feasibility call with the site to review its pre-screening log": "与中心召开可行性电话会议，审查预筛选记录",
  "Retrain the site on inclusion/exclusion criteria and referral pathways": "重新培训中心掌握纳入/排除标准及转诊流程",
  "Activate a backup site in the same country": "启动同一国家的备用中心",
  "Close the site and reallocate its enrollment target": "关闭中心并重新分配其入组目标",
  "Retrain site staff on eCRF completion guidelines": "重新培训中心员工掌握 eCRF 填写指南",
  "Run a remote query-resolution session with the CRA": "与临床监查员开展远程质疑解决会议",
  "Send weekly open-query reminder e-mails to site coordinators": "每周向中心协调员发送未解决质疑提醒邮件",
  "Switch the site to on-demand (IRT-triggered) resupply and return excess kits to the depot": "将中心改为按需补货（由 IRT 触发），并将多余药盒退回仓库",
  "Transfer excess kits to the regional depot before they expire": "在过期前将多余药盒转移至区域仓库",
  "Raise the site's IRT resupply trigger and maximum stock levels": "提高中心的 IRT 补货触发阈值及最高库存水平",
  "Send an emergency resupply shipment by air": "通过空运紧急补货",
  "Switch specimen shipments to ground courier with dry ice (<= 48 h transit)": "将样本运输改为干冰陆运快递（运输时间不超过 48 小时）",
  "Batch monitoring visits by city: one trip per cluster per cycle": "按城市合并监查访视：每个周期对每组中心安排一次行程",
  "Move alternate monitoring visits to remote source-data review": "将隔次监查访视改为远程源数据审查",
  "Escalate to the vendor's account lead and agree a recovery plan": "向供应商客户负责人升级问题，并商定恢复计划",
  "Ask the vendor to add a second programming team for the delivery": "要求供应商增加第二个编程团队以完成交付",
  "Re-baseline the database-lock timeline with the steering committee": "与指导委员会重新确定数据库锁定时间基线",
  "Prioritise data cleaning at sites with the largest query backlogs": "优先清理质疑积压最多的中心的数据",
  "Visit-reminder SMS programme for patients": "患者访视提醒短信计划",
  "screened": "已筛选", "enrolled": "已入组", "visit completed": "访视已完成", "visit missed": "访视缺失", "query opened": "质疑已创建", "query closed": "质疑已关闭", "withdrawn": "已退出", "dispatched": "已发运", "received": "已接收", "dispensed": "已发药", "site activated": "中心已启动", "invoice posted": "发票已入账", "milestone updated": "里程碑已更新",
  "Bring database lock back into range": "将数据库锁定日期恢复到计划范围",
  "Scripted scenario forecast": "预设情景预测",
  "In this rehearsal, enrollment and vendor prerequisites are complete. Query clearance at S11 and S27 is the final lock bottleneck. These lock dates are scenario assumptions, separate from the operations forecast below.": "本次演练中，入组和供应商前置条件均已完成。S11 和 S27 的质疑清理是锁库的最后瓶颈。这些锁库日期属于情景假设，与下方的运营预测独立。",
  "Unresolved eCRF queries at S11 and S27 extend the final cleaning window. Database lock is now forecast beyond the planned range.": "S11 和 S27 尚未解决的 eCRF 质疑延长了最后的数据清理时间。预计数据库锁定日期将超出计划范围。",
  "Retrain staff on eCRF completion": "重新培训员工填写 eCRF", "Run eCRF training": "开展 eCRF 培训", "Data management lead": "数据管理负责人",
  "Run eCRF training at S11 and S27 and check query creation and clearance in follow-up.": "在 S11 和 S27 开展 eCRF 培训，并在随访中检查质疑的产生和解决情况。",
  "Fewer new queries and faster clearance could shorten the final cleaning window.": "减少新质疑并加快解决速度，可能缩短最后的数据清理时间。",
  "Query rate falls much more than at matched controls. Under this scenario's cleaning assumption, clearing the bottleneck brings lock back into range.": "质疑率的下降幅度明显大于匹配对照中心。在此情景的数据清理假设下，消除瓶颈可使锁库日期恢复到计划范围。",
  "Send visit-reminder SMS": "发送访视提醒短信", "Run SMS programme": "开展短信提醒计划", "Site operations lead": "中心运营负责人",
  "Run the patient SMS programme across the 11 target sites and track missed visits against matched controls.": "在 11 个目标中心开展患者短信提醒计划，并与匹配对照中心比较漏访情况。",
  "Fewer missed visits could reduce follow-up work before lock.": "减少漏访可能降低锁库前的随访工作量。",
  "Missed visits fall at treated and control sites as the northern winter ends. This shared seasonal improvement does not pull lock back into range.": "随着北半球冬季结束，干预中心与对照中心的漏访均有所下降。这种共同的季节性改善并未使锁库日期恢复到计划范围。",
  "Too early: 1 complete week(s) of data after the start; at least 3 are needed.": "判断尚早：启动后仅有 1 个完整周的数据，至少需要 3 周。",
  "Query rate (data queries opened per 100 completed visits) at the treated site(s) S11, S27 went from 87.3 to 33.0 per 100 (-54.3); at 6 matched control site(s) (same region, nearest baseline: S12, S13, S23, S28, S26, S17) it went from 58.3 to 51.8 (-6.5). Difference-in-differences: -47.8 per 100 (95% interval -76.7 to -23.4; 12 weeks before vs 17 weeks after the start on 2026-06-08). The interval excludes zero in the intended direction: the change at the treated units is larger than what the controls show, so it is unlikely to be coincidence. Interpretation assumes parallel trends and no unmeasured concurrent changes; this simulated observational estimate does not prove causation. Note: no control had a similar baseline; the estimate relies on parallel trends.": "质疑率（每完成 100 次访视产生的数据质疑数）在干预中心 S11、S27 从 87.3 降至 33.0（减少 54.3）；6 个匹配对照中心（同地区、基线最接近：S12、S13、S23、S28、S26、S17）从 58.3 降至 51.8（减少 6.5）。双重差分为每 100 次访视减少 47.8（95% 区间 -76.7 至 -23.4；比较 2026-06-08 启动前 12 周与启动后 17 周）。区间在预期方向上不包含零：干预中心的变化大于对照中心，因此不太可能是巧合。解读假设平行趋势且没有未测量的同期变化；此模拟观察性估计不能证明因果关系。注意：没有基线相似的对照中心，估计依赖平行趋势假设。",
  "Missed-visit rate (missed visits per 100 scheduled post-baseline visits) at the treated site(s) S14, S15, S16, S17, S18, S19, S20, S25, S26, S27, S28 went from 18.7 to 8.4 per 100 (-10.3); at 6 matched control site(s) (same region, nearest baseline: S11, S13, S24, S12, S22, S23) it went from 19.4 to 8.5 (-10.9). Difference-in-differences: +0.6 per 100 (95% interval -7.9 to +9.0; 12 weeks before vs 26 weeks after the start on 2026-03-02). The treated units did improve, but the controls improved by a similar amount over the same weeks, so the improvement is most likely a shared trend (e.g. seasonal), not the intervention. Interpretation assumes parallel trends and no unmeasured concurrent changes; this simulated observational estimate does not prove causation.": "漏访率（每 100 次计划的基线后访视中的漏访次数）在干预中心 S14、S15、S16、S17、S18、S19、S20、S25、S26、S27、S28 从 18.7 降至 8.4（减少 10.3）；6 个匹配对照中心（同地区、基线最接近：S11、S13、S24、S12、S22、S23）从 19.4 降至 8.5（减少 10.9）。双重差分为每 100 次访视增加 0.6（95% 区间 -7.9 至 +9.0；比较 2026-03-02 启动前 12 周与启动后 26 周）。干预中心确有改善，但对照中心在同期的改善幅度相近，因此更可能是共同趋势（例如季节性）造成，而非干预效果。解读假设平行趋势且没有未测量的同期变化；此模拟观察性估计不能证明因果关系。",
};

export function displayText(value: string): string {
  const label = labels[value] ?? labels[value.replaceAll("_", " ")];
  if (label) return translate(value, label);
  const patterns: [RegExp, string][] = [
    [/^(\d+) active \/ (\d+) stalled$/, "$1 个活跃 / $2 个停滞"],
    [/^(.+): no patient enrolled after (\d+) weeks active \(plan P50 (\d+)\)\.$/, "$1：启动 $2 周后仍无患者入组（计划 P50 $3）。"],
    [/^(.+): (\d+) enrolled vs plan P50 (\d+) \(P10 (\d+)\) — (\d+)% of the planned rate\.$/, "$1：已入组 $2，计划 P50 $3（P10 $4）— 达到计划速率的 $5%。"],
    [/^Study enrollment (\d+) is below the plan P10 band \((\d+)\) for (\d+) weeks; last-patient-in forecast P50 day (\d+) vs target (\d+)\.$/, "研究入组人数 $1 连续 $3 周低于计划 P10 范围（$2）；最后一位患者入组预测 P50 为第 $4 天，目标为第 $5 天。"],
    [/^(.+): (\d+) open queries \(median age (\d+) days\), growing ([+\-\d.]+)\/week over (\d+) weeks\.$/, "$1：$2 项未解决质疑（中位持续时间 $3 天），过去 $5 周每周增加 $4 项。"],
    [/^(.+): (\d+) kits on hand, (\d+) dispensed in the last (\d+) weeks; ~(\d+) kits projected to expire \(first expiry ([^)]+)\)\.$/, "$1：现有 $2 盒药物，过去 $4 周发放 $3 盒；预计约 $5 盒将过期（最早到期日 $6）。"],
    [/^(.+): ([\d.]+) weeks of supply \(on hand \+ in transit\) vs observed resupply lead time (\d+) days; (\d+) kit\(s\) short at dispensing in the last 8 weeks\.$/, "$1：现有及在途库存可供应 $2 周，实际补货周期为 $3 天；过去 8 周发药时短缺 $4 盒。"],
    [/^(.+): (\d+) of (\d+) specimen shipments flown in (\d+) weeks although the central lab is ~(\d+) km by road \(ground courier with dry ice is feasible up to (\d+) km\)\.$/, "$1：过去 $4 周的 $3 批样本中有 $2 批使用空运，但中心实验室的公路距离约为 $5 公里（干冰陆运快递可覆盖 $6 公里）。"],
    [/^(.+): (\d+) avoidable monitoring trip\(s\) in (\d+) weeks — sites in (.+) visited on separate trips instead of one trip per city\.$/, "$1：过去 $3 周有 $2 次可避免的监查行程 — $4 的中心分别安排了行程，而非每个城市合并一次。"],
    [/^(.+): '(.+)' now forecast (.+) vs planned (.+) \(\+(\d+) days\)( — on the database-lock critical path)?\.$/, "$1：“$2”目前预计于 $3 完成，原计划为 $4（推迟 $5 天）$6。"],
    [/^Database lock forecast P50 (.+) \(P10 (.+), P90 (.+)\) vs target (.+): \+(\d+) days\. Main driver: (.+)\.$/, "数据库锁定预测 P50 $1（P10 $2，P90 $3），目标为 $4：推迟 $5 天。主要原因：$6。"],
  ];
  for (const [pattern, replacement] of patterns) {
    if (pattern.test(value)) return translate(value, value.replace(pattern, replacement).replace(" — on the database-lock critical path", " — 位于数据库锁定关键路径上"));
  }
  return value;
}
