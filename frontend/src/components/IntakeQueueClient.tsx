"use client";

import Link from "next/link";
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";

import { api, type CaseSummary, type IntakeMetrics, type IntakeSubmission } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";


export function IntakeQueueClient() {
  const [items, setItems] = useState<IntakeSubmission[]>([]);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [metrics, setMetrics] = useState<IntakeMetrics | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [caseChoices, setCaseChoices] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    const [submissions, counters, bootstrap] = await Promise.all([
      api.listIntakeSubmissions(), api.intakeMetrics(), api.bootstrap(),
    ]);
    setItems(submissions); setMetrics(counters); setCases(bootstrap.case_summary);
  }

  useEffect(() => { load().catch(reason => setError(reason instanceof Error ? reason.message : "Intake queue could not be loaded.")); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) { setError("Choose a Google Forms CSV file."); return; }
    const values = new FormData(event.currentTarget);
    setBusy("upload"); setError(""); setMessage("");
    try {
      const result = await api.uploadGoogleFormsIntake(
        file,
        String(values.get("source_external_id") || "").trim() || undefined,
        String(values.get("case_id") || "") || undefined,
      );
      setMessage(result.processing_status === "PROCESSED"
        ? "Submission processed automatically."
        : result.processing_status === "NEEDS_REVIEW"
          ? "Submission processed and added to the review queue."
          : result.failure_message ?? "Submission received.");
      setFile(null); await load(); window.dispatchEvent(new Event("visa-bootstrap-refresh"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Submission could not be received."); }
    finally { setBusy(""); }
  }

  async function retry(item: IntakeSubmission) {
    setBusy(item.id); setError(""); setMessage("");
    try {
      const result = await api.retryIntakeSubmission(item.id, caseChoices[item.id] || undefined);
      setMessage(result.processing_status === "PROCESSED" ? "Retry completed." : result.failure_message ?? "Retry completed with review items.");
      await load(); window.dispatchEvent(new Event("visa-bootstrap-refresh"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Retry failed."); }
    finally { setBusy(""); }
  }

  function chooseFile(event: ChangeEvent<HTMLInputElement>) { setFile(event.target.files?.[0] ?? null); }

  return <div className="detail-stack">
    <section className="section-card"><div className="section-heading"><div><h2>Receive Google Forms CSV</h2><span className="muted">The source is preserved, deduplicated, mapped and safely applied automatically.</span></div></div>
      {message && <div className="success-message" role="status">{message}</div>}{error && <div className="form-error" role="alert">{error}</div>}
      <form className="form-grid" onSubmit={upload}>
        <div className="field"><label htmlFor="intake-file">CSV source</label><input id="intake-file" type="file" accept=".csv,text/csv" onChange={chooseFile} /></div>
        <div className="field"><label htmlFor="intake-external-id">Google submission ID (optional)</label><input id="intake-external-id" name="source_external_id" /></div>
        <div className="field field-full"><label htmlFor="intake-case">Existing application (optional)</label><select id="intake-case" name="case_id" defaultValue=""><option value="">Create or resolve automatically</option>{cases.map(item => <option key={item.id} value={item.id}>{item.display_name} · {item.case_number}</option>)}</select></div>
        <div className="button-row field-full"><button className="button" disabled={busy === "upload"}>{busy === "upload" ? "Processing…" : "Receive and process"}</button></div>
      </form>
    </section>
    {metrics && <section className="summary-grid" aria-label="Intake counters">{[
      ["Received", metrics.submissions_received], ["Processed", metrics.successfully_processed],
      ["Duplicates ignored", metrics.duplicates_ignored], ["New applications", metrics.new_cases_created],
      ["Matched applications", metrics.existing_cases_matched], ["Need review", metrics.review_required],
      ["Failed", metrics.failed],
    ].map(([label, value]) => <div className="summary-item" key={label}><strong>{value}</strong><span>{label}</span></div>)}</section>}
    <section className="section-card"><div className="section-heading"><div><h2>Intake queue</h2><span className="muted">Failed and review-required submissions appear first.</span></div><span className="badge">{items.length}</span></div>
      {!items.length ? <div className="empty-state">No intake submissions received.</div> : <div className="record-list">{items.map(item => <article className="record" key={item.id}>
        <div className="record-head"><div><h3>{item.applicant_display_name ?? "Applicant not identified yet"}</h3><div className="record-meta"><StatusBadge value={item.processing_status} /><span className="badge">{item.issue_count} issues</span></div></div><span className="muted">{new Date(item.received_at).toLocaleString()}</span></div>
        <p><strong>Source:</strong> Google Forms CSV{item.source_filename ? ` · ${item.source_filename}` : ""}<br /><strong>Application:</strong> {item.case_number ?? "Not linked"}</p>
        {item.failure_message && <p>{item.failure_message}</p>}
        <div className="button-row">{item.case_id && <Link className="button button-secondary button-small" href={`/cases/${item.case_id}`}>Open application</Link>}
          {["FAILED", "NEEDS_REVIEW"].includes(item.processing_status) && <><select aria-label={`Application for ${item.source_filename ?? item.id}`} value={caseChoices[item.id] ?? ""} onChange={event => setCaseChoices(current => ({ ...current, [item.id]: event.target.value }))}><option value="">Retry current resolution</option>{cases.map(candidate => <option key={candidate.id} value={candidate.id}>{candidate.display_name} · {candidate.case_number}</option>)}</select><button className="button button-small" disabled={busy === item.id} onClick={() => void retry(item)}>{busy === item.id ? "Retrying…" : "Retry"}</button></>}
        </div>
      </article>)}</div>}
    </section>
  </div>;
}
