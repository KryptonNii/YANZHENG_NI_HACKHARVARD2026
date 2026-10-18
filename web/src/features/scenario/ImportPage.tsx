import { useTranslation } from "@/app/i18n";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { TrialDesign, TrialDesignDrugType, Visit } from "@/app/contracts";
import { ApiError, api, isAbort } from "@/app/api/client";
import type { CachedStudy, DesignRecord, DesignSummary, ImportCtgovResponse, ProtocolExtractionResponse, ProtocolReviewStats } from "@/app/api/types";
import { useHealth } from "@/app/health";
import { setLastDesignId } from "@/app/lastDesign";
import { useToast } from "@/app/toast";
import { Badge, Modal, SectionTitle, Spinner } from "@/app/ui";
import { MissingAssumed } from "./components/MissingAssumed";
import { ProtocolReview } from "./components/ProtocolReview";
import { SiteMap } from "./components/SiteMap";
import { TrialCard } from "./components/TrialCard";
import { nctError, normalizeNct, type DemoTrial } from "./demoTrials";
import { assumptionCount, visibleNotes } from "./importNotes";

const MAX_PDF_BYTES = 20 * 1024 * 1024;

/** A5 refused the save because another version was stored after this one was loaded. */
function onDesignConflict(err: unknown, show: (message: string) => void) {
  if (err instanceof ApiError && err.code === "design_changed") show(err.message);
}

