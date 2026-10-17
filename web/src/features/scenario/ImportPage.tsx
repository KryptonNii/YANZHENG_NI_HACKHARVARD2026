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
import { DEMO_TRIALS, nctError, normalizeNct, type DemoTrial } from "./demoTrials";
import { assumptionCount, visibleNotes } from "./importNotes";

const MAX_PDF_BYTES = 20 * 1024 * 1024;

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

  const save = async () => {
    const e = Number(enrollment);
    const d = Number(duration);
    if (!Number.isFinite(e) || e <= 0 || !Number.isFinite(d) || d <= 0) return;
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
      if (err instanceof ApiError && err.code === "design_changed") setConflict(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Edit trial facts"
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={() => void save()} disabled={saving}>
            {saving ? "Saving…" : "Save changes"}
          </button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="label" htmlFor={`${id}-e`}>Enrollment target</label>
          <input id={`${id}-e`} className="input mt-1" type="number" min={1} value={enrollment} onChange={(e) => setEnrollment(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor={`${id}-d`}>Duration (months)</label>
          <input id={`${id}-d`} className="input mt-1" type="number" min={1} step={0.5} value={duration} onChange={(e) => setDuration(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor={`${id}-t`}>Drug type</label>
          <select id={`${id}-t`} className="input mt-1" value={drugType} onChange={(e) => setDrugType(e.target.value as TrialDesignDrugType)}>
            <option value="biologic">Biologic</option>
            <option value="small_molecule">Small molecule</option>
            <option value="device">Device</option>
            <option value="none">None</option>
            <option value="unknown">Unknown</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor={`${id}-p`}>Phase</label>
          <input id={`${id}-p`} className="input mt-1" value={phase} placeholder="e.g. PHASE3" onChange={(e) => setPhase(e.target.value)} />
        </div>
      </div>
      <p className="mt-3 text-xs text-ink-500">Edits are saved as a new design version and recorded in the audit trail. The save is refused if someone else stored a version after this one was loaded.</p>
      {conflict && (
        <p role="alert" className="mt-3 rounded-lg border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900" data-testid="design-conflict">
          {conflict}
        </p>
      )}
    </Modal>
  );
}

export function ImportPage() {
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
      setInfo({ ...res, design: record.design, missing_fields: record.design.missing_fields });
      setRegistryDesign(imported);
      setKeptStored(kept);
      showRecord(record);
      toast.push(
        "success",
        kept ? `Opened saved ${id}` : `Imported ${id}`,
        kept ? `Design v${record.version} is already stored` : res.raw_cached ? "Served from the local cache and saved" : "Saved for the simulator",
      );
    } catch (e) {
      setImportError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setImporting(null);
    }
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setExtractError(null);
    if (file.type && file.type !== "application/pdf") {
      setExtractError("Please choose a PDF file.");
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setExtractError("The PDF is larger than 20 MB.");
      return;
    }
    setExtracting(true);
    setExtraction(null);
    try {
      setExtraction(await api.importProtocol({ file }, design?.id, { silent: true }));
    } catch (e) {
      setExtractError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setExtracting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const extractFromRegistry = async () => {
    if (!design?.registry_id) return;
    setExtractError(null);
    setExtracting(true);
    setExtraction(null);
    try {
      setExtraction(await api.importProtocol({ nctId: design.registry_id }, design.id, { silent: true }));
    } catch (e) {
      setExtractError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setExtracting(false);
    }
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
      showRecord(updated);
      setKeptStored(false);
      setInfo((i) => (i ? { ...i, missing_fields: updated.design.missing_fields, design: updated.design } : i));
      setExtraction(null);
      toast.push(
        "success",
        `Applied ${visits.length} visits to the design`,
        `${stats.accepted} accepted · ${stats.edited} edited · ${stats.rejected} rejected · design v${updated.version}`,
      );
      if (reviewId) {
        try {
          await api.logProtocolReview({ extraction_id: reviewId, design_id: design.id, ...stats }, { silent: true });
        } catch {
          toast.push("error", "Design saved, but review counts were not recorded", "The protocol schedule is saved. Extraction review statistics are unavailable for this application.");
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === "design_changed") setConflict(err.message);
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
      showRecord(updated);
      setKeptStored(false);
      setInfo((i) => (i ? { ...i, missing_fields: updated.design.missing_fields, design: updated.design } : i));
      toast.push("success", `Stored the registry copy as design v${updated.version}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "design_changed") setConflict(err.message);
    } finally {
      setImporting(null);
    }
  };

  const validation = touched ? nctError(nct) : null;
  const chips: DemoTrial[] = cached.length
    ? cached.map((c) => ({
        registryId: c.nct_id,
        label: [c.acronym ?? c.title.slice(0, 40), c.phase, c.sites ? `${c.sites} sites` : null].filter(Boolean).join(" · "),
        note: [c.title, c.sponsor && `Sponsor: ${c.sponsor}`].filter(Boolean).join(" — "),
      }))
    : DEMO_TRIALS;
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
          <h1 className="text-3xl font-bold tracking-tight text-ink-900">Plan a trial you can defend</h1>
          <p className="mt-2 max-w-xl text-base text-ink-600">
            Import a real trial, flip design levers and see cost, site staff time, patient travel, timeline and carbon move — each as a
            P10–P90 range with its formula and sources.
          </p>

          <form
            className="mt-6"
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              void runImport(nct);
            }}
          >
            <label htmlFor={inputId} className="label">
              ClinicalTrials.gov ID
            </label>
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
                {importing ? "Importing…" : "Import"}
              </button>
            </div>
            <p id={`${inputId}-help`} className={`mt-1.5 text-sm ${validation ? "font-medium text-worse-700" : "text-ink-500"}`} role={validation ? "alert" : undefined}>
              {validation ?? "NCT followed by 8 digits. Registry data is real; anything missing is flagged and filled with a labelled assumption."}
            </p>
            {importError && (
              <p role="alert" className="mt-2 rounded-lg border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900" data-testid="import-error">
                {importError}
              </p>
            )}
          </form>

          {(chips.length > 0 || recent.length > 0) && (
            <div className="mt-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">{chips.length ? "Demo trials (cached — work offline)" : "Recent trials"}</p>
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
          {importing && <Spinner className="mt-4" label={`Fetching ${importing} from ClinicalTrials.gov (or the cache)`} />}
        </div>

        <aside className="card self-start p-5" aria-labelledby="how-title">
          <h2 id="how-title" className="card-title">
            How it works
          </h2>
          <ol className="mt-3 space-y-3 text-sm text-ink-700">
            <li><strong className="text-ink-900">1. Import.</strong> Sites, enrollment, phase and dates come from the registry. The visit schedule comes from the protocol (AI-extracted, you confirm every row) or a labelled template.</li>
            <li><strong className="text-ink-900">2. Simulate.</strong> Remote monitoring, home or telehealth visits, local labs, on-demand drug supply, fewer procedures or sites.</li>
            <li><strong className="text-ink-900">3. Defend.</strong> Click any number for its formula, parameters and sources. Save, compare and send for e-signed approval.</li>
          </ol>
        </aside>
      </section>

      {design && (
        <>
          <TrialCard design={design} info={info} onEdit={() => setEditOpen(true)} />
          {designVersion != null && (
            <p className="text-sm text-ink-600" data-testid="import-design-version">
              Saved as <strong>design v{designVersion}</strong>. The simulator computes and saves against this version.
            </p>
          )}
          {keptStored && (
            <div className="rounded-xl border border-ink-200 bg-ink-50 px-5 py-3 text-sm text-ink-800" data-testid="stored-design-banner">
              <p>
                This trial was already saved{designVersion != null ? ` as design v${designVersion}` : ""}. That copy is shown, including a protocol schedule if one was confirmed.
                The registry response is not written over it.
              </p>
              {registryDiffers && designEtag && (
                <button type="button" className="btn-secondary mt-2" onClick={() => void reimportRegistry()} disabled={importing !== null} data-testid="reimport-registry">
                  Re-import from registry
                </button>
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
              <strong>{design.visits.length} visits</strong> and <strong>{design.sites.length} sites</strong> ready.
              {design.missing_fields.length > 0 && ` ${design.missing_fields.length} input(s) use labelled assumptions.`}
            </p>
            <button type="button" className="btn-primary px-5" onClick={() => navigate(`/scenario/${encodeURIComponent(design.id)}`)} data-testid="open-simulator">
              Open scenario simulator →
            </button>
          </div>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <section className="card p-5" id="missing" aria-labelledby="missing-title">
              <SectionTitle aside={<Badge tone="caution"><span data-testid="missing-count">{assumedTotal}</span></Badge>}>
                <span id="missing-title">Missing &amp; assumed</span>
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
                <span id="map-title">Sites</span>
              </SectionTitle>
              <SiteMap sites={design.sites} />
            </section>
          </div>
        </>
      )}

      <section ref={protocolRef} className="card p-5" aria-labelledby="protocol-title" id="protocol">
        <SectionTitle>
          <span id="protocol-title">Protocol PDF → schedule of activities</span>
        </SectionTitle>
        <p className="max-w-3xl text-sm text-ink-600">
          Upload the trial protocol to extract visits and procedures. Extraction is done by an AI model and returned as candidates with the page
          number and a short quote; nothing is applied until you accept rows and press “Apply to design”.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="btn-secondary cursor-pointer">
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              onChange={(e) => void onFile(e.target.files?.[0])}
              data-testid="protocol-file"
            />
            Choose protocol PDF…
          </label>
          {design?.registry_id && (registryProtocol || design.registry_id.startsWith("NCT")) && (
            <button type="button" className="btn-secondary" onClick={() => void extractFromRegistry()} disabled={extracting} data-testid="extract-registry">
              Use the registry protocol{registryProtocol?.extraction_cached ? " (cached extraction)" : ""}
            </button>
          )}
          <span className="text-xs text-ink-500">PDF up to 20 MB{design ? ` · will be applied to ${design.registry_id ?? "this design"}` : " · import the trial first to apply results"}</span>
          {extracting && <Spinner label="Extracting schedule (this can take ~30 s)" />}
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
                extraction.method && `Method: ${extraction.method}`,
                extraction.model && `model: ${extraction.model}`,
                extraction.soa_pages.length
                  ? `schedule on pages ${extraction.soa_pages[0]}–${extraction.soa_pages[extraction.soa_pages.length - 1]}${extraction.page_count ? ` of ${extraction.page_count}` : ""}`
                  : null,
                extraction.from_cache ? "served from cache" : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {extraction.notice && <p className="mb-2 text-xs text-caution-900">{extraction.notice}</p>}
            {extraction.excluded_columns.length > 0 && (
              <details className="mb-3 text-xs text-ink-600">
                <summary className="cursor-pointer font-semibold">Columns the extractor left out ({extraction.excluded_columns.length})</summary>
                <ul className="mt-1 list-disc space-y-0.5 pl-5">
                  {extraction.excluded_columns.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </details>
            )}
            {extraction.candidates.length === 0 ? (
              <p className="text-sm text-ink-600">No schedule of activities was found in this PDF.</p>
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
          onSaved={(rec) => {
            showRecord(rec);
            setKeptStored(false);
            setInfo((i) => (i ? { ...i, missing_fields: rec.design.missing_fields, design: rec.design } : i));
          }}
        />
      )}
      {!design && recent.length === 0 && DEMO_TRIALS.length === 0 && (
        <p className="text-center text-sm text-ink-500">
          New here? Read <Link className="link" to="/about">how TrialPilot calculates</Link>.
        </p>
      )}
    </div>
  );
}
