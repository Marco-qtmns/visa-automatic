"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, type CanadaImportChange, type CanadaImportRun } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

const actor = process.env.NEXT_PUBLIC_WORKFLOW_ACTOR ?? "manual-ui";
const OFFICIAL_SECTIONS = [
  "Personal Details", "Languages", "Passport", "National Identity Document",
  "US Permanent Residence", "Contact Information", "Details of Visit to Canada",
  "Education", "Employment and Activity History", "Family Information",
  "Travel and Residence History", "Background Information", "Representative Information",
] as const;
type OfficialSection = typeof OFFICIAL_SECTIONS[number];
type DisplayStatus = "Confirmed" | "Needs confirmation" | "Conflict / Invalid" | "Missing";

function officialSection(change: CanadaImportChange): OfficialSection {
  const path = change.source_path;
  if (path.startsWith("passport.identity_")) return "National Identity Document";
  if (path.includes("green_card")) return "US Permanent Residence";
  if (path.startsWith("passport.")) return "Passport";
  if (path.startsWith("contact.")) return "Contact Information";
  if (path.startsWith("trip.")) return "Details of Visit to Canada";
  if (path.startsWith("education.")) return "Education";
  if (path.startsWith("activities")) return "Employment and Activity History";
  if (path.startsWith("relationships.") || path.startsWith("family.")) return "Family Information";
  if (path.startsWith("residence_records") || path.startsWith("travel_records")) return "Travel and Residence History";
  if (path.startsWith("official_review.")) return "Background Information";
  if (path.startsWith("representative.")) return "Representative Information";
  if (path.includes("language")) return "Languages";
  return "Personal Details";
}

function displayStatus(change: CanadaImportChange): DisplayStatus {
  if (["confirmed", "corrected"].includes(change.canonical_review_state ?? "")) return "Confirmed";
  if (change.status === "rejected") return "Confirmed";
  if (["conflict", "ambiguous"].includes(change.status)) return "Conflict / Invalid";
  if (change.proposed_value_json === null || change.proposed_value_json === "") return "Missing";
  return "Needs confirmation";
}

