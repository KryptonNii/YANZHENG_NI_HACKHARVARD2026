import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import type { Levers, TrialDesign } from "@/app/contracts";
import { ApiError, api, isAbort } from "@/app/api/client";
import { DEFAULT_LEVERS } from "@/app/api/normalize";
import type { SavedScenario } from "@/app/api/types";
import { humanize } from "@/app/format";
import { setLastDesignId } from "@/app/lastDesign";
import { useToast } from "@/app/toast";
import { Badge, ErrorPanel, Modal, Skeleton } from "@/app/ui";
import { ForecastChart } from "./components/ForecastChart";
import { LeversPanel } from "./components/LeversPanel";
import { MetricCard } from "./components/MetricCard";
import { ModuleChart } from "./components/ModuleChart";
import { ProvenanceDrawer, type ProvenanceTarget } from "./components/ProvenanceDrawer";
import { SiteMap } from "./components/SiteMap";
import { SupplyPanel } from "./components/SupplyPanel";
import { VersionsPanel } from "./components/VersionsPanel";
import { useScenarioCompute } from "./hooks/useScenarioCompute";
import { METRICS } from "./metrics";

function describeLevers(l: Levers): string[] {
  const out: string[] = [];
  if (l.remote_monitoring_share > 0) out.push(`${Math.round(l.remote_monitoring_share * 100)}% remote monitoring`);
  if (l.home_visit_numbers.length) out.push(`${l.home_visit_numbers.length} home visit${l.home_visit_numbers.length > 1 ? "s" : ""}`);
  if (l.remote_visit_numbers.length) out.push(`${l.remote_visit_numbers.length} telehealth visit${l.remote_visit_numbers.length > 1 ? "s" : ""}`);
  if (l.local_lab_share > 0) out.push(`${Math.round(l.local_lab_share * 100)}% local labs`);
  if (l.drug_supply_strategy === "on_demand") out.push("on-demand supply");
  if (l.removed_procedures.length) out.push(`${l.removed_procedures.length} procedure${l.removed_procedures.length > 1 ? "s" : ""} removed`);
  if (l.excluded_site_ids.length) out.push(`${l.excluded_site_ids.length} site${l.excluded_site_ids.length > 1 ? "s" : ""} excluded`);
  return out;
}

type SaveMode = "new" | "version";

function SaveDialog({ open, onClose, onSave, saving, ready, defaultName, base }: {
  open: boolean;
  onClose: () => void;
  onSave: (name: string, mode: SaveMode) => void;
  saving: boolean;
  ready: boolean;
  defaultName: string;
  /** the selected saved scenario, offered as the base for a new version */
  base: SavedScenario | null;
}) {
  const id = useId();
  const [name, setName] = useState(defaultName);
  const [mode, setMode] = useState<SaveMode>("new");
  useEffect(() => {
    if (!open) return;
    setMode(base ? "version" : "new");
    setName(base ? base.name : defaultName);
  }, [open, defaultName, base]);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Save scenario"
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form={`${id}-form`} className="btn-primary" disabled={saving || !ready || !name.trim()} data-testid="save-confirm">
            {saving ? "Saving…" : mode === "version" && base ? `Save as v${base.version + 1}` : "Save"}
          </button>
        </>
      }
    >
      <form
        id={`${id}-form`}
        onSubmit={(e) => {
          e.preventDefault();
          if (ready && !saving && name.trim()) onSave(name.trim(), mode);
        }}
      >
        {base && (
          <fieldset className="mb-3 space-y-1.5">
            <legend className="label mb-1">Save as</legend>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name={`${id}-mode`} className="mt-0.5 accent-accent-700" checked={mode === "version"} onChange={() => setMode("version")} />
              <span>
                New version of <strong>{base.name}</strong> (v{base.version} → v{base.version + 1})
                <span className="block text-xs text-ink-500">v{base.version} stays unchanged{base.status !== "draft" ? ` — it is ${base.status} and immutable` : ""}.</span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name={`${id}-mode`} className="mt-0.5 accent-accent-700" checked={mode === "new"} onChange={() => setMode("new")} data-testid="save-mode-new" />
              <span>A new, separate scenario</span>
            </label>
          </fieldset>
        )}
        <label htmlFor={id} className="label">
          Name
        </label>
        <input id={id} className="input mt-1" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} data-testid="save-name" />
        <p className="mt-2 text-xs text-ink-500">Saved with the current levers, the computed result and the parameter-set version, against the design version on this page, as a draft you can submit for approval.</p>
      </form>
    </Modal>
  );
}

