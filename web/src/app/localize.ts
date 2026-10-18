import { translate } from "./i18n";

/**
 * Display-only Chinese for sentences the interface still receives in English.
 * The English text is unchanged when the language is English, and stored data is not rewritten.
 */
const EXACT: Record<string, string> = {
  "Untitled scenario": "未命名方案",
  "Invalid request": "请求无效",
  "The TrialPilot API is not reachable right now.": "目前无法连接 TrialPilot API。",
  "Can't reach the TrialPilot API. Check that the server is running.": "无法连接 TrialPilot API。请确认服务器正在运行。",
  "The API did not provide a valid design version and strong ETag. Reload before editing or computing.": "API 未提供有效的设计版本和强 ETag。编辑或计算前请重新加载。",
  "The API did not return the reviewed design. Nothing was saved; retry applying the protocol.": "API 未返回已审核的设计。没有内容被保存，请重试应用试验方案。",
  "The calculation did not confirm the design version on screen. Retry before saving.": "计算结果未确认与页面上的设计版本一致。保存前请重试。",
  "The protocol response contains an invalid visit. Extract again before applying.": "试验方案响应包含无效访视。应用前请重新提取。",
  "The protocol response contains an invalid visit, week or procedure. Missing weeks are not assumed to be zero; extract again before applying.": "试验方案响应包含无效的访视、周次或检查项目。缺失周次不会被当作 0，应用前请重新提取。",
  "Unexpected approval response shape": "审批响应的格式不符合预期",
  "Invalid evidence path": "证据路径无效",
  "Evidence manifest has no files array": "证据清单中没有文件列表",
  "The viewer role cannot change data.": "查看者角色不能修改数据。",
  "Send the demo identity headers X-User and X-Role with every change.": "每次修改都需要发送演示身份请求头 X-User 和 X-Role。",
  "Only the author can edit a draft scenario.": "只有作者可以编辑草稿方案。",
  "Only the author or an administrator can delete a scenario.": "仅作者或管理员可删除方案。",
  "Only the author or an admin can delete a scenario.": "仅作者或管理员可删除方案。",
  "Only the author can submit a scenario for approval.": "只有作者可以提交方案审批。",
  "This scenario was submitted meanwhile.": "此方案在此期间已被提交。",
  "record_id is required.": "必须提供 record_id。",
  "record_hash must be a sha256 hex digest.": "record_hash 必须是 sha256 十六进制摘要。",
  "A rejection needs a reason.": "拒绝时必须填写原因。",
  "Path escapes the package.": "路径超出了验证包范围。",
  "GET /api/health failed": "GET /api/health 请求失败",
  "Phase not given in the registry.": "注册记录未给出试验分期。",
  "The registry lists no study locations.": "注册记录未列出研究地点。",
  "No study completion date; duration uses the primary completion date.": "没有研究完成日期；持续时间使用主要终点完成日期。",
  "A registry date gave only year/month; the 1st of the month was assumed.": "注册日期只精确到年或月，已假定为该月 1 日。",
  "Per-site enrollment is not in the registry (expected_enrollment left empty).": "注册记录没有各研究中心的入组人数（expected_enrollment 留空）。",
  "Added countries are assumptions, not registry sites.": "新增国家是假设，不是注册研究中心。",
  "Site expected enrollment not given: patients split equally across sites.": "未提供研究中心预期入组人数：患者人数在各中心间平均分配。",
  "No drug kits modelled (drug type 'none', no patients or no dispensing visits).": "未建立药物药盒模型（药物类型为 none、没有患者，或没有发药访视）。",
  "Duration is the design's planned duration (no enrollment forecast supplied): a point value.": "持续时间使用设计中的计划时长（未提供入组预测）：这是一个点值。",
  "Module 'intervention' is excluded (drug manufacture is excluded in the published method); the 'drug_supply' extension estimates kits separately and is included in the totals.": "“干预”模块已排除（发表方法不含药物生产）；“药物供应”扩展单独估算药盒，并计入总量。",
  "Remote monitoring can reduce monitor travel and on-site review work.": "远程监查可以减少监查员差旅和现场审核工作。",
  "Local laboratory testing can reduce central sample shipping costs.": "本地实验室检测可以减少中心样本的运输成本。",
  "On-demand supply can reduce unused drug kits while changing shipment costs.": "按需供应可以减少未使用的药盒，同时改变运输成本。",
  "Adding assumed countries can change recruitment time and site costs; these are assumed sites, not registry sites.": "增加假设国家会改变招募时间和研究中心成本；这些是假设中心，不是注册研究中心。",
  "Moving eligible visits home can reduce site work while adding home nursing costs.": "将符合条件的访视改为上门，可以减少研究中心工作，同时增加上门护理成本。",
  "Excluding the remaining site with the lowest reported expected enrollment can reduce site costs but may lengthen recruitment.": "排除其余中心中报告预期入组人数最低的中心，可以降低中心成本，但可能延长招募时间。",
  "Not linked to an endpoint in the reviewed schedule, so removing it is screened as one cost lever. This is not clinical approval: endpoint linkage does not show the procedure is unnecessary for safety, eligibility or treatment decisions, and removal still requires manual protocol review.": "在已审核的访视计划中未关联终点，因此将其作为一项费用调整进行筛选。这不代表临床批准：终点关联不能说明该检查对安全性、入选资格或治疗决策没有必要，移除仍需人工审核试验方案。",
  "Pressure scenario under an assumed slower enrollment rate. It is an assumption, not a recommendation, and any cost change is not a saving; it shows how the current plan behaves if recruitment is slower than expected.": "这是假设入组速度更慢时的压力情景。它是假设，不是推荐；费用变化也不代表节省，只是展示招募慢于预期时当前计划的表现。",
  "Met the model constraints but ranked below the top 3 by cost P50 change relative to the current selection.": "符合模型约束，但相对于当前选择，按费用 P50 变化排在前 3 名之外。",
  "Enrollment is already at the model minimum, so no slower-enrollment stress scenario was computed.": "入组速度已处于模型下限，因此没有计算更慢入组的压力情景。",
  "Database-lock forecast unavailable for this scenario, so no change is reported.": "此情景没有数据库锁定预测，因此不报告变化。",
  "Reviewed visit schedule required: the schedule is still missing or assumed.": "需要已审核的访视计划：当前计划仍然缺失或为假设。",
  "Current-selection database-lock forecast unavailable; planned duration is not a forecast.": "当前选择没有数据库锁定预测；计划持续时间不是预测值。",
  "Supports a primary endpoint; removal is excluded from advice and requires manual protocol review.": "支持主要终点；建议中不包含移除，且需要人工审核试验方案。",
  "Supports a secondary endpoint; removal is excluded from advice and requires manual protocol review.": "支持次要终点；建议中不包含移除，且需要人工审核试验方案。",
  "Endpoint linkage is unknown; removal is excluded from advice and requires manual protocol review.": "终点关联未知；建议中不包含移除，且需要人工审核试验方案。",
  "Its not_linked occurrences do not override the linked or unknown ones.": "标记为 not_linked 的出现次数不能覆盖已关联或未知关联。",
  "Some sites have no finite expected_enrollment; the smallest site is selected only among reported values, or site exclusion is skipped if none are reported.": "部分研究中心没有有限的 expected_enrollment；只在已报告数值中选择最小的中心，若都没有报告则跳过中心排除。",
  "Existing procedure removals are retained as the comparison baseline; this does not approve their clinical appropriateness.": "已有的检查项目移除作为比较基线保留；这不代表批准其临床合理性。",
  "database-lock forecast unavailable; planned duration is not a forecast": "没有数据库锁定预测；计划持续时间不是预测值",
  "cost delta is unknown": "费用变化未知",
  "cost P50 does not improve on the current selection": "费用 P50 没有优于当前选择",
  "duration delta is unknown": "持续时间变化未知",
  "duration P50 increases beyond the 0-month tolerance": "持续时间 P50 的增加超过 0 个月容差",
  "drug stockout probability is unknown": "药物缺货概率未知",
  "independent": "独立",
  "same source": "同一来源",
  "paper factor kept": "保留论文因子",
  "Real published data (BMJ Open 2024, CC BY 4.0) transcribed by hand from the paper's appendices; not simulated.": "真实已发表数据（BMJ Open 2024，CC BY 4.0），根据论文附录手工转录；不是模拟数据。",
  "Per-draw candidate minus your current selection (the baseline), both computed with seed 7 and 200 draws using common random numbers; negative values are reductions. Feasible candidates are ranked by cost_usd P50, then site_staff_hours P50 (unknown last), then id.": "逐次抽样用候选方案减去当前选择（基线），两者都使用随机种子 7 和 200 次抽样，并使用共同随机数；负值表示减少。可行候选项先按 cost_usd 的 P50 排序，再按 site_staff_hours 的 P50 排序（未知排在最后），最后按 id 排序。",
  "Existing engine per-draw counterfactual minus baseline, using common random numbers.": "现有引擎逐次抽样计算假设方案减去基线，使用共同随机数。",
  "Existing engine per-draw counterfactual minus baseline, using common random numbers; not subtraction of marginal percentiles. Selected codes are removed from every visit. An empty selection compares identical levers.": "现有引擎逐次抽样计算假设方案减去基线，使用共同随机数；不是把各自的分位数相减。选中的代码会从每次访视中移除。未选择时比较的是相同的调整项。",
  "Reviewable model screening assumptions, not a clinical guarantee. A candidate needs a negative cost P50 delta relative to your current selection, no increase in duration P50 (0 months tolerance), and, for drug designs, a known stockout probability at or below the parameter-library warning threshold (0.05 fallback; not applicable to none/device designs). A reviewed visit schedule and database-lock forecasts are required. Procedures that support a primary or secondary endpoint, or whose linkage is unknown, are never recommended for removal. A not_linked procedure may be screened alone as a removal candidate; that is not clinical approval. Added countries are assumed sites, not registry sites. Slower enrollment appears only as an assumption stress scenario.": "这些是可审核的模型筛选假设，不是临床保证。候选项相对当前选择的费用 P50 变化必须为负，持续时间 P50 不得增加（容差 0 个月）；药物设计还需要已知缺货概率，且不高于参数库警告阈值（缺省 0.05；不适用于 none/device 设计）。需要已审核的访视计划和数据库锁定预测。支持主要或次要终点、或关联未知的检查项目绝不建议移除。not_linked 的检查项目可以单独作为移除候选项筛选，但这不代表临床批准。新增国家是假设研究中心，不是注册研究中心。更慢的入组只作为假设压力情景出现。",
  "Placeholder: early-phase studies usually concentrate visits around first doses. Not from a source; replace with the protocol schedule of activities.": "占位说明：早期研究通常把访视集中在首次给药前后。并非来自原始资料；请用试验方案中的活动日程替换。",
  "Placeholder: monthly visits early, then every 8 weeks. Not from a source; replace with the protocol schedule of activities.": "占位说明：前期每月访视，之后每 8 周一次。并非来自原始资料；请用试验方案中的活动日程替换。",
  "Placeholder: every 4 weeks for the first 12 weeks, then every 12 weeks to end of treatment, one follow-up visit. Not from a source; replace with the protocol schedule of activities.": "占位说明：前 12 周每 4 周一次，之后每 12 周一次直到治疗结束，另有一次随访。并非来自原始资料；请用试验方案中的活动日程替换。",
  "Placeholder used when the registry gives no usable phase. Not from a source; replace with the protocol schedule of activities.": "注册记录没有可用分期时使用的占位说明。并非来自原始资料；请用试验方案中的活动日程替换。",
};

