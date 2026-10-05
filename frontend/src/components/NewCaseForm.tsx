"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";

export function NewCaseForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError("");
    const data = new FormData(event.currentTarget);
    try {
      const created = await api.createCase({
        case_number: String(data.get("case_number")),
        visa_type: String(data.get("visa_type")),
        purpose: String(data.get("purpose")),
      });
      router.push(`/cases/${created.id}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Case could not be created."); }
    finally { setSaving(false); }
  }

  return <form className="panel form-grid" onSubmit={submit}>
    <div className="field"><label htmlFor="case_number">Case number</label><input id="case_number" name="case_number" required maxLength={64} /></div>
    <div className="field"><label htmlFor="visa_type">Visa type</label><input id="visa_type" name="visa_type" required maxLength={64} /></div>
    <div className="field field-full"><label htmlFor="purpose">Purpose</label><input id="purpose" name="purpose" required maxLength={128} /></div>
    {error && <div className="form-error field-full" role="alert">{error}</div>}
    <div className="button-row field-full"><button className="button" disabled={saving}>{saving ? "Creating…" : "Create case"}</button></div>
  </form>;
}
