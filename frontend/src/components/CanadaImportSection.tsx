"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, type CanadaImportChange, type CanadaImportRun } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

const actor = process.env.NEXT_PUBLIC_WORKFLOW_ACTOR ?? "manual-ui";

function display(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function CanadaImportSection({ caseId, onChanged }: { caseId: string; onChanged: () => Promise<void> }) {
  const [runs, setRuns] = useState<CanadaImportRun[]>([]);
  const [selected, setSelected] = useState<CanadaImportRun | null>(null);
  const [changes, setChanges] = useState<CanadaImportChange[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(preferred?: CanadaImportRun) {
    const nextRuns = await api.listCanadaImports(caseId);
    const run = preferred ?? nextRuns[0] ?? null;
    setRuns(nextRuns); setSelected(run);
    setChanges(run ? await api.listCanadaImportChanges(run.id) : []);
  }
  useEffect(() => { load().catch(reason => setError(reason instanceof Error ? reason.message : "Imports could not be loaded.")); }, [caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); await load(); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Import action failed."); }
    finally { setBusy(false); }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const file = data.get("file");
    if (!(file instanceof File) || !file.size) { setError("Choose an import file."); return; }
    await act(async () => {
      const run = await api.previewCanadaImport(caseId, String(data.get("source_type")), file, actor);
      await load(run);
    });
  }

  async function review(change: CanadaImportChange, action: "accept" | "reject" | "keep_current" | "use_imported", hostType?: "person" | "organization") {
    await act(() => action === "accept" || action === "reject"
      ? api.reviewCanadaImportChange(change.id, action, actor)
      : api.resolveCanadaImportChange(change.id, action, actor, hostType));
  }

  const sections = [...new Set(changes.map(item => item.domain_section))];
  const counts = selected?.counts_json ?? {};
  return <details id="canada-import" open>
    <summary>Canada intake import</summary>
    <p className="muted">Preview legacy data first. Confirmed canonical values are never overwritten without an individual decision.</p>
    {error && <div className="form-error" role="alert">{error}</div>}
    <form className="form-grid" onSubmit={upload}>
      <div className="field"><label htmlFor="canada-import-source">Source</label><select id="canada-import-source" name="source_type"><option value="google_verified_csv">Verified Google intake CSV</option><option value="canada_case_json">Canada case JSON</option><option value="representative_profile_json">Representative profile JSON</option></select></div>
      <div className="field"><label htmlFor="canada-import-file">Source file</label><input id="canada-import-file" name="file" type="file" required /></div>
      <div className="button-row field-full"><button className="button" disabled={busy}>Preview import</button></div>
    </form>
    {runs.length > 0 && <div className="field"><label htmlFor="canada-import-run">Import run</label><select id="canada-import-run" value={selected?.id ?? ""} onChange={event => { const run = runs.find(item => item.id === event.target.value); if (run) load(run).catch(() => setError("Import changes could not be loaded.")); }}>{runs.map(run => <option key={run.id} value={run.id}>{run.source_identifier} · {run.status}</option>)}</select></div>}
    {selected && <>
      <div className="summary-grid" aria-label="Import counts">{[["New", counts.new], ["Same", counts.same], ["Conflicts", counts.conflict], ["Ambiguous", counts.ambiguous], ["Applied", counts.applied]].map(([label, count]) => <div className="summary-item" key={label}><strong>{count ?? 0}</strong><span>{label}</span></div>)}</div>
      {selected.warnings_json.length > 0 && <div><strong>Warnings</strong><ul>{selected.warnings_json.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul></div>}
      <div className="button-row"><button className="button" disabled={busy} onClick={() => act(() => api.applyCanadaImport(selected.id, "safe", actor))}>Accept all safe new values</button><button className="button button-secondary" disabled={busy} onClick={() => act(() => api.applyCanadaImport(selected.id, "accepted", actor))}>Apply selected</button></div>
      {sections.map(section => <div key={section}><h3>{section}</h3>{changes.filter(item => item.domain_section === section).map(change => <article className="summary-item" key={change.id}>
        <div className="section-heading"><strong>{change.employee_label}</strong><StatusBadge value={change.status} /></div>
        <p>Current: {display(change.current_value_json)}<br />Imported: {display(change.proposed_value_json)}</p>
        <span className="muted">Source: {change.source_classification}</span>
        {change.status === "conflict" || change.status === "ambiguous" ? <div className="button-row"><button className="button button-secondary" disabled={busy} onClick={() => review(change, "keep_current")}>Keep current</button>{change.conflict_type === "host_type_ambiguous" ? <><button className="button" disabled={busy} onClick={() => review(change, "use_imported", "person")}>Use as person</button><button className="button" disabled={busy} onClick={() => review(change, "use_imported", "organization")}>Use as institution</button></> : <button className="button" disabled={busy} onClick={() => review(change, "use_imported")}>Use imported</button>}</div> : change.status !== "applied" && change.status !== "rejected" ? <div className="button-row"><button className="button button-secondary" disabled={busy} onClick={() => review(change, "reject")}>Reject</button><button className="button" disabled={busy} onClick={() => review(change, "accept")}>Accept</button></div> : null}
      </article>)}</div>)}
    </>}
  </details>;
}
