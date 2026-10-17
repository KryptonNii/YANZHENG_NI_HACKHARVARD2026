import { useTranslation } from "@/app/i18n";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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
      <p className="mt-3 text-xs text-ink-500">{tr("Edits are saved as a new design version and recorded in the audit trail. The save is refused if someone else stored a version after this one was loaded.", "修改将保存为新的设计版本并记录在审计追踪中。如果其他人在此版本加载后保存了新版本，本次保存将被拒绝。")}</p>
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
      const res = await api.importCtgov(id, { silent: true });
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
        kept ? tr(`Design v${record.version} is already stored`, `设计 v${record.version} 已保存`) : res.raw_cached ? tr("Served from the local cache and saved", "已从本地缓存读取并保存") : tr("Saved for the simulator", "已保存，可用于模拟器"),
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
      setExtraction(await api.importProtocol(src, design?.id, { silent: true }));
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
      <section className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="pt-2">
          <h1 className="text-3xl font-bold tracking-tight text-ink-900">{tr("Plan a trial you can defend", "规划有据可依的临床试验")}</h1>
          <p className="mt-2 max-w-xl text-base text-ink-600">{tr("Import a real trial, flip design levers and see cost, site staff time, patient travel, timeline and carbon move — each as a P10–P90 range with its formula and sources.", "导入真实试验，调整设计选项，查看成本、研究中心人力、患者出行、时间线和碳排放的变化，每项均展示 P10–P90 区间、计算公式与来源。")}</p>

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
              {validation ?? tr("NCT followed by 8 digits. Registry data is real; anything missing is flagged and filled with a labelled assumption.", "NCT 后接 8 位数字。使用真实注册数据；缺失项会明确标注，并以已标注的假设值填补。")}
            </p>
            {importError && (
              <p role="alert" className="mt-2 rounded-lg border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900" data-testid="import-error">
                {importError}
              </p>
            )}
          </form>

          {(chips.length > 0 || recent.length > 0) && (
            <div className="mt-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">{chips.length ? tr("Demo trials (cached — work offline)", "演示试验（已缓存，可离线使用）") : tr("Recent trials", "最近的试验")}</p>
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
          {importing && <Spinner className="mt-4" label={tr(`Fetching ${importing} from ClinicalTrials.gov (or the cache)`, `正在从 ClinicalTrials.gov 或缓存获取 ${importing}`)} />}
        </div>

        <aside className="card self-start p-5" aria-labelledby="how-title">
          <h2 id="how-title" className="card-title">{tr("How it works", "使用流程")}</h2>
          <ol className="mt-3 space-y-3 text-sm text-ink-700">
            <li><strong className="text-ink-900">{tr("1. Import.", "1. 导入。")}</strong>{tr(" Sites, enrollment, phase and dates come from the registry. The visit schedule comes from the protocol (AI-extracted, you confirm every row) or a labelled template.", "研究中心、入组人数、分期和日期来自注册平台。访视计划来自试验方案（由 AI 提取，需逐行确认）或明确标注的模板。")}</li>
            <li><strong className="text-ink-900">{tr("2. Simulate.", "2. 模拟。")}</strong>{tr(" Remote monitoring, home or telehealth visits, local labs, on-demand drug supply, fewer procedures or sites.", "调整远程监查、居家或远程医疗访视、本地实验室、按需药物供应，或减少检查项目与研究中心。")}</li>
            <li><strong className="text-ink-900">{tr("3. Defend.", "3. 论证。")}</strong>{tr(" Click any number for its formula, parameters and sources. Save, compare and send for e-signed approval.", "点击任意数值查看公式、参数和来源。保存、比较方案，并提交电子签名审批。")}</li>
          </ol>
        </aside>
      </section>

      {design && (
        <>
          <TrialCard design={design} info={info} onEdit={() => setEditOpen(true)} />
          {designVersion != null && (
            <p className="text-sm text-ink-600" data-testid="import-design-version">{tr("Saved as ", "已保存为")}<strong>{tr("design v", "设计 v")}{designVersion}</strong>{tr(". The simulator computes and saves against this version.", "。模拟器将基于此版本计算和保存。")}</p>
          )}
          {keptStored && (
            <div className="rounded-xl border border-ink-200 bg-ink-50 px-5 py-3 text-sm text-ink-800" data-testid="stored-design-banner">
              <p>{tr("This trial was already saved", "该试验已保存")}{designVersion != null ? tr(` as design v${designVersion}`, `为设计 v${designVersion}`) : ""}{tr(". That copy is shown, including a protocol schedule if one was confirmed. The registry response is not written over it.", "。当前显示已保存的副本，包括已确认的方案访视计划。注册平台的响应不会覆盖它。")}</p>
              {registryDiffers && designEtag && (
                <button type="button" className="btn-secondary mt-2" onClick={() => void reimportRegistry()} disabled={importing !== null} data-testid="reimport-registry">{tr("Re-import from registry", "从注册平台重新导入")}</button>
              )}
            </div>
          )}
          {conflict && (
            <p role="alert" className="rounded-lg border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900" data-testid="design-conflict">
              {conflict}
            </p>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent-200 bg-accent-50 px-5 py-3">
            <p className="text-sm text-accent-900">
              <strong>{design.visits.length}{tr(" visits", "次访视")}</strong>{tr(" and ", "和")}<strong>{design.sites.length}{tr(" sites", "个研究中心")}</strong>{tr(" ready.", "已就绪。")}{design.missing_fields.length > 0 && tr(` ${design.missing_fields.length} input(s) use labelled assumptions.`, ` ${design.missing_fields.length} 项输入使用已标注的假设。`)}
            </p>
            <button type="button" className="btn-primary px-5" onClick={() => navigate(`/scenario/${encodeURIComponent(design.id)}`)} data-testid="open-simulator">{tr("Open scenario simulator & peer comparison →", "打开方案模拟器与同类试验比较 →")}</button>
          </div>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <section className="card p-5" id="missing" aria-labelledby="missing-title">
              <SectionTitle aside={<Badge tone="caution"><span data-testid="missing-count">{assumedTotal}</span></Badge>}>
                <span id="missing-title">{tr("Missing & assumed", "缺失项与假设")}</span>
              </SectionTitle>
              <MissingAssumed
                missing={design.missing_fields}
                notes={notes}
                onEdit={() => setEditOpen(true)}
                onProtocol={() => protocolRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
              />
            </section>
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
          <span id="protocol-title">{tr("Protocol PDF → schedule of activities", "试验方案 PDF → 活动计划")}</span>
        </SectionTitle>
        <p className="max-w-3xl text-sm text-ink-600">{tr("Upload the trial protocol to extract visits and procedures. Extraction is done by an AI model and returned as candidates with the page number and a short quote; nothing is applied until you accept rows and press “Apply to design”.", "上传试验方案以提取访视和检查项目。AI 模型将返回附带页码和简短引文的候选项；只有在您接受相应行并点击“应用到设计”后才会生效。")}</p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="btn-secondary cursor-pointer">
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              onChange={(e) => void onFile(e.target.files?.[0])}
              data-testid="protocol-file"
            />{tr("Choose protocol PDF…", "选择试验方案 PDF…")}</label>
          {design?.registry_id && (registryProtocol || design.registry_id.startsWith("NCT")) && (
            <button type="button" className="btn-secondary" onClick={() => void extractFromRegistry()} disabled={extracting} data-testid="extract-registry">{tr("Use the registry protocol", "使用注册平台中的试验方案")}{registryProtocol?.extraction_cached ? tr(" (cached extraction)", "（已缓存的提取结果）") : ""}
            </button>
          )}
          <span className="text-xs text-ink-500">{tr("PDF up to 20 MB", "PDF 最大 20 MB")}{design ? tr(` · will be applied to ${design.registry_id ?? "this design"}`, ` · 将应用到 ${design.registry_id ?? "此设计"}`) : tr(" · import the trial first to apply results", " · 请先导入试验以应用结果")}</span>
          {extracting && <Spinner label={tr("Extracting schedule (this can take ~30 s)", "正在提取计划（约需 30 秒）")} />}
        </div>
        {extractError && (
          <p role="alert" className="mt-3 rounded-lg border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900">
            {extractError}
          </p>
        )}
        {extraction && (
          <div className="mt-4">
            <p className="mb-2 text-xs text-ink-500" data-testid="extraction-meta">
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
            {extraction.notice && <p className="mb-2 text-xs text-caution-900">{extraction.notice}</p>}
            {extraction.excluded_columns.length > 0 && (
              <details className="mb-3 text-xs text-ink-600">
                <summary className="cursor-pointer font-semibold">{tr("Columns the extractor left out (", "提取时排除的列（")}{extraction.excluded_columns.length})</summary>
                <ul className="mt-1 list-disc space-y-0.5 pl-5">
                  {extraction.excluded_columns.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </details>
            )}
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
      {!design && recent.length === 0 && (
        <p className="text-center text-sm text-ink-500">{tr("New here? Read ", "首次使用？了解")}<Link className="link" to="/about">{tr("how TrialPilot calculates", "TrialPilot 的计算方法")}</Link>.
        </p>
      )}
    </div>
  );
}