const RATIONALE = new Set(Object.keys(EXACT).filter((key) => key.startsWith("Placeholder")));

function basisZh(basis: string): string {
  if (basis.startsWith("registry: ")) return `注册记录：${basis.slice("registry: ".length)}`;
  if (basis === "assumption: template default") return "假设：模板默认值";
  return basis;
}

function kindsZh(kinds: string): string {
  return kinds.replace(/\bstart\b/g, "开始").replace(/\bend\b/g, "结束");
}

function failedConstraints(text: string): string | null {
  const prefix = "Failed the model constraints: ";
  if (!text.startsWith(prefix) || !text.endsWith(".")) return null;
  const parts = text.slice(prefix.length, -1).split("; ");
  const translated = parts.map((part) => {
    const known = EXACT[part];
    if (known) return known;
    const stockout = /^drug stockout probability (.+) exceeds the (.+) screening threshold$/.exec(part);
    if (stockout) return `药物缺货概率 ${stockout[1]} 超过筛选阈值 ${stockout[2]}`;
    return part;
  });
  return `未通过模型约束：${translated.join("；")}。`;
}

function joinKnownSentences(text: string): string | null {
  const keys = Object.keys(EXACT).filter((key) => key.length > 24).sort((a, b) => b.length - a.length);
  let rest = text.trim();
  const parts: string[] = [];
  while (rest) {
    const hit = keys.find((key) => rest === key || rest.startsWith(`${key} `));
    if (!hit) return null;
    parts.push(EXACT[hit]);
    rest = rest.slice(hit.length).trim();
  }
  return parts.join("");
}

