"use client";

import { useState, type FormEvent } from "react";
import { api, type CanonicalValueRevision, type DynamicCaseStatus, type Person } from "@/lib/api";

const actor = process.env.NEXT_PUBLIC_WORKFLOW_ACTOR ?? "manual-ui";

function textValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function triState(value: FormDataEntryValue | null): boolean | null {
  if (value === "yes") return true;
  if (value === "no") return false;
  return null;
}

function triDefault(value: unknown) {
  return value === true ? "yes" : value === false ? "no" : "unknown";
}

export function CanonicalIntakeSection({ caseId, status, revisions, people, onChanged }: {
  caseId: string;
  status: DynamicCaseStatus;
  revisions: CanonicalValueRevision[];
  people: Person[];
  onChanged: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const values = status.canonical_values;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    const data = new FormData(event.currentTarget);
    const optional = (name: string) => String(data.get(name) ?? "").trim() || null;
    const expectedRevision = (fieldPath: string) => Math.max(0, ...revisions.filter(item => item.field_path === fieldPath).map(item => item.revision));
    const decision = (field_path: string, value_json: unknown) => ({ field_path, value_json, expected_revision: expectedRevision(field_path) });
    try {
      await api.applyCanonicalDecisions(caseId, [
        decision("case.visa_type", String(data.get("visa_type") ?? "").trim()),
        decision("applicant.given_names", String(data.get("given_names") ?? "").trim()),
        decision("applicant.family_name", String(data.get("family_name") ?? "").trim()),
        decision("contact.email", optional("email")), decision("contact.phone", optional("phone")),
        decision("trip.purpose", optional("purpose")), decision("destination.country_code", optional("destination")),
        decision("sponsor.exists", triState(data.get("sponsor_exists"))), decision("sponsor.person_id", optional("sponsor_person_id")),
        decision("host.exists", triState(data.get("host_exists"))), decision("host.person_id", optional("host_person_id")),
        decision("trip.payer", optional("payer")), decision("commercial.instructions", optional("commercial_instructions")),
        decision("special.circumstances", optional("special_circumstances")), decision("additional.notes", optional("additional_notes")),
      ], actor);
      setMessage("Canonical intake information saved and requirements recalculated.");
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Canonical information could not be saved.");
    } finally { setBusy(false); }
  }

  return <section className="section-card" id="canonical-intake">
    <div className="section-heading"><div><h2>Canonical intake information</h2><span className="muted">Manual, CSV, and Commercial evidence converge here. Unknown values remain unresolved.</span></div></div>
    {message && <div className="success-message" role="status">{message}</div>}{error && <div className="form-error" role="alert">{error}</div>}
    <form className="form-grid" onSubmit={save}>
      <div className="field"><label htmlFor="canonical-given">Given names</label><input id="canonical-given" name="given_names" required defaultValue={textValue(values["applicant.given_names"])} /></div>
      <div className="field"><label htmlFor="canonical-family">Family name</label><input id="canonical-family" name="family_name" required defaultValue={textValue(values["applicant.family_name"])} /></div>
      <div className="field"><label htmlFor="canonical-email">Email</label><input id="canonical-email" name="email" type="email" defaultValue={textValue(values["contact.email"])} /></div>
      <div className="field"><label htmlFor="canonical-phone">Phone</label><input id="canonical-phone" name="phone" defaultValue={textValue(values["contact.phone"])} /></div>
      <div className="field"><label htmlFor="canonical-visa">Visa type</label><input id="canonical-visa" name="visa_type" required defaultValue={textValue(values["case.visa_type"])} /></div>
      <div className="field"><label htmlFor="canonical-destination">Destination country</label><input id="canonical-destination" name="destination" maxLength={3} defaultValue={textValue(values["destination.country_code"])} /></div>
      <div className="field field-full"><label htmlFor="canonical-purpose">Travel purpose</label><input id="canonical-purpose" name="purpose" defaultValue={textValue(values["trip.purpose"])} /></div>
      <div className="field"><label htmlFor="canonical-sponsor">Financial sponsor</label><select id="canonical-sponsor" name="sponsor_exists" defaultValue={triDefault(values["sponsor.exists"])}><option value="unknown">Unknown</option><option value="yes">Yes</option><option value="no">No</option></select></div>
      <div className="field"><label htmlFor="canonical-sponsor-person">Sponsor identity</label><select id="canonical-sponsor-person" name="sponsor_person_id" defaultValue={textValue(values["sponsor.person_id"])}><option value="">Not selected</option>{people.filter(person => !person.roles.includes("applicant")).map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}</option>)}</select></div>
      <div className="field"><label htmlFor="canonical-host">Host in Canada</label><select id="canonical-host" name="host_exists" defaultValue={triDefault(values["host.exists"])}><option value="unknown">Unknown</option><option value="yes">Yes</option><option value="no">No</option></select></div>
      <div className="field"><label htmlFor="canonical-host-person">Host identity</label><select id="canonical-host-person" name="host_person_id" defaultValue={textValue(values["host.person_id"])}><option value="">Not selected</option>{people.filter(person => !person.roles.includes("applicant")).map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}</option>)}</select></div>
      <div className="field"><label htmlFor="canonical-payer">Trip payer</label><select id="canonical-payer" name="payer" defaultValue={textValue(values["trip.payer"])}><option value="">Unknown</option><option value="applicant">Applicant / self-funded</option><option value="sponsor">Sponsor</option><option value="mixed">Mixed funding</option><option value="other">Other</option></select></div>
      <div className="field field-full"><label htmlFor="canonical-instructions">Commercial instructions</label><textarea id="canonical-instructions" name="commercial_instructions" defaultValue={textValue(values["commercial.instructions"])} /></div>
      <div className="field field-full"><label htmlFor="canonical-special">Special circumstances</label><textarea id="canonical-special" name="special_circumstances" defaultValue={textValue(values["special.circumstances"])} /></div>
      <div className="field field-full"><label htmlFor="canonical-notes">Additional notes</label><textarea id="canonical-notes" name="additional_notes" defaultValue={textValue(values["additional.notes"])} /></div>
      <div className="button-row field-full"><button className="button" disabled={busy}>{busy ? "Saving…" : "Save canonical information"}</button></div>
    </form>
  </section>;
}