function TrialHeader({ design, version }: { design: TrialDesign; version: number | null }) {
  const countries = new Set(design.sites.map((s) => s.country)).size;
  return (
    <div className="min-w-0">
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
        Scenario simulator
        {design.registry_id && (
          <>
            {" · "}
            {design.registry_id.startsWith("NCT") ? (
              <a className="link normal-case" href={`https://clinicaltrials.gov/study/${design.registry_id}`} target="_blank" rel="noreferrer">
                {design.registry_id}
              </a>
            ) : (
              design.registry_id
            )}
          </>
        )}
      </p>
      <h1 className="mt-0.5 truncate text-2xl font-bold tracking-tight text-ink-900" title={design.title}>
        {design.title}
      </h1>
      <div className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
        {design.phase && <Badge>{design.phase}</Badge>}
        <Badge>{design.sites.length} sites · {countries} countries</Badge>
        <Badge>{design.enrollment_target.toLocaleString("en-US")} patients</Badge>
        <Badge>{design.duration_months} months planned</Badge>
        <Badge>{humanize(design.drug_type)}</Badge>
        <Badge>{design.visits.length} visits</Badge>
        {version != null && (
          <Badge>
            <span data-testid="design-version">design v{version}</span>
          </Badge>
        )}
      </div>
    </div>
  );
}

