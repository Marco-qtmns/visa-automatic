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
  const refresh = async () => { await load(); };
  const applicant = data.people.find(person => person.roles.includes("applicant"));
  const allowedTargets = visibleWorkflowTargets(data.workflow.current_state, data.workflow.allowed_targets, currentUser?.role);

  return <div className="detail-stack">
    <div className="page-heading"><div><p className="eyebrow">Case {data.case.case_number}</p><h1>{applicant ? `${applicant.first_name} ${applicant.last_name}` : "Applicant not assigned"}</h1><p className="subtitle">{data.case.visa_type} — {data.case.purpose}</p></div><Link className="button button-secondary" href="/cases">Back to cases</Link></div>
    <nav className="anchor-nav" aria-label="Case sections">{["overview", "people", "canada-application", "preparation-readiness", "facts", "communications", "requirements", "documents", "tasks", "workflow"].map(section => <a href={`#${section}`} key={section}>{section}</a>)}</nav>
    <section className="section-card" aria-label="Current workflow"><div className="section-heading"><h2>Current workflow</h2><StatusBadge value={data.workflow.current_state} /></div><WorkflowStepper current={data.workflow.current_state} /></section>
    <NextActionCard action={data.nextAction} />
    <section className="section-card" id="overview"><div className="section-heading"><h2>Overview</h2><button className="button button-secondary button-small" onClick={() => setEditing(!editing)}>{editing ? "Cancel" : "Edit"}</button></div>
      {!editing ? <div className="summary-grid"><div className="summary-item"><strong>{data.case.case_number}</strong><span>Case number</span></div><div className="summary-item"><strong>{data.people.length}</strong><span>People</span></div><div className="summary-item"><strong>{data.facts.length}</strong><span>Facts</span></div><div className="summary-item"><strong>{data.requirements.filter(item => item.active).length}</strong><span>Active requirements</span></div><div className="summary-item"><strong>{data.documents.length}</strong><span>Documents</span></div><div className="summary-item"><strong>{data.tasks.filter(task => task.status === "open" || task.status === "in_progress").length}</strong><span>Open tasks</span></div><div className="summary-item"><strong>{new Date(data.case.created_at).toLocaleDateString()}</strong><span>Created</span></div><div className="summary-item"><strong>{new Date(data.case.updated_at).toLocaleDateString()}</strong><span>Updated</span></div></div> : <form className="form-grid" onSubmit={updateOverview}><div className="field"><label>Case number</label><input name="case_number" required defaultValue={data.case.case_number} /></div><div className="field"><label>Visa type</label><input name="visa_type" required defaultValue={data.case.visa_type} /></div><div className="field field-full"><label>Purpose</label><input name="purpose" required defaultValue={data.case.purpose} /></div><div className="button-row field-full"><button className="button">Save case</button></div></form>}
    </section>
    <div className="detail-grid"><PeopleSection caseId={caseId} items={data.people} onChanged={refresh} /><FactsSection caseId={caseId} items={data.facts} people={data.people} onChanged={refresh} /></div>
    <CanadaApplicationSection caseId={caseId} people={data.people} value={data.canadaApplication} onChanged={refresh} />
    <PreparationSection caseId={caseId} value={data.preparation} history={data.preparationRuns} onChanged={refresh} />
    <CommunicationsSection caseId={caseId} conversations={data.conversations} messages={data.conversationMessages} runs={data.factExtractionRuns} candidates={data.factCandidates} facts={data.facts} onChanged={refresh} />
    <RequirementsSection caseId={caseId} items={data.requirements} people={data.people} documents={data.documents} matches={data.documentMatches} completenessEvaluations={data.requirementCompletenessEvaluations} onChanged={refresh} />
    <DocumentsSection caseId={caseId} items={data.documents} people={data.people} requirements={data.requirements} documentTypes={data.documentTypes} matches={data.documentMatches} classifications={data.documentClassifications} qualityChecks={data.documentQualityChecks} onChanged={refresh} />
    <TasksSection caseId={caseId} items={data.tasks} requirements={data.requirements} documents={data.documents} onChanged={refresh} />
    <section className="section-card" id="workflow"><div className="section-heading"><div><h2>Workflow</h2><span className="muted">Transitions are validated and recorded by the backend. Actor: {actor}</span></div><StatusBadge value={data.workflow.current_state} /></div><WorkflowStepper current={data.workflow.current_state} />
      <h3>Allowed transitions</h3>{!allowedTargets.length ? <EmptyWorkflow /> : <div className="transition-forms">{allowedTargets.map(target => <form className="transition-form" key={target} onSubmit={event => void transition(target, event)}><strong>{data.workflow.current_state} → {target}</strong><input name="reason" aria-label={`Reason for ${target}`} placeholder="Reason (optional)" /><button className="button button-small" disabled={busy}>Move to {target}</button></form>)}</div>}{workflowError && <div className="form-error" role="alert">{workflowError}</div>}
      <h3 className="history-title">Transition history</h3>{!data.workflow.history.length ? <div className="empty-state">No transitions recorded.</div> : <div>{data.workflow.history.map(entry => <div className="transition-entry" key={entry.id}><div><strong>{new Date(entry.created_at).toLocaleString()}</strong><div className="muted">{entry.actor || "Unknown actor"}</div></div><div><div className="transition-arrow">{entry.from_state} → {entry.to_state}</div>{entry.reason && <p>{entry.reason}</p>}</div></div>)}</div>}
    </section>
    {currentUser && currentUser.role !== "CASE_WORKER" ? <CaseAuditSection caseId={caseId} /> : null}
  </div>;
}

function EmptyWorkflow() { return <div className="empty-state">No transition is currently available.</div>; }
