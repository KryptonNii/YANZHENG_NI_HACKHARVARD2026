import type { TrialDesign } from "@/app/contracts";
import { humanize } from "@/app/format";
import { Badge } from "@/app/ui";

function Fact({ label, value, assumed }: { label: string; value: string; assumed?: boolean }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</dt>
      <dd className="mt-0.5 flex items-center gap-1.5 text-base font-semibold text-ink-900">
        {value}
        {assumed && (
          <Badge tone="caution" title="Missing from the source; filled with a labelled assumption">
            assumed
          </Badge>
        )}
      </dd>
    </div>
  );
}

const SOURCE_LABEL: Record<TrialDesign["source"], string> = {
  ctgov: "ClinicalTrials.gov (real registry data)",
  protocol_pdf: "Protocol PDF (human-confirmed extraction)",
  manual: "Entered manually",
  published_paper: "Published paper",
  fixture: "Fixture",
};

export function TrialCard({ design, rawCached, onEdit }: { design: TrialDesign; rawCached?: boolean; onEdit?: () => void }) {
  const countries = [...new Set(design.sites.map((s) => s.country))];
  const missing = new Set(design.missing_fields);
  return (
    <section className="card p-5" aria-labelledby="trial-title" data-testid="trial-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            {design.registry_id ?? "No registry id"} · {SOURCE_LABEL[design.source]}
            {rawCached ? " · served from cache" : ""}
          </p>
          <h2 id="trial-title" className="mt-1 text-xl font-bold leading-snug text-ink-900">
            {design.title}
          </h2>
          {design.conditions.length > 0 && <p className="mt-1 text-sm text-ink-600">{design.conditions.join(" · ")}</p>}
        </div>
        <div className="flex gap-2">
          {design.registry_id?.startsWith("NCT") && (
            <a className="btn-ghost" href={`https://clinicaltrials.gov/study/${design.registry_id}`} target="_blank" rel="noreferrer">
              View on ClinicalTrials.gov
            </a>
          )}
          {onEdit && (
            <button type="button" className="btn-secondary" onClick={onEdit}>
              Edit facts
            </button>
          )}
        </div>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Fact label="Phase" value={design.phase ?? "—"} assumed={missing.has("phase")} />
        <Fact label="Sites" value={design.sites.length.toLocaleString("en-US")} assumed={missing.has("sites")} />
        <Fact label="Countries" value={countries.length.toLocaleString("en-US")} />
        <Fact label="Enrollment" value={`${design.enrollment_target.toLocaleString("en-US")} patients`} assumed={missing.has("enrollment_target")} />
        <Fact label="Duration" value={`${design.duration_months} months`} assumed={missing.has("duration_months")} />
        <Fact label="Drug type" value={humanize(design.drug_type)} assumed={missing.has("drug_type")} />
      </dl>
      {countries.length > 0 && (
        <p className="mt-3 text-xs text-ink-500">
          Countries: {countries.slice(0, 12).join(", ")}
          {countries.length > 12 ? ` and ${countries.length - 12} more` : ""}
        </p>
      )}
    </section>
  );
}
