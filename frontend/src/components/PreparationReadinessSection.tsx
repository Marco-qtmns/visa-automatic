"use client";

import { useState } from "react";
import { api, type PreparationIssue, type PreparationRun, type PreparationStatus } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

function issueTarget(issue: PreparationIssue): string {
  if (issue.section === "imports") return "#canada-import";
  if (issue.section === "facts") return "#needs-attention";
  if (issue.section === "documents") return "#documents";
  return "#canada-application";
}

const actor = process.env.NEXT_PUBLIC_WORKFLOW_ACTOR ?? "manual-ui";

function ArtifactList({ run }: { run: PreparationRun }) {
  return <ul>{run.artifacts.map(artifact => <li key={artifact.id}>
    <strong>{artifact.display_filename.replace("-DRAFT.pdf", "")}</strong>{" "}
    <a href={api.preparationArtifactContentUrl(artifact.id)} target="_blank" rel="noreferrer">Open</a>{" · "}
    <a href={api.preparationArtifactContentUrl(artifact.id, true)}>Download</a>
  </li>)}</ul>;
}

export function PreparationSection({ caseId, value, history, onChanged }: {
  caseId: string; value: PreparationStatus; history: PreparationRun[]; onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const readiness = value.readiness;
  async function generate() {
    setBusy(true); setError("");
    try { await api.prepare(caseId, actor); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Application package generation failed."); }
    finally { setBusy(false); }
  }
  return (
    <section className="section-card" id="preparation-readiness" aria-labelledby="preparation-readiness-title">
      <div className="section-heading">
        <div><p className="eyebrow">Canonical application</p><h2 id="preparation-readiness-title">Preparation</h2></div>
        <StatusBadge value={value.package_status} />
      </div>
      <p className="muted">{readiness.blocking_count} blockers · {readiness.warning_count} warnings</p>
      {!readiness.ready ? (
        <div className="detail-stack">{readiness.sections.map(section => (
          <div key={section.section} className="summary-item">
            <strong>{section.label}</strong><span>{section.blocking_count} blocking · {section.warning_count} warnings</span>
            {section.issues.map(issue => <div key={`${issue.code}-${issue.path}`}><p><strong>{issue.label}</strong> — {issue.message}</p><p className="muted">{issue.action}</p><a href={issueTarget(issue)}>Open relevant canonical section</a></div>)}
          </div>
        ))}</div>
      ) : <div className="detail-stack">
        {value.package_status === "not_generated" && <button className="button" disabled={busy} onClick={() => void generate()}>{busy ? "Generating…" : "Generate application package"}</button>}
        {value.package_status === "generating" && <div className="state-panel">Generating application package…</div>}
        {value.package_status === "current" && value.current_run && <><div className="empty-state">Application package is current.</div><ArtifactList run={value.current_run} /></>}
        {value.package_status === "stale" && <><div className="error-panel">Application data changed since this package was generated.</div><button className="button" disabled={busy} onClick={() => void generate()}>{busy ? "Generating…" : "Regenerate"}</button></>}
        {value.package_status === "integrity_error" && <><div className="error-panel">A generated artifact is missing or damaged.</div><button className="button" disabled={busy} onClick={() => void generate()}>Regenerate</button></>}
        {value.package_status === "failed" && <><div className="error-panel">{value.latest_run?.error_summary ?? "Application package generation failed."}</div><button className="button" disabled={busy} onClick={() => void generate()}>Generate application package</button></>}
        {value.package_status === "submitted_discrepancy" && <div className="error-panel">The submitted case differs from its generated application package. The submitted workflow remains closed.</div>}
        {error && <div className="form-error" role="alert">{error}</div>}
      </div>}
      <details><summary>Advanced: technical readiness and preparation history</summary><p className="muted">Policy {readiness.policy_version} · payload schema {readiness.schema_version}</p>
      <h3>Preparation history</h3>
      {!history.length ? <div className="empty-state">No preparation runs yet.</div> : <div className="detail-stack">{history.map((run, index) => <details key={run.id}>
        <summary>Run {history.length - index} · {run.status}{value.current_run?.id === run.id ? " · Current" : run.status === "succeeded" ? " · Outdated" : ""}</summary>
        <p className="muted">{new Date(run.started_at).toLocaleString()} · {run.initiated_by}</p>
        {run.error_summary && <p>{run.error_summary}</p>}
        {!!run.artifacts.length && <ArtifactList run={run} />}
      </details>)}</div>}</details>
    </section>
  );
}
