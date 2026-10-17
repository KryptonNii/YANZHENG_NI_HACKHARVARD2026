import type { Visit } from "@/app/contracts";
import { humanize } from "@/app/format";
import { translate } from "@/app/i18n";

/**
 * Group meaning for Procedure.code, copied from data/fixtures/procedure_codes.yaml (version 1).
 * A protocol label such as "PARC" is not the group: several labels share one code, and the lever
 * removes the whole code. Prefer a label the importer sends on the procedure when it has one.
 */
export const VOCABULARY_LABELS: Record<string, string> = {
  informed_consent: "Informed consent",
  eligibility_check: "Inclusion / exclusion criteria review",
  demographics: "Demographics",
  medical_history: "Medical / surgical history",
  concomitant_meds: "Prior and concomitant medication review",
  adverse_events: "Adverse event review",
  randomization: "Randomization",
  irt_contact: "IRT / IVRS / IWRS transaction",
  drug_dispensing: "Study drug dispensing",
  imp_administration: "Study drug administration at site",
  physical_exam: "Physical examination",
  vital_signs: "Vital signs",
  ecg: "12-lead electrocardiogram",
  echocardiogram: "Echocardiogram",
  x_ray: "X-ray",
  ct_scan: "CT scan",
  mri: "MRI",
  mammogram: "Mammogram",
  biopsy: "Biopsy",
  pk_sample: "Pharmacokinetic blood sample",
  ada_sample: "Anti-drug antibody (immunogenicity) sample",
  urine_sample: "Urine sample / urine pregnancy test",
  blood_draw: "Safety laboratory blood draw",
  biomarker_sample: "Exploratory biomarker / genetic sample",
  sputum_sample: "Sputum sample",
  home_spirometry: "At-home spirometry",
  spirometry: "Spirometry",
  feno: "Fractional exhaled nitric oxide (FeNO)",
  six_minute_walk: "Six-minute walk test",
  ophthalmic_exam: "Ophthalmic examination",
  visual_acuity: "Best-corrected visual acuity",
  retinal_imaging: "Retinal imaging (OCT / fundus photography / angiography)",
  questionnaire: "Questionnaire / patient-reported outcome / diary review",
  telephone_contact: "Telephone / remote contact",
};

export interface ProcedureGroup {
  code: string;
  /** Controlled-vocabulary meaning of the code, or the protocol label when the code is unknown. */
  meaning: string;
  /** Every distinct protocol label that mapped to this code. */
  labels: string[];
  /** Procedure rows across the schedule (one assessment at one visit counts once). */
  occurrences: number;
  /** Distinct visit numbers that include this code. */
  visits: number;
}

/** Localize controlled display labels while preserving imported procedure text and codes. */
export function procedureMeaning(procedure: Pick<ProcedureGroup, "code" | "meaning">): string {
  const labels: Record<string, string> = {
    informed_consent: "知情同意",
    eligibility_check: "入选／排除标准审核",
    demographics: "人口学信息",
    medical_history: "内外科病史",
    concomitant_meds: "既往及合并用药审核",
    adverse_events: "不良事件审核",
    randomization: "随机分组",
    irt_contact: "IRT／IVRS／IWRS 操作",
    drug_dispensing: "试验药物发放",
    imp_administration: "研究中心内试验药物给药",
    physical_exam: "体格检查",
    vital_signs: "生命体征",
    ecg: "十二导联心电图",
    echocardiogram: "超声心动图",
    x_ray: "X 光检查",
    ct_scan: "CT 扫描",
    mri: "磁共振成像",
    mammogram: "乳腺 X 线检查",
    biopsy: "活检",
    pk_sample: "药代动力学血样",
    ada_sample: "抗药抗体（免疫原性）样本",
    urine_sample: "尿样／尿妊娠试验",
    blood_draw: "安全性实验室采血",
    biomarker_sample: "探索性生物标志物／遗传样本",
    sputum_sample: "痰样本",
    home_spirometry: "居家肺功能检查",
    spirometry: "肺功能检查",
    feno: "呼出气一氧化氮（FeNO）",
    six_minute_walk: "六分钟步行试验",
    ophthalmic_exam: "眼科检查",
    visual_acuity: "最佳矫正视力",
    retinal_imaging: "视网膜成像（OCT／眼底照相／血管造影）",
    questionnaire: "问卷／患者报告结局／日记审核",
    telephone_contact: "电话／远程联系",
  };
  return procedure.meaning === VOCABULARY_LABELS[procedure.code]
    ? translate(procedure.meaning, labels[procedure.code] ?? procedure.meaning)
    : procedure.meaning;
}

function sentMeaning(procedure: Visit["procedures"][number]): string | null {
  for (const [key, value] of Object.entries(procedure)) {
    if (!["vocabulary_label", "group_label", "code_label"].includes(key)) continue;
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

export function groupProcedures(visits: Visit[]): ProcedureGroup[] {
  const byCode = new Map<string, { meaning: string | null; labels: Set<string>; visits: Set<number>; occurrences: number }>();
  for (const visit of visits) {
    const seen = new Set<string>();
    for (const procedure of visit.procedures) {
      const row = byCode.get(procedure.code) ?? { meaning: null, labels: new Set<string>(), visits: new Set<number>(), occurrences: 0 };
      row.meaning = row.meaning ?? sentMeaning(procedure);
      if (procedure.label.trim()) row.labels.add(procedure.label.trim());
      row.occurrences += 1;
      if (!seen.has(procedure.code)) {
        row.visits.add(visit.number);
        seen.add(procedure.code);
      }
      byCode.set(procedure.code, row);
    }
  }
  return [...byCode.entries()]
    .map(([code, row]) => {
      const labels = [...row.labels].sort((a, b) => a.localeCompare(b));
      const meaning =
        row.meaning ??
        VOCABULARY_LABELS[code] ??
        (code.startsWith("other:") ? code.slice("other:".length) : null) ??
        (labels.length === 1 ? labels[0] : humanize(code));
      return { code, meaning, labels, occurrences: row.occurrences, visits: row.visits.size };
    })
    .sort((a, b) => a.meaning.localeCompare(b.meaning) || a.code.localeCompare(b.code));
}