export function ScenarioPage() {
  const { designId } = useParams<{ designId: string }>();
  const [search, setSearch] = useSearchParams();
  const toast = useToast();

  const [design, setDesign] = useState<TrialDesign | null>(null);
  const [designVersion, setDesignVersion] = useState<number | null>(null);
  const [designError, setDesignError] = useState<ApiError | Error | null>(null);
  const [levers, setLevers] = useState<Levers>({ ...DEFAULT_LEVERS });
  const [drawer, setDrawer] = useState<ProvenanceTarget | null>(null);
  const [scenarios, setScenarios] = useState<SavedScenario[]>([]);
  const [scenariosLoading, setScenariosLoading] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const selectedId = search.get("s");

  useEffect(() => {
    if (!designId) return;
    const ctrl = new AbortController();
    setDesign(null);
    setDesignVersion(null);
    setDesignError(null);
    setLevers({ ...DEFAULT_LEVERS });
    api
      .getDesign(designId, { signal: ctrl.signal, silent: true })
      .then((rec) => {
        setDesign(rec.design);
        setDesignVersion(rec.version);
        setLastDesignId(rec.design.id);
      })
      .catch((err) => {
        if (!isAbort(err)) setDesignError(err);
      });
    return () => ctrl.abort();
  }, [designId, reloadKey]);

  const refreshScenarios = useCallback(() => {
    if (!designId) return;
    setScenariosLoading(true);
    api
      .listScenarios(designId, { silent: true })
      .then(setScenarios)
      .catch(() => setScenarios([]))
      .finally(() => setScenariosLoading(false));
  }, [designId]);

  useEffect(() => {
    refreshScenarios();
  }, [refreshScenarios]);

  const compute = useScenarioCompute(design?.id, levers, design !== null && designVersion !== null, designVersion);
  const { baseline, current, computing } = compute;
  const canSave = current !== null && designVersion !== null && !computing && !compute.currentError;

  const selected = scenarios.find((s) => s.id === selectedId) ?? null;

  const select = (id: string | null) => {
    const next = new URLSearchParams(search);
    if (id) next.set("s", id);
    else next.delete("s");
    setSearch(next, { replace: true });
  };

  const save = async (name: string, mode: SaveMode) => {
    if (!design || !current || !canSave || designVersion === null) return;
    setSaving(true);
    try {
      const s =
        mode === "version" && selected
          ? await api.newVersion(selected.id, { levers: current.levers, name, design_version: designVersion })
          : await api.saveScenario({ design_id: design.id, design_version: designVersion, name, levers: current.levers });
      toast.push("success", `Saved “${s.name}” v${s.version}`);
      setSaveOpen(false);
      refreshScenarios();
      select(s.id);
    } catch {
      // toast shown by the client
    } finally {
      setSaving(false);
    }
  };

  const toggleSite = (siteId: string) =>
    setLevers((l) => ({
      ...l,
      excluded_site_ids: l.excluded_site_ids.includes(siteId) ? l.excluded_site_ids.filter((x) => x !== siteId) : [...l.excluded_site_ids, siteId],
    }));

  const leverSummary = useMemo(() => describeLevers(levers), [levers]);
  const warnings = current?.warnings ?? baseline?.warnings ?? [];

  if (designError) {
    const notFound = designError instanceof ApiError && designError.status === 404;
    return (
      <div className="mx-auto max-w-2xl pt-6">
        <ErrorPanel
          title={notFound ? "This trial design was not found" : "Could not load the trial design"}
          message={designError.message}
          onRetry={notFound ? undefined : () => setReloadKey((k) => k + 1)}
        />
        <Link to="/" className="btn-secondary mt-4">
          Import a trial
        </Link>
      </div>
    );
  }

  if (!design) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton className="h-8 w-2/3" />
        <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          <Skeleton className="h-[32rem]" />
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
            {METRICS.map((m) => (
              <Skeleton key={m.key} className="h-44" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <TrialHeader design={design} version={designVersion} />
        <div className="flex items-center gap-2">
          <Link to={`/?design=${encodeURIComponent(design.id)}`} className="btn-ghost">
            Trial details
          </Link>
          <button type="button" className="btn-primary" disabled={!canSave || saving} onClick={() => setSaveOpen(true)} data-testid="save-scenario">
            Save scenario
          </button>
        </div>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-[7.5rem] lg:max-h-[calc(100vh-8.5rem)] lg:overflow-y-auto">
          <LeversPanel design={design} levers={levers} onChange={setLevers} />
        </div>

        <div className="min-w-0 space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm" aria-live="polite">
            <span className="font-semibold text-ink-700">Current vs baseline:</span>
            {leverSummary.length === 0 ? (
              <span className="text-ink-500">baseline design (no levers changed)</span>
            ) : (
              leverSummary.map((t) => (
                <Badge key={t} tone="accent">
                  {t}
                </Badge>
              ))
            )}
            {computing && <span className="text-xs text-ink-500">recomputing…</span>}
          </div>

          {(compute.baselineError || compute.currentError) && (
            <ErrorPanel
              title="The engine could not compute this scenario"
              message={compute.currentError ?? compute.baselineError ?? undefined}
              onRetry={compute.retry}
            />
          )}

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5" data-testid="metric-cards">
            {METRICS.map((m) => (
              <MetricCard
                key={m.key}
                def={m}
                current={current?.[m.key] ?? null}
                baseline={baseline?.[m.key] ?? null}
                computing={computing}
                onOpen={() => setDrawer({ kind: "metric", key: m.key })}
              />
            ))}
          </div>

          {(warnings.length > 0 || design.missing_fields.length > 0) && (
            <details className="rounded-xl border border-caution-200 bg-caution-50/70 px-4 py-2.5 text-sm" data-testid="assumption-notes">
              <summary className="cursor-pointer font-semibold text-caution-900">
                {design.missing_fields.length > 0 && `${design.missing_fields.length} missing input${design.missing_fields.length > 1 ? "s" : ""} filled with labelled assumptions`}
                {design.missing_fields.length > 0 && warnings.length > 0 && " · "}
                {warnings.length > 0 && `${warnings.length} engine warning${warnings.length > 1 ? "s" : ""}`}
              </summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-caution-900">
                {design.missing_fields.map((f) => (
                  <li key={`m-${f}`}>
                    <strong>{humanize(f)}</strong>: not available from the source; an assumption is used.{" "}
                    <Link className="link" to={`/?design=${encodeURIComponent(design.id)}#missing`}>
                      Review
                    </Link>
                  </li>
                ))}
                {warnings.map((w) => (
                  <li key={`w-${w}`}>{w}</li>
                ))}
              </ul>
            </details>
          )}

          <ModuleChart baseline={baseline} current={current} onSelectModule={(m) => setDrawer({ kind: "module", module: m })} />

          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <ForecastChart result={current} target={design.enrollment_target} />
            <SupplyPanel result={current} baseline={baseline} strategy={levers.drug_supply_strategy} onOpen={() => setDrawer({ kind: "waste" })} />
          </div>

          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <section className="card p-4" aria-labelledby="sites-title">
              <h2 id="sites-title" className="card-title mb-2">
                Sites — click a dot to exclude or include it
              </h2>
              <SiteMap sites={design.sites} excluded={levers.excluded_site_ids} onToggle={toggleSite} height={300} />
            </section>
            <VersionsPanel
              scenarios={scenarios}
              loading={scenariosLoading}
              selectedId={selectedId}
              onSelect={select}
              onLoadLevers={(s) => {
                if (s.levers) setLevers(s.levers);
                select(s.id);
              }}
              onRefresh={refreshScenarios}
            />
          </div>
        </div>
      </div>

      <ProvenanceDrawer target={drawer} result={current} designId={design.id} designVersion={designVersion} levers={current?.levers ?? levers} onClose={() => setDrawer(null)} />
      <SaveDialog
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        onSave={(n, m) => void save(n, m)}
        base={selected}
        saving={saving}
        ready={canSave}
        defaultName={leverSummary.length ? `Scenario — ${leverSummary.slice(0, 2).join(", ")}` : "Baseline"}
      />
    </div>
  );
}
