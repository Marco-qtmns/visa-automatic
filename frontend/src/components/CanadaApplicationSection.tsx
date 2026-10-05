"use client";

import { useState, type FormEvent } from "react";
import { api, type CanadaApplicationBundle, type Person } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";
import { CanadaImportSection } from "./CanadaImportSection";

const REVIEW_STATES = ["unreviewed", "confirmed", "corrected", "needs_review", "rejected"];
const actor = process.env.NEXT_PUBLIC_WORKFLOW_ACTOR ?? "manual-ui";

function optional(value: FormDataEntryValue | null) {
  const text = String(value ?? "").trim();
  return text || null;
}

export function CanadaApplicationSection({
  caseId,
  people,
  value,
  onChanged,
}: {
  caseId: string;
  people: Person[];
  value: CanadaApplicationBundle | null;
  onChanged: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function run(action: () => Promise<unknown>, success: string) {
    setError(""); setMessage("");
    try { await action(); setMessage(success); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Canada application data could not be saved."); }
  }

  async function initialize(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await run(() => api.createCanadaApplication(caseId, String(data.get("applicant_person_id"))), "Canada application initialized.");
  }

  if (!value) return <section className="section-card" id="canada-application">
    <div className="section-heading"><div><h2>Canada application</h2><span className="muted">Canonical structured application data</span></div></div>
    <p>Select the applicant explicitly. The system never chooses the first person or legacy role automatically.</p>
    {error && <div className="form-error" role="alert">{error}</div>}
    <form className="form-grid" onSubmit={initialize}><div className="field"><label htmlFor="canada-applicant">Applicant</label><select id="canada-applicant" name="applicant_person_id" required defaultValue=""><option value="" disabled>Select a person</option>{people.map(person => <option value={person.id} key={person.id}>{person.first_name} {person.last_name}</option>)}</select></div><div className="button-row field-full"><button className="button">Initialize Canada application</button></div></form>
  </section>;

  const bundle = value;
  const app = bundle.application;
  const trip = bundle.trip_plan;

  async function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    await run(() => api.updateCanadaApplication(app.id, {
      official_application_date: optional(data.get("official_application_date")),
      legal_guardian_person_id: optional(data.get("legal_guardian_person_id")),
      application_date_review_state: String(data.get("application_date_review_state")),
      native_language_code: optional(data.get("native_language_code")),
      preferred_language_code: optional(data.get("preferred_language_code")),
      service_language_code: optional(data.get("service_language_code")),
      mailing_same_as_residential: data.get("mailing_same_as_residential") === "unknown" ? null : data.get("mailing_same_as_residential") === "true",
    }), "Application metadata saved.");
  }

  async function saveTrip(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    await run(() => api.updateCanadaTripPlan(app.id, {
      intake_purpose_text: optional(data.get("intake_purpose_text")),
      imm5257_purpose_code: optional(data.get("imm5257_purpose_code")),
      purpose_review_state: String(data.get("purpose_review_state")),
      arrival_date: optional(data.get("arrival_date")), departure_date: optional(data.get("departure_date")),
    }), "Trip plan saved without automatic purpose mapping.");
  }

  async function addAddress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    await run(() => api.createCanadaAddress(app.id, {
      context: String(data.get("context")), owner_id: app.id,
      street_name: optional(data.get("street_name")), city: optional(data.get("city")),
      state_province: optional(data.get("state_province")), postal_code: optional(data.get("postal_code")),
      country_code: optional(data.get("country_code")), review_state: "unreviewed",
    }), "Owned address added.");
  }

  async function addPassport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    await run(() => api.createCanadaTravelDocument(app.id, {
      person_id: app.applicant_person_id, document_type: "passport", number: String(data.get("number")),
      issuing_country_code: String(data.get("issuing_country_code")), issue_date: optional(data.get("issue_date")),
      expiry_date: optional(data.get("expiry_date")), is_primary: data.get("is_primary") === "on",
      sort_order: bundle.travel_documents.length,
    }), "Travel document added.");
  }

  async function addActivity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    await run(() => api.createCanadaActivity(app.id, {
      person_id: app.applicant_person_id, activity_type: optional(data.get("activity_type")),
      position: optional(data.get("position")), organization_name: optional(data.get("organization_name")),
      period_status: String(data.get("period_status")), start_date: optional(data.get("start_date")),
      end_date: optional(data.get("end_date")), sort_order: bundle.activities.length,
    }), "Applicant activity added.");
  }

  async function saveAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget); const code = String(data.get("question_code"));
    await run(() => api.saveOfficialAnswer(app.id, code, {
      question_code: code, answer: String(data.get("answer")), review_state: String(data.get("review_state")),
      reviewed_by: actor, source_reference: "employee-ui",
    }), "Official answer saved.");
  }

  const counts = [
    ["Roles", value.roles.length], ["Biographies", value.biographies.length], ["Citizenships", value.citizenships.length],
    ["Identifiers", value.identifiers.length], ["Contacts", value.contacts.length], ["Addresses", value.addresses.length],
    ["Residences", value.applicant_residences.length], ["Travel documents", value.travel_documents.length],
    ["Funding sources", value.funding_sources.length], ["Hosts", value.hosts.length], ["Organizations", value.organizations.length],
    ["Family relationships", value.family_relationships.length], ["Education", value.education.length], ["Activities", value.activities.length],
    ["Residence history", value.residence_history.length], ["Travel history", value.travel_history.length],
    ["Official answers", value.official_answers.length], ["Official explanations", value.official_explanations.length], ["Provenance history", value.provenance.length],
  ] as const;

  return <section className="section-card" id="canada-application">
    <div className="section-heading"><div><h2>Canada application</h2><span className="muted">Canonical M9A data — no generator integration</span></div><StatusBadge value={app.application_date_review_state} /></div>
    {message && <div className="success-message" role="status">{message}</div>}{error && <div className="form-error" role="alert">{error}</div>}
    <CanadaImportSection caseId={caseId} onChanged={onChanged} />
    <div className="summary-grid">{counts.map(([label, count]) => <div className="summary-item" key={label}><strong>{count}</strong><span>{label}</span></div>)}</div>
    <details open><summary>Application metadata</summary><form className="form-grid" onSubmit={saveMetadata}><div className="field"><label>Official application date</label><input name="official_application_date" type="date" defaultValue={app.official_application_date ?? ""} /></div><div className="field"><label>Date review</label><select name="application_date_review_state" defaultValue={app.application_date_review_state}>{REVIEW_STATES.map(item => <option key={item}>{item}</option>)}</select></div><div className="field"><label>Legal guardian</label><select name="legal_guardian_person_id" defaultValue={app.legal_guardian_person_id ?? ""}><option value="">None selected</option>{people.filter(person => person.id !== app.applicant_person_id).map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}</option>)}</select></div><div className="field"><label>Native language</label><input name="native_language_code" defaultValue={app.native_language_code ?? ""} /></div><div className="field"><label>Preferred language</label><input name="preferred_language_code" defaultValue={app.preferred_language_code ?? ""} /></div><div className="field"><label>Service language</label><input name="service_language_code" defaultValue={app.service_language_code ?? ""} /></div><div className="field"><label>Mailing equals residential</label><select name="mailing_same_as_residential" defaultValue={app.mailing_same_as_residential === null ? "unknown" : String(app.mailing_same_as_residential)}><option value="unknown">Unknown</option><option value="true">Yes</option><option value="false">No</option></select></div><div className="button-row field-full"><button className="button">Save metadata</button></div></form></details>
    <details open><summary>Trip and purpose</summary><p className="muted">Intake wording and IMM5257 code are separate authoritative fields. No silent mapping occurs.</p><form className="form-grid" onSubmit={saveTrip}><div className="field field-full"><label htmlFor="canada-intake-purpose">Intake purpose text</label><textarea id="canada-intake-purpose" name="intake_purpose_text" defaultValue={trip?.intake_purpose_text ?? ""} /></div><div className="field"><label htmlFor="canada-imm-purpose">IMM5257 purpose code</label><input id="canada-imm-purpose" name="imm5257_purpose_code" defaultValue={trip?.imm5257_purpose_code ?? ""} /></div><div className="field"><label>Purpose review</label><select name="purpose_review_state" defaultValue={trip?.purpose_review_state ?? "unreviewed"}>{REVIEW_STATES.map(item => <option key={item}>{item}</option>)}</select></div><div className="field"><label>Arrival</label><input name="arrival_date" type="date" defaultValue={trip?.arrival_date ?? ""} /></div><div className="field"><label>Departure</label><input name="departure_date" type="date" defaultValue={trip?.departure_date ?? ""} /></div><div className="button-row field-full"><button className="button">Save trip plan</button></div></form></details>
    <details><summary>Add applicant or mailing address</summary><form className="form-grid" onSubmit={addAddress}><div className="field"><label>Context</label><select name="context"><option value="residential">Residential</option><option value="mailing">Mailing</option></select></div><div className="field"><label>Street</label><input name="street_name" /></div><div className="field"><label>City</label><input name="city" /></div><div className="field"><label>State / province</label><input name="state_province" /></div><div className="field"><label>Postal code</label><input name="postal_code" /></div><div className="field"><label>Country code</label><input name="country_code" maxLength={3} /></div><div className="button-row field-full"><button className="button">Add owned address</button></div></form></details>
    <details><summary>Add travel document</summary><form className="form-grid" onSubmit={addPassport}><div className="field"><label>Passport number</label><input name="number" required /></div><div className="field"><label>Issuing country</label><input name="issuing_country_code" maxLength={3} required /></div><div className="field"><label>Issue date</label><input name="issue_date" type="date" /></div><div className="field"><label>Expiry date</label><input name="expiry_date" type="date" /></div><label><input name="is_primary" type="checkbox" /> Primary passport</label><div className="button-row field-full"><button className="button">Add travel document</button></div></form></details>
    <details><summary>Add applicant activity</summary><p className="muted">Current applicant occupation is derived from current ActivityRecord, never from biography.</p><form className="form-grid" onSubmit={addActivity}><div className="field"><label>Activity type</label><input name="activity_type" /></div><div className="field"><label>Position / occupation</label><input name="position" /></div><div className="field"><label>Organization</label><input name="organization_name" /></div><div className="field"><label>Period status</label><select name="period_status"><option value="current">Current</option><option value="completed">Completed</option><option value="unknown">Unknown</option></select></div><div className="field"><label>Start date</label><input name="start_date" type="date" /></div><div className="field"><label>End date</label><input name="end_date" type="date" /></div><div className="button-row field-full"><button className="button">Add activity</button></div></form></details>
    <details><summary>Official answer review</summary><form className="form-grid" onSubmit={saveAnswer}><div className="field"><label htmlFor="canada-question-code">Question code</label><input id="canada-question-code" name="question_code" required /></div><div className="field"><label>Answer</label><select name="answer" defaultValue="unknown"><option value="unknown">Unknown</option><option value="yes">Yes</option><option value="no">No</option><option value="not_applicable">Not applicable</option></select></div><div className="field"><label>Review state</label><select name="review_state" defaultValue="unreviewed">{REVIEW_STATES.map(item => <option key={item}>{item}</option>)}</select></div><div className="button-row field-full"><button className="button">Save official answer</button></div></form></details>
  </section>;
}