function EditFactsDialog({
  design,
  etag,
  open,
  onClose,
  onSaved,
}: {
  design: TrialDesign;
  etag: string | null;
  open: boolean;
  onClose: () => void;
  onSaved: (rec: DesignRecord) => void;
}) {
  const tr = useTranslation();
  const id = useId();
  const [enrollment, setEnrollment] = useState(String(design.enrollment_target));
  const [duration, setDuration] = useState(String(design.duration_months));
  const [drugType, setDrugType] = useState<TrialDesignDrugType>(design.drug_type);
  const [phase, setPhase] = useState(design.phase ?? "");
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setEnrollment(String(design.enrollment_target));
    setDuration(String(design.duration_months));
    setDrugType(design.drug_type);
    setPhase(design.phase ?? "");
    setConflict(null);
  }, [open, design]);

  // not a <form>, so min={1} is not enforced: an empty or zero value keeps Save disabled
  const valid = [enrollment, duration].every((v) => Number.isFinite(Number(v)) && Number(v) > 0);

  const save = async () => {
    if (!valid) return;
    const e = Number(enrollment);
    const d = Number(duration);
    const changed = new Set<string>();
    if (e !== design.enrollment_target) changed.add("enrollment_target");
    if (d !== design.duration_months) changed.add("duration_months");
    if (drugType !== design.drug_type) changed.add("drug_type");
    if ((phase || null) !== design.phase) changed.add("phase");
    setSaving(true);
    setConflict(null);
    try {
      const updated = await api.saveDesign(
        {
          ...design,
          enrollment_target: Math.round(e),
          duration_months: d,
          drug_type: drugType,
          phase: phase || null,
          // a value a person entered is no longer "missing"
          missing_fields: design.missing_fields.filter((f) => !changed.has(f)),
        },
        { ifMatch: etag ?? undefined },
      );
      onSaved(updated);
      onClose();
    } catch (err) {
      onDesignConflict(err, setConflict);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={tr("Edit trial facts", "编辑试验信息")}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>{tr("Cancel", "取消")}</button>
          <button type="button" className="btn-primary" onClick={() => void save()} disabled={saving || !valid}>
            {saving ? tr("Saving…", "保存中…") : tr("Save changes", "保存修改")}
          </button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor={`${id}-e`}>{tr("Enrollment target", "目标入组人数")}</label>
          <input id={`${id}-e`} className="input mt-1" type="number" min={1} value={enrollment} onChange={(e) => setEnrollment(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor={`${id}-d`}>{tr("Duration (months)", "持续时间（月）")}</label>
          <input id={`${id}-d`} className="input mt-1" type="number" min={1} step={0.5} value={duration} onChange={(e) => setDuration(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor={`${id}-t`}>{tr("Drug type", "药物类型")}</label>
          <select id={`${id}-t`} className="input mt-1" value={drugType} onChange={(e) => setDrugType(e.target.value as TrialDesignDrugType)}>
            <option value="biologic">{tr("Biologic", "生物制剂")}</option>
            <option value="small_molecule">{tr("Small molecule", "小分子药物")}</option>
            <option value="device">{tr("Device", "器械")}</option>
            <option value="none">{tr("None", "无")}</option>
            <option value="unknown">{tr("Unknown", "未知")}</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor={`${id}-p`}>{tr("Phase", "试验分期")}</label>
          <input id={`${id}-p`} className="input mt-1" value={phase} placeholder={tr("e.g. PHASE3", "例如 PHASE3")} onChange={(e) => setPhase(e.target.value)} />
        </div>
      </div>
      {conflict && (
        <p role="alert" className="mt-3 rounded-lg border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900" data-testid="design-conflict">
          {conflict}
        </p>
      )}
    </Modal>
  );
}

export function ImportPage() {
  const tr = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const inputId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const protocolRef = useRef<HTMLElement>(null);

  const [nct, setNct] = useState("");
  const [touched, setTouched] = useState(false);
  const [importing, setImporting] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [design, setDesign] = useState<TrialDesign | null>(null);
  const [designVersion, setDesignVersion] = useState<number | null>(null);
  const [designEtag, setDesignEtag] = useState<string | null>(null);
  const [registryDesign, setRegistryDesign] = useState<TrialDesign | null>(null);
  const [keptStored, setKeptStored] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);
  const [info, setInfo] = useState<ImportCtgovResponse | null>(null);
  const health = useHealth();
  // Only an explicitly offline API should serve cached imports and extractions.
  const liveSources = health.kind !== "ok" || !health.offline;
  const [recent, setRecent] = useState<DesignSummary[]>([]);
  const [cached, setCached] = useState<CachedStudy[]>([]);
  const [editOpen, setEditOpen] = useState(false);
  const [extraction, setExtraction] = useState<ProtocolExtractionResponse | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const designParam = search.get("design");

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .listDesigns({ signal: ctrl.signal, silent: true })
      .then((ds) => setRecent(ds.slice(0, 6)))
      .catch(() => setRecent([]));
    return () => ctrl.abort();
  }, [design?.id]);

  useEffect(() => {
    if (health.kind !== "ok") return;
    const ctrl = new AbortController();
    api
      .cachedStudies({ signal: ctrl.signal, silent: true })
      .then(setCached)
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [health.kind]);

  useEffect(() => {
    if (!designParam || design?.id === designParam) return;
    const ctrl = new AbortController();
    api
      .getDesign(designParam, { signal: ctrl.signal })
      .then((rec) => {
        setDesign(rec.design);
        setDesignVersion(rec.version);
        setDesignEtag(rec.etag);
        setRegistryDesign(null);
        setKeptStored(false);
        setInfo(null);
      })
      .catch((err) => {
        if (!isAbort(err)) setSearch({}, { replace: true });
      });
    return () => ctrl.abort();
  }, [designParam, design?.id, setSearch]);

  useEffect(() => {
    if (design && window.location.hash === "#missing") document.getElementById("missing")?.scrollIntoView();
  }, [design]);

  const showRecord = useCallback(
    (rec: DesignRecord) => {
      setDesign(rec.design);
      setDesignVersion(rec.version);
      setDesignEtag(rec.etag);
      setLastDesignId(rec.design.id);
      setSearch({ design: rec.design.id }, { replace: true });
    },
    [setSearch],
  );

  /** A version this page just stored replaces the shown design and the "already saved" banner. */
  const adoptSaved = (rec: DesignRecord) => {
    showRecord(rec);
    setKeptStored(false);
  };

  const runImport = async (raw: string) => {
    const id = normalizeNct(raw);
    const err = nctError(id);
    setTouched(true);
    if (err) {
      setImportError(null);
      return;
    }
    setImporting(id);
    setImportError(null);
    setConflict(null);
    setExtraction(null);
    try {
      const res = await api.importCtgov(id, { silent: true, refresh: liveSources });
      const imported = { ...res.design, missing_fields: res.missing_fields.length ? res.missing_fields : res.design.missing_fields };
      let record: DesignRecord;
      let kept = false;
      try {
        record = await api.getDesign(imported.id, { silent: true });
        kept = true;
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 404)) throw e;
        record = await api.saveDesign(imported);
      }
      setInfo(res);
      setRegistryDesign(imported);
      setKeptStored(kept);
      showRecord(record);
      toast.push(
        "success",
        kept ? tr(`Opened saved ${id}`, `已打开已保存的 ${id}`) : tr(`Imported ${id}`, `已导入 ${id}`),
        tr(`Design v${record.version}`, `设计 v${record.version}`),
      );
    } catch (e) {
      setImportError(e instanceof Error ? e.message : String(e));
    } finally {
      setImporting(null);
    }
  };

  /** Uploaded PDF or registry protocol → AI candidates for review. Never throws. */
  const runExtraction = async (src: { file?: File; nctId?: string }) => {
    setExtractError(null);
    setExtracting(true);
    setExtraction(null);
    try {
      setExtraction(await api.importProtocol({ ...src, refresh: liveSources }, design?.id, { silent: true }));
    } catch (e) {
      setExtractError(e instanceof Error ? e.message : String(e));
    } finally {
      setExtracting(false);
    }
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setExtractError(null);
    if (file.type && file.type !== "application/pdf") {
      setExtractError(tr("Please choose a PDF file.", "请选择 PDF 文件。"));
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setExtractError(tr("The PDF is larger than 20 MB.", "PDF 文件超过 20 MB。"));
      return;
    }
    await runExtraction({ file });
    if (fileRef.current) fileRef.current.value = "";
  };

  const extractFromRegistry = async () => {
    if (!design?.registry_id) return;
    await runExtraction({ nctId: design.registry_id });
  };

  const applyExtraction = async (visits: Visit[], stats: ProtocolReviewStats) => {
    if (!design) return;
    setApplying(true);
    setConflict(null);
    try {
      // A4 validates the confirmed schedule (weeks increasing, unique numbers) and audits it; A5 stores the new version
      const applied = await api.applyProtocol(design, visits, extraction?.extraction_id ?? null);
      const updated = await api.saveDesign(applied, { ifMatch: designEtag ?? undefined });
      const reviewId = extraction?.extraction_id;
      adoptSaved(updated);
      setExtraction(null);
      toast.push(
        "success",
        tr(`Applied ${visits.length} visits to the design`, `已将 ${visits.length} 次访视应用到设计`),
        tr(`${stats.accepted} accepted · ${stats.edited} edited · ${stats.rejected} rejected · design v${updated.version}`, `${stats.accepted} 项已接受 · ${stats.edited} 项已编辑 · ${stats.rejected} 项已拒绝 · 设计 v${updated.version}`),
      );
      if (reviewId) {
        try {
          await api.logProtocolReview({ extraction_id: reviewId, design_id: design.id, ...stats }, { silent: true });
        } catch {
          toast.push("error", tr("Design saved, but review counts were not recorded", "设计已保存，但审阅计数未记录"), tr("The protocol schedule is saved. Extraction review statistics are unavailable for this application.", "方案访视计划已保存。本次应用的提取审阅统计不可用。"));
        }
      }
    } catch (err) {
      onDesignConflict(err, setConflict);
    } finally {
      setApplying(false);
    }
  };

  const reimportRegistry = async () => {
    if (!registryDesign || !designEtag) return;
    setConflict(null);
    setImporting(registryDesign.registry_id);
    try {
      const updated = await api.saveDesign(registryDesign, { ifMatch: designEtag });
      adoptSaved(updated);
      toast.push("success", tr(`Stored the registry copy as design v${updated.version}`, `已将注册平台副本保存为设计 v${updated.version}`));
    } catch (err) {
      onDesignConflict(err, setConflict);
    } finally {
      setImporting(null);
    }
  };

  const validation = touched ? nctError(nct) : null;
  const chips: DemoTrial[] = cached.map((c) => ({
    registryId: c.nct_id,
    label: [c.acronym ?? c.title.slice(0, 40), c.phase, c.sites ? tr(`${c.sites} sites`, `${c.sites} 个研究中心`) : null].filter(Boolean).join(" · "),
    note: [c.title, c.sponsor && tr(`Sponsor: ${c.sponsor}`, `申办方：${c.sponsor}`)].filter(Boolean).join(" — "),
  }));
  const notes = visibleNotes(design?.missing_fields ?? [], info?.notes ?? []);
  const assumedTotal = assumptionCount(design?.missing_fields ?? [], info?.notes ?? []);
  const registryDiffers =
    !!registryDesign &&
    !!design &&
    (registryDesign.visits.length !== design.visits.length ||
      registryDesign.missing_fields.join("|") !== design.missing_fields.join("|") ||
      registryDesign.enrollment_target !== design.enrollment_target);
  const registryProtocol = info?.documents.find((d) => d.has_protocol) ?? null;

  return (
    <div className="space-y-6">
      <section>
        <div className="pt-2">
          <h1 className="text-3xl font-bold tracking-tight text-ink-900">{tr("Trial workspace", "试验管理")}</h1>

          <form
            className="mt-6"
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              void runImport(nct);
            }}
          >
            <label htmlFor={inputId} className="label">{tr("ClinicalTrials.gov ID", "ClinicalTrials.gov 注册编号")}</label>
            <div className="mt-1 flex gap-2">
              <input
                id={inputId}
                className={`input max-w-xs font-mono text-base uppercase ${validation ? "border-worse-500" : ""}`}
                placeholder="NCT01234567"
                value={nct}
                onChange={(e) => setNct(e.target.value)}
                onBlur={() => nct && setTouched(true)}
                aria-invalid={validation ? true : undefined}
                aria-describedby={`${inputId}-help`}
                data-testid="nct-input"
                autoComplete="off"
                spellCheck={false}
              />
              <button type="submit" className="btn-primary px-5" disabled={importing !== null} data-testid="nct-submit">
                {importing ? tr("Importing…", "导入中…") : tr("Import", "导入")}
              </button>
            </div>
            <p id={`${inputId}-help`} className={`mt-1.5 text-sm ${validation ? "font-medium text-worse-700" : "text-ink-500"}`} role={validation ? "alert" : undefined}>
              {validation ?? tr("NCT + 8 digits", "NCT + 8 位数字")}
            </p>
            {importError && (
              <p role="alert" className="mt-2 rounded-lg border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900" data-testid="import-error">
                {importError}
              </p>
            )}
          </form>

          {(chips.length > 0 || recent.length > 0) && (
            <div className="mt-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">{chips.length ? tr("Trial library", "试验库") : tr("Recent trials", "最近试验")}</p>
              <div className="mt-2 flex flex-wrap gap-2" data-testid={chips.length ? "demo-chips" : "recent-trials"}>
                {chips.map((t) => (
                  <button
                    key={t.registryId}
                    type="button"
                    className="btn-secondary rounded-full py-1.5"
                    onClick={() => {
                      setNct(t.registryId);
                      void runImport(t.registryId);
                    }}
                    disabled={importing !== null}
                    title={t.note}
                  >
                    <span className="whitespace-nowrap font-mono text-xs text-ink-500">{t.registryId}</span> {t.label}
                  </button>
                ))}
                {recent
                  .filter((d) => !chips.some((t) => t.registryId === d.registry_id))
                  .map((d) => (
                    <button
                      key={d.id}
                      type="button"
                      className="btn-secondary max-w-xs rounded-full py-1.5"
                      onClick={() => {
                        api
                          .getDesign(d.id)
                          .then((full) => {
                            setInfo(null);
                            setExtraction(null);
                            setRegistryDesign(null);
                            setKeptStored(false);
                            setConflict(null);
                            showRecord(full);
                          })
                          .catch(() => undefined);
                      }}
                      title={d.title}
                    >
                      {d.registry_id && <span className="whitespace-nowrap font-mono text-xs text-ink-500">{d.registry_id}</span>}
                      <span className="truncate">{d.title}</span>
                    </button>
                  ))}
              </div>
            </div>
          )}
          {importing && <Spinner className="mt-4" label={tr(`Importing ${importing}…`, `正在导入 ${importing}…`)} />}
        </div>

      </section>

      {design && (
        <>
          <TrialCard design={design} info={info} onEdit={() => setEditOpen(true)} />
          <div className="flex flex-wrap items-center gap-3 text-sm text-ink-600">
            {designVersion != null && <p data-testid="import-design-version"><strong>{tr("design v", "设计 v")}{designVersion}</strong></p>}
            {keptStored && <span data-testid="stored-design-banner">{tr("Saved", "已保存")}</span>}
            {keptStored && registryDiffers && designEtag && (
              <button type="button" className="btn-secondary py-1 text-xs" onClick={() => void reimportRegistry()} disabled={importing !== null} data-testid="reimport-registry">{tr("Re-import registry", "重新导入")}</button>
            )}
          </div>
          {conflict && (
            <p role="alert" className="rounded-lg border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900" data-testid="design-conflict">
              {conflict}
            </p>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent-200 bg-accent-50 px-5 py-3">
            <p className="text-sm text-accent-900">
              <strong>{design.visits.length}{tr(" visits", " 次访视")}</strong>{" · "}<strong>{design.sites.length}{tr(" sites", " 个研究中心")}</strong>{assumedTotal > 0 && tr(` · ${assumedTotal} pending inputs`, ` · ${assumedTotal} 项待确认`)}
            </p>
            <button type="button" className="btn-primary px-5" onClick={() => navigate(`/scenario/${encodeURIComponent(design.id)}`)} data-testid="open-simulator">{tr("Scenario analysis →", "方案分析 →")}</button>
          </div>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <details className="card self-start p-5" id="missing" aria-labelledby="missing-title">
              <summary className="cursor-pointer font-semibold text-ink-900">
                <span id="missing-title" className="mr-2">{tr("Pending inputs", "待确认项目")}</span>
                <Badge tone="caution"><span data-testid="missing-count">{assumedTotal}</span></Badge>
              </summary>
              <MissingAssumed
                missing={design.missing_fields}
                notes={notes}
                onEdit={() => setEditOpen(true)}
                onProtocol={() => protocolRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
              />
            </details>
            <section className="card p-5" aria-labelledby="map-title">
              <SectionTitle>
                <span id="map-title">{tr("Sites", "研究中心")}</span>
              </SectionTitle>
              <SiteMap sites={design.sites} />
            </section>
          </div>
        </>
      )}

      <section ref={protocolRef} className="card p-5" aria-labelledby="protocol-title" id="protocol">
        <SectionTitle>
          <span id="protocol-title">{tr("Visit schedule", "访视计划")}</span>
        </SectionTitle>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="btn-secondary cursor-pointer">
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              onChange={(e) => void onFile(e.target.files?.[0])}
              data-testid="protocol-file"
            />{tr("Upload protocol", "上传方案")}</label>
          {design?.registry_id && (registryProtocol || design.registry_id.startsWith("NCT")) && (
            <button type="button" className="btn-secondary" onClick={() => void extractFromRegistry()} disabled={extracting} data-testid="extract-registry">{tr("Extract registry protocol", "提取注册方案")}
            </button>
          )}
          <span className="text-xs text-ink-500">PDF ≤ 20 MB</span>
          {extracting && <Spinner label={tr("Extracting…", "提取中…")} />}
        </div>
        {extractError && (
          <p role="alert" className="mt-3 rounded-lg border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900">
            {extractError}
          </p>
        )}
        {extraction && (
          <div className="mt-4">
            <details className="mb-3 text-xs text-ink-500">
              <summary className="cursor-pointer font-semibold">{tr("Extraction details", "提取详情")}</summary>
              <p className="mt-2" data-testid="extraction-meta">
                {[
                  extraction.method && tr(`Method: ${extraction.method}`, `方法：${extraction.method}`),
                  extraction.model && tr(`model: ${extraction.model}`, `模型：${extraction.model}`),
                  extraction.soa_pages.length
                    ? tr(`schedule on pages ${extraction.soa_pages[0]}–${extraction.soa_pages[extraction.soa_pages.length - 1]}${extraction.page_count ? ` of ${extraction.page_count}` : ""}`, `计划位于第 ${extraction.soa_pages[0]}–${extraction.soa_pages[extraction.soa_pages.length - 1]} 页${extraction.page_count ? `，共 ${extraction.page_count} 页` : ""}`)
                    : null,
                  extraction.from_cache ? tr("served from cache", "来自缓存") : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              {extraction.notice && <p className="mt-2 text-caution-900">{extraction.notice}</p>}
              {extraction.excluded_columns.length > 0 && (
                <details className="mt-2 text-ink-600">
                  <summary className="cursor-pointer font-semibold">{tr("Excluded columns", "排除列")} ({extraction.excluded_columns.length})</summary>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {extraction.excluded_columns.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </details>
              )}
            </details>
            {extraction.candidates.length === 0 ? (
              <p className="text-sm text-ink-600">{tr("No schedule of activities was found in this PDF.", "此 PDF 中未找到活动计划。")}</p>
            ) : (
              <ProtocolReview
                key={extraction.candidates.length + (extraction.candidates[0]?.quote ?? "")}
                candidates={extraction.candidates}
                warnings={extraction.warnings}
                canApply={design !== null}
                applying={applying}
                onApply={(v, s) => void applyExtraction(v, s)}
              />
            )}
          </div>
        )}
      </section>

      {design && (
        <EditFactsDialog
          design={design}
          etag={designEtag}
          open={editOpen}
          onClose={() => setEditOpen(false)}
          onSaved={adoptSaved}
        />
      )}
    </div>
  );
}
