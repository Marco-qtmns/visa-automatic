"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, loadCaseDetail, type CaseDetailBundle, type WorkflowState } from "@/lib/api";
import { DocumentsSection, FactsSection, PeopleSection, RequirementsSection, TasksSection } from "./CaseSections";
import { NextActionCard } from "./NextActionCard";
import { StatusBadge } from "./StatusBadge";
import { WorkflowStepper } from "./WorkflowStepper";
import { CommunicationsSection } from "./CommunicationsSection";
import { CanadaApplicationSection } from "./CanadaApplicationSection";
import { PreparationSection } from "./PreparationReadinessSection";
import { useCurrentUser } from "./AuthShell";
import { CaseAuditSection } from "./CaseAuditSection";

const actor = process.env.NEXT_PUBLIC_WORKFLOW_ACTOR ?? "manual-ui";
export function workflowActionLabel(current: WorkflowState, target: WorkflowState): string {
  if (current === "PREPARE" && target === "REVIEW") return "Send for review";
  if (current === "REVIEW" && target === "PREPARE") return "Return to preparation";
  if (current === "REVIEW" && target === "READY") return "Approve application";
  if (current === "READY" && target === "SUBMITTED") return "Mark submitted";
  if (target === "DOCUMENTS") return "Continue application";
  return `Continue to ${target}`;
}

