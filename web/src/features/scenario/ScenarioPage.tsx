import { useTranslation, translate as tr } from "@/app/i18n";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import type { Levers, TrialDesign } from "@/app/contracts";
import { ApiError, api, isAbort } from "@/app/api/client";
import { DEFAULT_LEVERS } from "@/app/api/normalize";
import type { SavedScenario } from "@/app/api/types";
import { humanize } from "@/app/format";
import { localizeCopy } from "@/app/localize";
import { setLastDesignId } from "@/app/lastDesign";
import { useToast } from "@/app/toast";
import { Badge, ErrorPanel, Modal, Skeleton } from "@/app/ui";
import { ForecastChart } from "./components/ForecastChart";
import { LeversPanel } from "./components/LeversPanel";
import { MetricCard } from "./components/MetricCard";
import { ModuleChart } from "./components/ModuleChart";
import { NextLever } from "./components/NextLever";
import { PeerMirror } from "./components/PeerMirror";
import { ProvenanceDrawer, type ProvenanceTarget } from "./components/ProvenanceDrawer";
import { SiteMap } from "./components/SiteMap";
import { SupplyPanel } from "./components/SupplyPanel";
import { VersionsPanel } from "./components/VersionsPanel";
import { useScenarioCompute } from "./hooks/useScenarioCompute";
import { METRICS } from "./metrics";

function describeLevers(l: Levers, localize = tr): string[] {
  const out: string[] = [];
  if (l.remote_monitoring_share > 0) out.push(localize(`${Math.round(l.remote_monitoring_share * 100)}% remote monitoring`, `${Math.round(l.remote_monitoring_share * 100)}% 远程监查`));
  if (l.home_visit_numbers.length) out.push(localize(`${l.home_visit_numbers.length} home visit${l.home_visit_numbers.length > 1 ? "s" : ""}`, `${l.home_visit_numbers.length} 次居家访视`));
  if (l.remote_visit_numbers.length) out.push(localize(`${l.remote_visit_numbers.length} telehealth visit${l.remote_visit_numbers.length > 1 ? "s" : ""}`, `${l.remote_visit_numbers.length} 次远程医疗访视`));
  if (l.local_lab_share > 0) out.push(localize(`${Math.round(l.local_lab_share * 100)}% local labs`, `${Math.round(l.local_lab_share * 100)}% 本地实验室`));
  if (l.drug_supply_strategy === "on_demand") out.push(localize("on-demand supply", "按需供应"));
  if (l.removed_procedures.length) out.push(localize(`${l.removed_procedures.length} procedure${l.removed_procedures.length > 1 ? "s" : ""} removed`, `已移除 ${l.removed_procedures.length} 项检查`));
  if (l.excluded_site_ids.length) out.push(localize(`${l.excluded_site_ids.length} site${l.excluded_site_ids.length > 1 ? "s" : ""} excluded`, `已排除 ${l.excluded_site_ids.length} 个研究中心`));
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
  const tr = useTranslation();
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
      title={tr("Save scenario", "保存方案")}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>{tr("Cancel", "取消")}</button>
          <button type="submit" form={`${id}-form`} className="btn-primary" disabled={saving || !ready || !name.trim()} data-testid="save-confirm">
            {saving ? tr("Saving…", "保存中…") : mode === "version" && base ? tr(`Save as v${base.version + 1}`, `保存为 v${base.version + 1}`) : tr("Save", "保存")}
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
            <legend className="label mb-1">{tr("Save as", "保存为")}</legend>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name={`${id}-mode`} className="mt-0.5 accent-accent-700" checked={mode === "version"} onChange={() => setMode("version")} />
              <span>{tr("New version of ", "新版本：")}<strong>{localizeCopy(base.name)}</strong> (v{base.version} → v{base.version + 1})
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="radio" name={`${id}-mode`} className="mt-0.5 accent-accent-700" checked={mode === "new"} onChange={() => setMode("new")} data-testid="save-mode-new" />
              <span>{tr("New scenario", "新方案")}</span>
            </label>
          </fieldset>
        )}
        <label htmlFor={id} className="label">{tr("Name", "名称")}</label>
        <input id={id} className="input mt-1" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} data-testid="save-name" />
        <p className="mt-2 text-xs text-ink-500">{tr("Save current settings and forecast as a draft.", "将当前参数与测算结果保存为草稿。")}</p>
      </form>
    </Modal>
  );
}

