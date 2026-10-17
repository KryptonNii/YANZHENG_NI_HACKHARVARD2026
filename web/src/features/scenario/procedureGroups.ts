import type { Visit } from "@/app/contracts";
import { humanize } from "@/app/format";

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
