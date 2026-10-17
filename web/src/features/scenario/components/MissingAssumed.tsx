import { useTranslation, translate as t } from "@/app/i18n";
import type { ImportNote } from "@/app/api/types";
import { humanize } from "@/app/format";
import { EmptyState } from "@/app/ui";

const FIELD_HELP: Record<string, { why: string; fix: "protocol" | "edit" | null }> = {
  visits: { get why() { return t("Registries don't publish the visit schedule. A phase-based template (marked as an assumption) is used until you apply a protocol extraction.", "注册平台不公布访视计划。在应用试验方案提取结果前，使用基于试验分期的模板（标记为假设）。"); }, fix: "protocol" },
  enrollment_target: { get why() { return t("No enrollment figure in the source.", "原始数据未提供入组人数。"); }, fix: "edit" },
  duration_months: { get why() { return t("Start or completion dates missing; duration is estimated.", "缺少开始或完成日期；持续时间为估算值。"); }, fix: "edit" },
  drug_type: { get why() { return t("Intervention type unclear in the registry.", "注册记录中的干预类型不明确。"); }, fix: "edit" },
  phase: { get why() { return t("Phase not stated in the source.", "原始数据未说明试验分期。"); }, fix: "edit" },
};

/** "Missing & assumed": what the importer could not get and what fills the gap (§2: unknown ≠ zero). */
export function MissingAssumed({
  missing,
  notes,
  onEdit,
  onProtocol,
}: {
  missing: string[];
  notes: ImportNote[];
  onEdit: () => void;
  onProtocol: () => void;
}) {
  useTranslation();
  if (missing.length === 0 && notes.length === 0) {
    return <EmptyState title={t("Nothing missing", "没有缺失项")}>{t("Every field came from the source.", "所有字段均来自原始数据。")}</EmptyState>;
  }
  return (
    <ul className="divide-y divide-ink-100" data-testid="missing-assumed">
      {missing.map((f) => {
        const help = FIELD_HELP[f];
        const lat = f.startsWith("site") && f.includes("coord");
        return (
          <li key={f} className="flex flex-wrap items-start justify-between gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink-900">
                <span className="mr-1.5 inline-block rounded bg-caution-100 px-1.5 text-[11px] font-bold uppercase tracking-wide text-caution-900">
                  {t("assumed", "假设")}
                </span>
                {humanize(f)}
              </p>
              <p className="mt-0.5 text-sm text-ink-600">
                {help?.why ?? (lat ? t("Coordinates resolved from an offline geocoder.", "坐标由离线地理编码器解析。") : t("Not available from the source; filled with a labelled assumption.", "原始数据未提供；已用明确标记的假设补全。"))}
              </p>
            </div>
            {help?.fix === "protocol" && (
              <button type="button" className="btn-secondary py-1.5 text-xs" onClick={onProtocol}>
                {t("Upload protocol", "上传试验方案")}
              </button>
            )}
            {help?.fix === "edit" && (
              <button type="button" className="btn-secondary py-1.5 text-xs" onClick={onEdit}>
                {t("Edit value", "编辑数值")}
              </button>
            )}
          </li>
        );
      })}
      {notes.map((note) => {
        const counted = note.assumption && (!note.field || !missing.includes(note.field));
        return (
          <li key={`${note.field ?? ""}:${note.text}`} className="py-2.5 text-sm text-ink-700">
            <span className={`mr-1.5 inline-block rounded px-1.5 text-[11px] font-bold uppercase tracking-wide ${counted ? "bg-caution-100 text-caution-900" : "bg-ink-100 text-ink-700"}`}>
              {counted ? t("assumed", "假设") : t("note", "备注")}
            </span>
            {note.text}
          </li>
        );
      })}
    </ul>
  );
}