function fromPattern(text: string): string | null {
  let match = /^This design changed while you were editing — it is now (.+)\. Reload it before saving so a confirmed protocol schedule is not replaced\.$/.exec(text);
  if (match) {
    const shown = match[1] === "a newer version" ? "更新的版本" : match[1].replace(/^design v/, "设计 v");
    return `此方案在你编辑期间已更改，当前是${shown}。请先重新加载再保存，以免已确认的访视计划被覆盖。`;
  }
  match = /^Request failed \(HTTP (\d+)\)\.$/.exec(text);
  if (match) return `请求失败（HTTP ${match[1]}）。`;
  match = /^No saved scenario with id '(.+)'\.$/.exec(text) ?? /^No saved scenario with id (.+)\.$/.exec(text);
  if (match) return `没有 id 为 ${match[1]} 的已保存方案。`;
  match = /^Enrollment (\d+) is the sponsor's anticipated target \(ESTIMATED\), not an actual count\.$/.exec(text);
  if (match) return `入组人数 ${match[1]} 是申办方预期目标（ESTIMATED），不是实际入组数。`;
  match = /^Enrollment (\d+) is the actual number enrolled \(ACTUAL\)\.$/.exec(text);
  if (match) return `入组人数 ${match[1]} 是实际入组数（ACTUAL）。`;
  match = /^Duration ([0-9.]+) months = ([0-9-]+) to ([0-9-]+) \((.+)\)\.$/.exec(text);
  if (match) return `持续时间为 ${match[1]} 个月，从 ${match[2]} 到 ${match[3]}（${kindsZh(match[4])}）。`;
  match = /^No usable start\/completion dates; duration set to the per-patient schedule length \(([0-9.]+) months\), which ignores the enrollment period\.$/.exec(text);
  if (match) return `没有可用的开始或完成日期；持续时间按每位患者的日程长度设为 ${match[1]} 个月，未计入入组期。`;
  match = /^Visit schedule is NOT in the registry: filled with assumed template '([^']+)' \((\d+) visits over ([0-9.]+) treatment weeks; length basis: ([^)]+)\)\. (.+) Import the protocol to replace it\.$/.exec(text);
  if (match) {
    const rationale = EXACT[match[5]] ?? (RATIONALE.has(match[5]) ? EXACT[match[5]] : match[5]);
    return `注册记录中没有访视计划：已用假设模板“${match[1]}”填补（${match[2]} 次访视，治疗期 ${match[3]} 周；时长依据：${basisZh(match[4])}）。${rationale} 请导入试验方案以替换它。`;
  }
  match = /^Drug type '([^']+)': no interventions listed in the registry\.$/.exec(text);
  if (match) return `药物类型“${match[1]}”：注册记录未列出干预措施。`;
  match = /^Drug type '([^']+)': registry intervention type BIOLOGICAL \((.+)\)\.$/.exec(text);
  if (match) return `药物类型“${match[1]}”：注册干预类型为 BIOLOGICAL（${match[2]}）。`;
  match = /^Drug type '([^']+)': registry intervention type DRUG with no biologic INN stem \((.+)\)\.$/.exec(text);
  if (match) return `药物类型“${match[1]}”：注册干预类型为 DRUG，且名称中没有生物制品 INN 词干（${match[2]}）。`;
  match = /^Drug type '([^']+)': registry intervention type DEVICE \((.+)\)\.$/.exec(text);
  if (match) return `药物类型“${match[1]}”：注册干预类型为 DEVICE（${match[2]}）。`;
  match = /^Drug type '([^']+)': registry type ([^,]+), but the INN stem marks a biologic: (.+) \(WHO INN stem book\)\.$/.exec(text);
  if (match) return `药物类型“${match[1]}”：注册类型为 ${match[2]}，但 INN 词干表明它是生物制品：${match[3]}（WHO INN 词干表）。`;
  match = /^Drug type '([^']+)': no drug or device intervention \(types: (.+)\)\.$/.exec(text);
  if (match) return `药物类型“${match[1]}”：没有药物或器械干预（类型：${match[2]}）。`;
  match = /^Drug type '([^']+)': intervention types (.+) not mapped\.$/.exec(text);
  if (match) return `药物类型“${match[1]}”：干预类型 ${match[2]} 尚未对应。`;
  match = /^(\d+) sites? from the registry; (\d+) with registry geoPoints\.$/.exec(text);
  if (match) return `来自注册记录的研究中心有 ${match[1]} 个，其中 ${match[2]} 个带有注册坐标。`;
  match = /^(\d+) sites? had no registry geoPoint and were placed from city\/state\/country with the offline GeoNames index \(CC BY 4\.0\)(?:; (\d+) only to state level)?\.$/.exec(text);
  if (match) return `${match[1]} 个研究中心没有注册坐标，已用离线 GeoNames 索引（CC BY 4.0）按城市、州和国家定位${match[2] ? `；其中 ${match[2]} 个只精确到州` : ""}。`;
  match = /^(\d+) sites? could not be placed \(no geoPoint, city not found\); lat\/lon left empty\.$/.exec(text);
  if (match) return `${match[1]} 个研究中心无法定位（没有坐标，也找不到城市）；经纬度留空。`;
  match = /^Your current selection already removes (.+), which support an endpoint or have unknown linkage; advice keeps these removals only as the comparison baseline, and this is not approval of removing them\.$/.exec(text);
  if (match) return `当前选择已经移除 ${match[1]}，这些项目支持终点或关联未知；建议只把这些移除保留为比较基线，并不代表批准移除。`;
  match = /^Advice computes your current selection and every candidate with seed (\d+) and (\d+) draws, in one ranking stage\. The formal scenario computation uses its own draw count \(([0-9,]+) draws\), so its figures can differ from these advice estimates\. Drug supply uses the engine's own draw cap, reported in warnings\.$/.exec(text);
  if (match) return `建议在同一个排序阶段用随机种子 ${match[1]} 和 ${match[2]} 次抽样计算当前选择及每个候选项。正式方案计算使用自己的抽样次数（${match[3]} 次），因此数值可能与这些建议估算不同。药物供应使用引擎自己的抽样上限，并在警告中说明。`;
  match = /^Candidate cannot be applied: (.+)$/.exec(text);
  if (match) return `无法应用该候选项：${chineseFor(match[1]) ?? match[1]}`;
  match = /^drug stockout probability (.+) exceeds the (.+) screening threshold$/.exec(text);
  if (match) return `药物缺货概率 ${match[1]} 超过筛选阈值 ${match[2]}`;
  return null;
}

function chineseFor(text: string): string | null {
  return EXACT[text] ?? fromPattern(text) ?? failedConstraints(text) ?? joinKnownSentences(text);
}

export function localizeCopy(text: string): string {
  const chinese = chineseFor(text);
  return chinese === null ? text : translate(text, chinese);
}