function display(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function editableValue(value: unknown) {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function CanadaImportSection({ caseId, onChanged }: { caseId: string; onChanged: () => Promise<void> }) {
  const [runs, setRuns] = useState<CanadaImportRun[]>([]);
  const [selected, setSelected] = useState<CanadaImportRun | null>(null);
  const [changes, setChanges] = useState<CanadaImportChange[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [hostTypes, setHostTypes] = useState<Record<string, "person" | "organization" | "">>({});
  const [activeSection, setActiveSection] = useState<OfficialSection>("Personal Details");
  const [filter, setFilter] = useState<"all" | "attention">("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(preferred?: CanadaImportRun) {
    const nextRuns = await api.listCanadaImports(caseId);
    const run = preferred ?? nextRuns[0] ?? null;
    const nextChanges = run ? await api.listCanadaImportChanges(run.id) : [];
    setRuns(nextRuns); setSelected(run); setChanges(nextChanges);
    setDrafts(current => Object.fromEntries(nextChanges.map(change => [change.id, current[change.id] ?? editableValue(change.proposed_value_json)])));
    const firstAttention = nextChanges.find(change => displayStatus(change) !== "Confirmed");
    if (firstAttention) setActiveSection(officialSection(firstAttention));
  }

  useEffect(() => { load().catch(reason => setError(reason instanceof Error ? reason.message : "Imports could not be loaded.")); }, [caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); await load(); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Import action failed."); }
    finally { setBusy(false); }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); const file = data.get("file");
    if (!(file instanceof File) || !file.size) { setError("Choose an import file."); return; }
    await act(async () => {
      const preview = await api.previewCanadaImport(caseId, String(data.get("source_type")), file, actor);
      await api.applyCanadaImport(preview.id, "safe", actor);
    });
  }

  async function confirm(change: CanadaImportChange) {
    await act(() => api.confirmCanadaImportChange(change.id, drafts[change.id] ?? "", actor, hostTypes[change.id] || undefined));
  }

  const grouped = useMemo(() => Object.fromEntries(OFFICIAL_SECTIONS.map(section => [section, changes.filter(change => officialSection(change) === section)])) as Record<OfficialSection, CanadaImportChange[]>, [changes]);
  const unresolved = changes.filter(change => displayStatus(change) !== "Confirmed");
  const sectionItems = grouped[activeSection] ?? [];
  const visibleItems = filter === "attention" ? sectionItems.filter(change => displayStatus(change) !== "Confirmed") : sectionItems;
  const invalidInSection = sectionItems.some(change => ["conflict", "ambiguous"].includes(change.status));
  const confirmableInSection = sectionItems.filter(change => ["new", "accepted"].includes(change.status));
  const counts = selected?.counts_json ?? {};
  const detected = Object.values(counts).reduce((sum, value) => sum + value, 0);

  function nextUnresolved() {
    if (!unresolved.length) return;
    const current = unresolved.findIndex(change => officialSection(change) === activeSection);
    const next = unresolved[(current + 1) % unresolved.length];
    setActiveSection(officialSection(next));
    setTimeout(() => document.getElementById(`import-field-${next.id}`)?.focus(), 0);
  }

  return <details id="canada-import" open>
    <summary>Canada application review</summary>
    <p className="muted">Review imported data in official application order. Original values and canonical proposals remain linked to the audit history.</p>
    {error && <div className="form-error" role="alert">{error}</div>}
    <form className="form-grid" onSubmit={upload}>
      <div className="field"><label htmlFor="canada-import-source">Source</label><select id="canada-import-source" name="source_type"><option value="google_verified_csv">Verified Google intake CSV</option><option value="canada_case_json">Canada case JSON</option><option value="representative_profile_json">Representative profile JSON</option></select></div>
      <div className="field"><label htmlFor="canada-import-file">Source file</label><input id="canada-import-file" name="file" type="file" required /></div>
      <div className="button-row field-full"><button className="button" disabled={busy}>Preview import</button></div>
    </form>
    {runs.length > 0 && <div className="field"><label htmlFor="canada-import-run">Import run</label><select id="canada-import-run" value={selected?.id ?? ""} onChange={event => { const run = runs.find(item => item.id === event.target.value); if (run) load(run).catch(() => setError("Import changes could not be loaded.")); }}>{runs.map(run => <option key={run.id} value={run.id}>{run.source_identifier} · {run.status}</option>)}</select></div>}
    {selected && <>
      <div className="success-message" role="status"><strong>Application intake processed</strong><br />{detected} values detected · {changes.length - unresolved.length} confirmed · {unresolved.length} need attention</div>
      {selected.warnings_json.length > 0 && <details><summary>{selected.warnings_json.length} parsing notes</summary><ul>{selected.warnings_json.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul></details>}
      <div className="button-row" aria-label="Review filters"><button type="button" className={filter === "all" ? "button" : "button button-secondary"} onClick={() => setFilter("all")}>All fields</button><button type="button" className={filter === "attention" ? "button" : "button button-secondary"} onClick={() => setFilter("attention")}>Needs attention</button><button type="button" className="button button-secondary" disabled={!unresolved.length} onClick={nextUnresolved}>Next unresolved field</button></div>
      <nav className="button-row" aria-label="Canada application sections">{OFFICIAL_SECTIONS.map(section => { const items = grouped[section]; const remaining = items.filter(item => displayStatus(item) !== "Confirmed").length; return <button type="button" key={section} className={section === activeSection ? "button" : "button button-secondary"} onClick={() => setActiveSection(section)}>{section} ({items.length - remaining}/{items.length})</button>; })}</nav>
      <div className="section-heading"><div><h3>{activeSection}</h3><span className="muted">{sectionItems.length - sectionItems.filter(item => displayStatus(item) !== "Confirmed").length} of {sectionItems.length} confirmed</span></div>{confirmableInSection.length > 0 && <button type="button" className="button" disabled={busy || invalidInSection} title={invalidInSection ? "Resolve invalid or conflicting fields first" : undefined} onClick={() => act(async () => { for (const change of confirmableInSection) await api.confirmCanadaImportChange(change.id, drafts[change.id] ?? "", actor, hostTypes[change.id] || undefined); })}>Confirm section</button>}</div>
      {!visibleItems.length && <div className="empty-state">No fields in this section match the current filter.</div>}
      {visibleItems.map(change => {
        const status = displayStatus(change); const changed = (drafts[change.id] ?? "") !== editableValue(change.proposed_value_json); const invalid = status === "Conflict / Invalid"; const needsHostType = change.conflict_type === "host_type_ambiguous"; const canConfirm = !invalid || changed || (needsHostType && Boolean(hostTypes[change.id])); const confirmDisabled = busy || (status === "Confirmed" ? !changed : !canConfirm);
        const card = <article className="summary-item"><div className="section-heading"><strong>{change.target_label}</strong><StatusBadge value={status} /></div><div className="form-grid"><div className="field field-full"><label htmlFor={`import-field-${change.id}`}>Application value</label><input id={`import-field-${change.id}`} value={drafts[change.id] ?? ""} aria-invalid={invalid} onChange={event => setDrafts(current => ({ ...current, [change.id]: event.target.value }))} /></div>{needsHostType && <div className="field"><label>Host type</label><select value={hostTypes[change.id] ?? ""} onChange={event => setHostTypes(current => ({ ...current, [change.id]: event.target.value as "person" | "organization" }))}><option value="">Choose person or institution</option><option value="person">Person</option><option value="organization">Institution</option></select></div>}</div>{status !== "Confirmed" && <p>{invalid ? "This proposal conflicts with canonical data or is invalid. Correct it before confirmation." : "This source value requires employee confirmation."}</p>}{(invalid || changed) && <p className="muted">Original: {display(change.raw_value_json)}<br />Current canonical value: {display(change.current_value_json)}</p>}<div className="button-row">{status !== "Confirmed" && <button type="button" className="button button-secondary" disabled={busy} onClick={() => act(() => api.reviewCanadaImportChange(change.id, "reject", actor))}>Reject</button>}<button type="button" className="button" disabled={confirmDisabled} onClick={() => confirm(change)}>{changed ? "Save correction and confirm" : "Confirm"}</button></div></article>;
        return change.source_record_key !== "scalar" ? <details open key={change.id}><summary>{change.source_record_key}</summary>{card}</details> : <div key={change.id}>{card}</div>;
      })}
      {changes.some(item => item.status === "accepted") && <div className="button-row"><button className="button" disabled={busy} onClick={() => act(() => api.applyCanadaImport(selected.id, "accepted", actor))}>Save confirmed data</button></div>}
    </>}
  </details>;
}