function businessLabel(value: string): string {
  const text = value.split(".").at(-1)?.replaceAll("_", " ") ?? value;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function visibleWorkflowTargets(
  currentState: WorkflowState,
  targets: WorkflowState[],
  role?: string,
): WorkflowState[] {
  if (role !== "CASE_WORKER") return targets;
  if (currentState === "READY") return [];
  if (currentState === "REVIEW") return targets.filter(target => target === "PREPARE");
  return targets.filter(target => !["READY", "SUBMITTED"].includes(target));
}

export function CaseDetailClient({ caseId }: { caseId: string }) {
  const currentUser = useCurrentUser();
  const [data, setData] = useState<CaseDetailBundle | null>(null);
  const [error, setError] = useState(""); const [editing, setEditing] = useState(false); const [workflowError, setWorkflowError] = useState(""); const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { setError(""); try { setData(await loadCaseDetail(caseId)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Case could not be loaded."); } }, [caseId]);
  useEffect(() => { void load(); }, [load]);
  if (error) return <div className="error-panel" role="alert">{error} <button className="button button-small" onClick={() => void load()}>Retry</button></div>;
  if (!data) return <div className="state-panel">Loading case…</div>;

  async function updateOverview(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const values = new FormData(event.currentTarget); try { await api.updateCase(caseId, { case_number: String(values.get("case_number")), visa_type: String(values.get("visa_type")), purpose: String(values.get("purpose")) }); setEditing(false); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Case could not be saved."); } }
  async function transition(target: WorkflowState, event: FormEvent<HTMLFormElement>) { event.preventDefault(); setBusy(true); setWorkflowError(""); const values = new FormData(event.currentTarget); try { await api.transition(caseId, target, actor, String(values.get("reason") || "") || undefined); await load(); } catch (reason) { setWorkflowError(reason instanceof Error ? reason.message : "Transition was rejected."); } finally { setBusy(false); } }
  const refresh = async () => {
    await load();
    window.dispatchEvent(new Event("visa-bootstrap-refresh"));
  };
  const applicant = data.people.find(person => person.roles.includes("applicant"));
  const allowedTargets = visibleWorkflowTargets(data.workflow.current_state, data.workflow.allowed_targets, currentUser?.role);
  const readiness = data.preparation.readiness;
  const issueCount = readiness.blocking_count + readiness.warning_count;
  const factConflicts = data.facts.filter(item => item.status === "conflict");
  const missingDocuments = data.requirements.filter(item => item.active && item.fulfillment_status === "pending");
  const documentReview = data.documents.filter(item => ["failed", "manual_review", "error"].includes(item.quality_status) || item.classification_status === "suggestion_available");
  const blockingTasks = data.tasks.filter(item => item.blocking && ["open", "in_progress"].includes(item.status));
  const attentionCount = factConflicts.length + missingDocuments.length + documentReview.length + blockingTasks.length;

  return <div className="detail-stack">
    <div className="page-heading"><div><p className="eyebrow">{data.case.case_number}</p><h1>{applicant ? `${applicant.first_name} ${applicant.last_name}` : "Applicant not identified yet"}</h1><p className="subtitle">Stage: {data.workflow.current_state} · Readiness: {readiness.ready ? "Ready" : "Blocked"} · {issueCount} items need attention</p></div><Link className="button button-secondary" href="/cases">Back to applications</Link></div>
    <nav className="anchor-nav" aria-label="Application workspace">{["needs-attention", "information-sources", "application-summary", "requirements", "documents", "primary-action", "advanced"].map(section => <a href={`#${section}`} key={section}>{section.replaceAll("-", " ")}</a>)}</nav>
    <NextActionCard action={data.nextAction} />
    <section className="section-card" id="needs-attention"><div className="section-heading"><div><h2>Needs attention</h2><span className="muted">Only unresolved employee, client, or reviewer actions</span></div><span className="badge">{attentionCount}</span></div>
      {!attentionCount ? <div className="empty-state">No operational exceptions require attention.</div> : <div className="record-list">
        {factConflicts.map(item => { const person = data.people.find(candidate => candidate.id === item.person_id); return <a className="record" href="#advanced" key={item.id}><strong>{person ? `${person.first_name} ${person.last_name}` : "Application"} — {businessLabel(item.key)} conflict</strong><span>Source: {item.source_type} ({item.source_reference}). Conflicting information must be resolved before preparation; review the source values and confirm one.</span></a>; })}
        {missingDocuments.map(item => <a className="record" href="#documents" key={item.id}><strong>{businessLabel(item.owner_role)} — {businessLabel(item.document_type)} missing</strong><span>Source: {item.rule_id ? `requirement rule ${item.rule_id}` : "case requirement"}. {item.reason} This blocks preparation; upload or match the required document.</span></a>)}
        {documentReview.map(item => { const person = data.people.find(candidate => candidate.id === item.person_id); return <a className="record" href="#documents" key={item.id}><strong>{person ? `${person.first_name} ${person.last_name}` : "Application"} — {item.original_filename} needs review</strong><span>Source: uploaded document. Classification or quality is uncertain; confirm the type or quality decision.</span></a>; })}
        {blockingTasks.map(item => <a className="record" href="#advanced" key={item.id}><strong>Application — {item.title}</strong><span>Source: case task. {item.description} This task blocks progress; complete or resolve it.</span></a>)}
      </div>}
    </section>
    <section className="section-card" id="information-sources"><div className="section-heading"><h2>Information sources</h2></div><div className="summary-grid">
      <a className="summary-item" href="#canada-import"><strong>Google Forms / CSV</strong><span>Import and review exceptions</span></a>
      <a className="summary-item" href="#communications"><strong>WhatsApp</strong><span>{data.conversations.length} conversations</span></a>
      <a className="summary-item" href="#documents"><strong>Documents</strong><span>{data.documents.length} received</span></a>
    </div></section>
    <section className="section-card" id="application-summary"><div className="section-heading"><h2>Application summary</h2></div><div className="summary-grid">{["Applicant", "Contact", "Travel", "Family", "Employment / Education", "Background", "Representative"].map(label => { const section = readiness.sections.find(item => item.label.toLowerCase().includes(label.split(" ")[0].toLowerCase())); const status = !section ? "MISSING" : section.blocking_count ? "NEEDS ATTENTION" : "COMPLETE"; return <div className="summary-item" key={label}><strong>{label}</strong><StatusBadge value={status} /></div>; })}</div></section>
    <section className="section-card" id="overview"><div className="section-heading"><h2>Overview</h2><button className="button button-secondary button-small" onClick={() => setEditing(!editing)}>{editing ? "Cancel" : "Edit"}</button></div>
      {!editing ? <div className="summary-grid"><div className="summary-item"><strong>{data.case.case_number}</strong><span>Case number</span></div><div className="summary-item"><strong>{data.people.length}</strong><span>People</span></div><div className="summary-item"><strong>{data.facts.length}</strong><span>Facts</span></div><div className="summary-item"><strong>{data.requirements.filter(item => item.active).length}</strong><span>Active requirements</span></div><div className="summary-item"><strong>{data.documents.length}</strong><span>Documents</span></div><div className="summary-item"><strong>{data.tasks.filter(task => task.status === "open" || task.status === "in_progress").length}</strong><span>Open tasks</span></div><div className="summary-item"><strong>{new Date(data.case.created_at).toLocaleDateString()}</strong><span>Created</span></div><div className="summary-item"><strong>{new Date(data.case.updated_at).toLocaleDateString()}</strong><span>Updated</span></div></div> : <form className="form-grid" onSubmit={updateOverview}><div className="field"><label>Case number</label><input name="case_number" required defaultValue={data.case.case_number} /></div><div className="field"><label>Visa type</label><input name="visa_type" required defaultValue={data.case.visa_type} /></div><div className="field field-full"><label>Purpose</label><input name="purpose" required defaultValue={data.case.purpose} /></div><div className="button-row field-full"><button className="button">Save case</button></div></form>}
    </section>
    <CanadaApplicationSection caseId={caseId} people={data.people} value={data.canadaApplication} onChanged={refresh} />
    <CommunicationsSection caseId={caseId} conversations={data.conversations} messages={data.conversationMessages} runs={data.factExtractionRuns} candidates={data.factCandidates} facts={data.facts} onChanged={refresh} />
    <section className="section-card" id="document-status"><div className="section-heading"><h2>Document status</h2><span className="muted">Received files, requirement match, and quality</span></div><div className="record-list">
      {data.requirements.filter(item => item.active).map(requirement => { const matches = data.documentMatches.filter(match => match.requirement_id === requirement.id); const documents = matches.map(match => data.documents.find(document => document.id === match.document_id)).filter(item => item !== undefined); return <div className="record" key={requirement.id}><strong>{requirement.owner_role} — {requirement.document_type}</strong><span>{requirement.fulfillment_status === "fulfilled" ? "Received" : "Missing"} · {documents.length ? documents.map(document => `${document.original_filename} (${document.quality_status})`).join(", ") : "No matching document"}{requirement.is_blocking && requirement.fulfillment_status === "pending" ? " · Action required" : ""}</span></div>; })}
      {!data.requirements.some(item => item.active) ? <div className="empty-state">No active document requirements.</div> : null}
    </div></section>
    <DocumentsSection caseId={caseId} items={data.documents} people={data.people} requirements={data.requirements} documentTypes={data.documentTypes} matches={data.documentMatches} classifications={data.documentClassifications} qualityChecks={data.documentQualityChecks} onChanged={refresh} />
    <PreparationSection caseId={caseId} value={data.preparation} history={data.preparationRuns} onChanged={refresh} />
    <section className="section-card" id="primary-action"><div className="section-heading"><h2>Primary action</h2><StatusBadge value={data.workflow.current_state} /></div>{!allowedTargets.length ? <EmptyWorkflow /> : <div className="transition-forms">{allowedTargets.map(target => <form className="transition-form" key={target} onSubmit={event => void transition(target, event)}><strong>{workflowActionLabel(data.workflow.current_state, target)}</strong><input name="reason" aria-label={`Reason for ${target}`} placeholder="Reason (optional)" /><button className="button" disabled={busy}>{workflowActionLabel(data.workflow.current_state, target)}</button></form>)}</div>}{workflowError && <div className="form-error" role="alert">{workflowError}</div>}</section>
    <details className="section-card" id="advanced"><summary><strong>Advanced / Diagnostics</strong></summary><p className="muted">Raw facts, canonical data, tasks, workflow history, provenance, and audit tools.</p>
    <div className="detail-grid"><PeopleSection caseId={caseId} items={data.people} onChanged={refresh} /><FactsSection caseId={caseId} items={data.facts} people={data.people} onChanged={refresh} /></div>
    <TasksSection caseId={caseId} items={data.tasks} requirements={data.requirements} documents={data.documents} onChanged={refresh} />
    <RequirementsSection caseId={caseId} items={data.requirements} people={data.people} documents={data.documents} matches={data.documentMatches} completenessEvaluations={data.requirementCompletenessEvaluations} onChanged={refresh} />
    <section className="section-card" id="workflow"><div className="section-heading"><div><h2>Workflow</h2><span className="muted">Transitions are validated and recorded by the backend. Actor: {actor}</span></div><StatusBadge value={data.workflow.current_state} /></div><WorkflowStepper current={data.workflow.current_state} />
      <h3 className="history-title">Transition history</h3>{!data.workflow.history.length ? <div className="empty-state">No transitions recorded.</div> : <div>{data.workflow.history.map(entry => <div className="transition-entry" key={entry.id}><div><strong>{new Date(entry.created_at).toLocaleString()}</strong><div className="muted">{entry.actor || "Unknown actor"}</div></div><div><div className="transition-arrow">{entry.from_state} → {entry.to_state}</div>{entry.reason && <p>{entry.reason}</p>}</div></div>)}</div>}
    </section>
    {currentUser && currentUser.role !== "CASE_WORKER" ? <CaseAuditSection caseId={caseId} /> : null}
    </details>
  </div>;
}

function EmptyWorkflow() { return <div className="empty-state">No transition is currently available.</div>; }
