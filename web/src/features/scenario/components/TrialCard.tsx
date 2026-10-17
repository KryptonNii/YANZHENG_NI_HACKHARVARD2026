import { useTranslation, translate as t } from "@/app/i18n";
import type { TrialDesign } from "@/app/contracts";
import type { ImportCtgovResponse } from "@/app/api/types";
import { humanize } from "@/app/format";
import { Badge } from "@/app/ui";

function Fact({ label, value, assumed }: { label: string; value: string; assumed?: boolean }) {
  useTranslation();
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</dt>
      <dd className="mt-0.5 flex items-center gap-1.5 text-base font-semibold text-ink-900">
        {value}
        {assumed && (
          <Badge tone="caution" title={t("Missing from the source; filled with a labelled assumption", "原始数据缺失；已使用明确标记的假设补全")}>
            {t("assumed", "假设")}
          </Badge>
        )}
      </dd>
    </div>
  );
}

const SOURCE_LABEL: Record<TrialDesign["source"], string> = {
  get ctgov() { return t("ClinicalTrials.gov — real registry data", "ClinicalTrials.gov — 真实注册数据"); },
  get protocol_pdf() { return t("Protocol PDF (human-confirmed extraction)", "试验方案 PDF（经人工确认的提取结果）"); },
  get manual() { return t("Entered manually", "手动输入"); },
  get published_paper() { return t("Published paper", "已发表论文"); },
  get fixture() { return t("Fixture", "固定示例数据"); },
};

export function TrialCard({
  design,
  info,
  onEdit,
}: {
  design: TrialDesign;
  /** registry details shown beside the stored design (the design itself always comes from `design`) */
  info?: Pick<ImportCtgovResponse, "raw_cached" | "field_sources" | "sponsor" | "collaborators" | "overall_status" | "attribution"> | null;
  onEdit?: () => void;
}) {
  useTranslation();
  const countries = [...new Set(design.sites.map((s) => s.country))];
  const missing = new Set(design.missing_fields);
  const sources = Object.entries(info?.field_sources ?? {});
  return (
    <section className="card p-5" aria-labelledby="trial-title" data-testid="trial-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            {design.registry_id ?? t("No registry id", "无注册编号")} · {SOURCE_LABEL[design.source]}
            {info?.raw_cached ? t(" · served from the local cache", " · 来自本地缓存") : ""}
          </p>
          <h2 id="trial-title" className="mt-1 text-xl font-bold leading-snug text-ink-900">
            {design.title}
          </h2>
          <p className="mt-1 text-sm text-ink-600">
            {[design.conditions.join(" · "), info?.sponsor && t(`Sponsor: ${info.sponsor}`, `申办方：${info.sponsor}`), info?.collaborators.length ? t(`Collaborators: ${info.collaborators.join(", ")}`, `合作方：${info.collaborators.join("、")}`) : null, info?.overall_status && humanize(info.overall_status.toLowerCase())]
              .filter(Boolean)
              .join(" — ")}
          </p>
        </div>
        <div className="flex gap-2">
          {design.registry_id?.startsWith("NCT") && (
            <a className="btn-ghost" href={`https://clinicaltrials.gov/study/${design.registry_id}`} target="_blank" rel="noreferrer">
              {t("View on ClinicalTrials.gov", "在 ClinicalTrials.gov 查看")}
            </a>
          )}
          {onEdit && (
            <button type="button" className="btn-secondary" onClick={onEdit}>
              {t("Edit facts", "编辑基本信息")}
            </button>
          )}
        </div>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Fact label={t("Phase", "分期")} value={design.phase ?? "—"} assumed={missing.has("phase")} />
        <Fact label={t("Sites", "研究中心")} value={design.sites.length.toLocaleString("en-US")} assumed={missing.has("sites")} />
        <Fact label={t("Countries", "国家")} value={countries.length.toLocaleString("en-US")} />
        <Fact label={t("Enrollment", "入组人数")} value={t(`${design.enrollment_target.toLocaleString("en-US")} patients`, `${design.enrollment_target.toLocaleString("zh-CN")} 人`)} assumed={missing.has("enrollment_target")} />
        <Fact label={t("Duration", "持续时间")} value={t(`${design.duration_months} months`, `${design.duration_months} 个月`)} assumed={missing.has("duration_months")} />
        <Fact label={t("Drug type", "药物类型")} value={t(humanize(design.drug_type), ({ small_molecule: "小分子药物", biologic: "生物制剂", cell_gene: "细胞与基因治疗", other: "其他" } as Record<string, string>)[design.drug_type] ?? humanize(design.drug_type))} assumed={missing.has("drug_type")} />
      </dl>
      {countries.length > 0 && (
        <p className="mt-3 text-xs text-ink-500">
          {t("Countries:", "国家：")} {countries.slice(0, 14).join(", ")}
          {countries.length > 14 ? t(` and ${countries.length - 14} more`, `，另有 ${countries.length - 14} 个`) : ""}
        </p>
      )}
      {sources.length > 0 && (
        <details className="mt-3 text-xs text-ink-600">
          <summary className="cursor-pointer font-semibold text-ink-700">{t("Where each field came from", "各字段的来源")}</summary>
          <table className="mt-2 w-full">
            <tbody>
              {sources.map(([k, v]) => (
                <tr key={k} className="border-t border-ink-100">
                  <th scope="row" className="py-1 pr-3 text-left font-medium text-ink-700">{humanize(k)}</th>
                  <td className={`py-1 font-mono ${v.startsWith("assumption") ? "text-caution-800" : "text-ink-600"}`}>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {info?.attribution && <p className="mt-3 border-t border-ink-100 pt-2 text-[11px] text-ink-500">{info.attribution}</p>}
    </section>
  );
}