function TrialHeader({ design, version }: { design: TrialDesign; version: number | null }) {
  const tr = useTranslation();
  const countries = new Set(design.sites.map((s) => s.country)).size;
  const shortTitle = /^([A-Z][A-Z0-9-]{2,24})\s*:/.exec(design.title)?.[1] ?? design.title;
  return (
    <div className="min-w-0">
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">{tr("Scenario analysis", "方案分析")}{design.registry_id && (
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
        {shortTitle}
      </h1>
      <div className="mt-1.5 flex flex-wrap gap-1.5 text-xs">
        {design.phase && <Badge>{design.phase}</Badge>}
        <Badge>{design.sites.length}{tr(" sites · ", "个研究中心 ·")}{countries}{tr(" countries", "个国家")}</Badge>
        <Badge>{design.enrollment_target.toLocaleString("en-US")}{tr(" patients", "名患者")}</Badge>
        <Badge>{design.duration_months}{tr(" months planned", "个月计划周期")}</Badge>
        <Badge>{humanize(design.drug_type)}</Badge>
        <Badge>{design.visits.length}{tr(" visits", "次访视")}</Badge>
        {version != null && (
          <Badge>
            <span data-testid="design-version">{tr("design v", "设计 v")}{version}</span>
          </Badge>
        )}
      </div>
    </div>
  );
}

export function ScenarioPage() {
  const tr = useTranslation();
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
      toast.push("success", tr(`Saved “${s.name}” v${s.version}`, `已保存“${localizeCopy(s.name)}”v${s.version}`));
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

  const leverSummary = useMemo(() => describeLevers(levers, tr), [levers, tr]);
  const defaultLeverSummary = describeLevers(levers, (english) => english);
  const warnings = current?.warnings ?? baseline?.warnings ?? [];

  if (designError) {
    const notFound = designError instanceof ApiError && designError.status === 404;
    return (
      <div className="mx-auto max-w-2xl pt-6">
        <ErrorPanel
          title={notFound ? tr("This trial design was not found", "未找到此试验设计") : tr("Could not load the trial design", "无法加载试验设计")}
          message={designError.message}
          onRetry={notFound ? undefined : () => setReloadKey((k) => k + 1)}
        />
        <Link to="/" className="btn-secondary mt-4">{tr("Import a trial", "导入试验")}</Link>
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
          <Link to={`/?design=${encodeURIComponent(design.id)}`} className="btn-ghost">{tr("Trial details", "试验详情")}</Link>
          <button type="button" className="btn-primary" disabled={!canSave || saving} onClick={() => setSaveOpen(true)} data-testid="save-scenario">{tr("Save scenario", "保存方案")}</button>
        </div>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-[7.5rem] lg:max-h-[calc(100vh-8.5rem)] lg:overflow-y-auto">
          <LeversPanel design={design} levers={levers} onChange={setLevers} />
        </div>

        <div className="min-w-0 space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm" aria-live="polite">
            <span className="font-semibold text-ink-700">{tr("Impact forecast · vs baseline", "影响测算 · 相对基线")}</span>
            {leverSummary.length === 0 ? (
              <span className="text-ink-500">{tr("Baseline", "基线方案")}</span>
            ) : (
              leverSummary.map((t) => (
                <Badge key={t} tone="accent">
                  {t}
                </Badge>
              ))
            )}
            {computing && <span className="text-xs text-ink-500">{tr("recomputing…", "重新计算中…")}</span>}
          </div>

          {(compute.baselineError || compute.currentError) && (
            <ErrorPanel
              title={tr("The engine could not compute this scenario", "引擎无法计算此方案")}
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

          {designVersion !== null && (
            <>
              <PeerMirror designId={design.id} designVersion={designVersion} removedProcedures={levers.removed_procedures} />
              <NextLever
                designId={design.id}
                designVersion={designVersion}
                currentLevers={levers}
                onPreview={(patch) => setLevers((currentLevers) => ({ ...currentLevers, ...patch }))}
              />
            </>
          )}

          {(warnings.length > 0 || design.missing_fields.length > 0) && (
            <details className="rounded-xl border border-caution-200 bg-caution-50/70 px-4 py-2.5 text-sm" data-testid="assumption-notes">
              <summary className="cursor-pointer font-semibold text-caution-900">
                {design.missing_fields.length > 0 && tr(`${design.missing_fields.length} inputs to confirm`, `${design.missing_fields.length} 项输入待确认`)}
                {design.missing_fields.length > 0 && warnings.length > 0 && " · "}
                {warnings.length > 0 && tr(`${warnings.length} calculation notes`, `${warnings.length} 项测算提示`)}
              </summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-caution-900">
                {design.missing_fields.map((f) => (
                  <li key={`m-${f}`}>
                    <strong>{humanize(f)}</strong>{tr(": planning value; source confirmation required.", "：使用规划值，待来源确认。")}{" "}
                    <Link className="link" to={`/?design=${encodeURIComponent(design.id)}#missing`}>{tr("Review", "查看")}</Link>
                  </li>
                ))}
                {warnings.map((w) => (
                  <li key={`w-${w}`}>{localizeCopy(w)}</li>
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
              <h2 id="sites-title" className="card-title mb-2">{tr("Site network", "研究中心布局")}</h2>
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
        defaultName={defaultLeverSummary.length ? `Scenario — ${defaultLeverSummary.slice(0, 2).join(", ")}` : "Baseline"}
      />
    </div>
  );
}
