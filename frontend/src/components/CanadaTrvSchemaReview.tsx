"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, type CanadaTrvReviewApplication, type CanadaTrvReviewDetail, type CanadaTrvReviewField } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

type Filter = "open" | "problems" | "confirmed";

function textValue(field: CanadaTrvReviewField): string {
  const value = field.edited_value_json ?? field.normalized_value_json;
  if (typeof value === "boolean") return value ? "Sim" : "Não";
  if (value && typeof value === "object" && "raw_text" in value) return String((value as { raw_text: unknown }).raw_text ?? "");
  return value === null || value === undefined ? field.raw_value : String(value);
}

function sectionTitle(id: string, fallback: string) {
  const activity = id.match(/^activity_0(\d)$/);
  if (activity) return `Atividades — Atividade ${activity[1]}`;
  const child = id.match(/^child_0(\d)$/);
  if (child) return `Filhos — Filho ${child[1]}`;
  return fallback;
}

function isProblem(field: CanadaTrvReviewField) {
  return ["missing", "needs_review"].includes(field.review_status);
}

export function CanadaTrvSchemaReview({ caseId, onChanged }: { caseId: string; onChanged: () => Promise<void> }) {
  const [applications, setApplications] = useState<CanadaTrvReviewApplication[]>([]);
  const [detail, setDetail] = useState<CanadaTrvReviewDetail | null>(null);
  const [activeSection, setActiveSection] = useState("");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState<Filter>("open");
  const [showInapplicable, setShowInapplicable] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load(preferredId?: string) {
    const nextApplications = await api.listCanadaTrvReviews(caseId);
    setApplications(nextApplications);
    const selected = preferredId ?? detail?.application.id ?? nextApplications[0]?.id;
    if (!selected) { setDetail(null); return; }
    const next = await api.getCanadaTrvReview(selected);
    setDetail(next);
    setDrafts(Object.fromEntries(next.fields.map(field => [field.id, textValue(field)])));
    const first = next.sections.find(section => section.reviewable && next.fields.some(field => field.section_id === section.id && field.ui.show_in_review));
    if (!activeSection || !next.sections.some(section => section.id === activeSection)) setActiveSection(first?.id ?? next.sections[0]?.id ?? "");
  }

  useEffect(() => { void load().catch(reason => setError(reason instanceof Error ? reason.message : "Review data could not be loaded.")); }, [caseId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function action(key: string, callback: () => Promise<unknown>, preferredId?: string) {
    setBusy(key); setError("");
    try { await callback(); await load(preferredId); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Review action failed."); }
    finally { setBusy(""); }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const file = new FormData(event.currentTarget).get("file");
    if (!(file instanceof File) || !file.size) { setError("Choose a CSV file."); return; }
    let created: CanadaTrvReviewApplication[] = [];
    await action("upload", async () => { created = await api.importCanadaTrvReview(file, caseId); }, undefined);
    if (created[0]) await load(created[0].id);
  }

  const reviewableSections = detail?.sections.filter(section => section.reviewable) ?? [];
  const fields = detail?.fields ?? [];
  const required = fields.filter(field => field.requirement_mode === "review_when_applicable" && field.applicability !== "not_applicable");
  const confirmed = required.filter(field => ["confirmed", "confirmed_after_correction"].includes(field.review_status)).length;
  const activeFields = fields.filter(field => field.section_id === activeSection && field.ui.show_in_review && (showInapplicable || field.applicability !== "not_applicable"));
  const visibleFields = activeFields.filter(field => filter === "confirmed"
    ? ["confirmed", "confirmed_after_correction"].includes(field.review_status)
    : filter === "problems" ? isProblem(field) : !["confirmed", "confirmed_after_correction", "not_applicable"].includes(field.review_status));
  const sectionIssues = detail?.validation_issues.filter(issue => issue.section_id === activeSection) ?? [];
  const sectionCanConfirm = activeFields.every(field => field.requirement_mode !== "review_when_applicable" || field.applicability === "not_applicable" || ["confirmed", "confirmed_after_correction"].includes(field.review_status))
    && !sectionIssues.some(issue => ["blocking", "error"].includes(issue.severity));
  const canConfirmAll = detail?.application.status === "ready_to_confirm";

  const progressBySection = useMemo(() => Object.fromEntries(reviewableSections.map(section => {
    const items = fields.filter(field => field.section_id === section.id && field.ui.show_in_review && field.applicability !== "not_applicable");
    return [section.id, { done: items.filter(field => ["confirmed", "confirmed_after_correction"].includes(field.review_status)).length, total: items.length }];
  })), [fields, reviewableSections]);

  return <div className="trv-review-workspace">
    <div className="section-heading"><div><h2>Canada TRV schema review</h2><span className="muted">Strict schema v3 import, correction, and explicit confirmation</span></div>{detail && <StatusBadge value={detail.application.status} />}</div>
    {error && <div className="form-error" role="alert">{error}</div>}
    <form className="trv-review-upload" onSubmit={upload}>
      <div className="field"><label htmlFor="trv-review-file">Google Forms CSV</label><input id="trv-review-file" name="file" type="file" accept=".csv,text/csv" required /></div>
      <button className="button" disabled={Boolean(busy)}>{busy === "upload" ? "Importing…" : "Import CSV"}</button>
    </form>
    {applications.length > 0 && <div className="field"><label htmlFor="trv-review-application">Import / response row</label><select id="trv-review-application" value={detail?.application.id ?? ""} onChange={event => void load(event.target.value)}>{applications.map(item => <option key={item.id} value={item.id}>Row {item.import_row_number} · {item.status} · {new Date(item.created_at).toLocaleString()}</option>)}</select></div>}
    {detail && <>
      <div className="trv-review-progress" role="status"><strong>{confirmed} / {required.length}</strong><span>applicable required review fields confirmed</span><progress value={confirmed} max={Math.max(required.length, 1)} /></div>
      <details className="trv-metadata"><summary>Source metadata and provenance</summary><dl><div><dt>Schema</dt><dd>{detail.schema_id} v{detail.schema_version}</dd></div><div><dt>Variant</dt><dd>{detail.variant_id}</dd></div><div><dt>Source</dt><dd>{detail.source_filename}, row {detail.application.import_row_number}</dd></div></dl></details>
      <nav className="trv-section-nav" aria-label="TRV review sections">{reviewableSections.map(section => { const progress = progressBySection[section.id] ?? { done: 0, total: 0 }; return <button type="button" key={section.id} className={activeSection === section.id ? "active" : ""} onClick={() => setActiveSection(section.id)}>{sectionTitle(section.id, section.ui_group_title_pt)} <span>{progress.done}/{progress.total}</span></button>; })}</nav>
      <div className="trv-review-toolbar"><div className="button-row" aria-label="Field filters">{(["open", "problems", "confirmed"] as Filter[]).map(value => <button type="button" key={value} className={filter === value ? "button button-small" : "button button-secondary button-small"} onClick={() => setFilter(value)}>{value}</button>)}</div><label><input type="checkbox" checked={showInapplicable} onChange={event => setShowInapplicable(event.target.checked)} /> Show not applicable</label></div>
      <section className="trv-schema-section" aria-labelledby={`trv-section-${activeSection}`}>
        <header><div><h3 id={`trv-section-${activeSection}`}>{sectionTitle(activeSection, reviewableSections.find(section => section.id === activeSection)?.ui_group_title_pt ?? activeSection)}</h3>{sectionIssues.map(issue => <p className={`trv-issue trv-issue-${issue.severity}`} key={`${issue.code}-${issue.field_id}`}>{issue.message}</p>)}</div><button type="button" className="button" disabled={Boolean(busy) || !sectionCanConfirm} onClick={() => action("section", () => api.confirmCanadaTrvReviewSection(detail.application.id, activeSection), detail.application.id)}>Confirm section</button></header>
        {!visibleFields.length ? <div className="empty-state">No fields match this filter.</div> : <div className="trv-field-grid">{visibleFields.map(field => <ReviewField key={field.id} field={field} value={drafts[field.id] ?? ""} disabled={Boolean(busy)} onValue={value => setDrafts(current => ({ ...current, [field.id]: value }))} onSave={() => action(field.id, () => api.updateCanadaTrvReviewField(field.id, drafts[field.id] ?? ""), detail.application.id)} onConfirm={() => action(field.id, () => api.confirmCanadaTrvReviewField(field.id), detail.application.id)} />)}</div>}
      </section>
      <div className="trv-review-complete"><div><strong>Complete application review</strong><p>Available only after every applicable required field is confirmed and blocking issues are resolved.</p></div><button type="button" className="button" disabled={Boolean(busy) || !canConfirmAll} onClick={() => action("all", () => api.confirmCanadaTrvReview(detail.application.id), detail.application.id)}>Confirm complete review</button></div>
    </>}
  </div>;
}

function ReviewField({ field, value, disabled, onValue, onSave, onConfirm }: { field: CanadaTrvReviewField; value: string; disabled: boolean; onValue: (value: string) => void; onSave: () => void; onConfirm: () => void }) {
  const changed = value !== textValue(field);
  const multiline = field.normalized_type === "multiline_text" || field.ui.span_columns === "full";
  const inputId = `trv-field-${field.id}`;
  return <article className={`trv-field-cell ${multiline ? "trv-field-full" : ""}`}>
    <div className="trv-field-header"><label htmlFor={inputId}>{field.label_pt}</label><StatusBadge value={field.review_status} /></div>
    {field.normalized_type === "yes_no_raw" ? <select id={inputId} value={value} onChange={event => onValue(event.target.value)}><option value="">Choose</option><option value="Sim">Sim</option><option value="Não">Não</option></select> : multiline ? <textarea id={inputId} value={value} onChange={event => onValue(event.target.value)} /> : <input id={inputId} type={field.normalized_type === "date_raw" ? "date" : field.normalized_type === "email" ? "email" : "text"} value={value} onChange={event => onValue(event.target.value)} />}
    <details><summary>Source and history</summary><p><strong>{field.field_id}</strong> · CSV column {field.source_csv_column_1based ?? "not present"}<br />Exact header: {field.source_header}<br />Evidence: {field.evidence ?? "unverified"}</p><p>Original: {field.raw_value || "—"}</p>{field.revisions.map(revision => <p key={revision.id}>{new Date(revision.created_at).toLocaleString()} · {revision.actor_id}</p>)}</details>
    <div className="button-row"><button type="button" className="button button-secondary button-small" disabled={disabled || !changed} onClick={onSave}>Save correction</button><button type="button" className="button button-small" disabled={disabled || changed || field.review_status === "needs_review" || field.review_status === "missing" || field.applicability !== "applicable" || ["confirmed", "confirmed_after_correction"].includes(field.review_status)} onClick={onConfirm}>Confirm</button></div>
  </article>;
}
