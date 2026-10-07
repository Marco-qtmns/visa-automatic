"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

export function NewCaseForm() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function create(source?: "csv" | "documents" | "whatsapp") {
    setSaving(true); setError("");
    try {
      const created = await api.createCase({});
      window.dispatchEvent(new Event("visa-bootstrap-refresh"));
      const target = source === "csv" ? "canada-import" : source === "documents" ? "documents" : source === "whatsapp" ? "communications" : "";
      router.push(`/cases/${created.id}${target ? `#${target}` : ""}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Case could not be created."); }
    finally { setSaving(false); }
  }

  return <section className="panel source-first">
    <h2>Add whatever information is currently available</h2>
    <p className="muted">No applicant name is required. The case number is generated automatically and the applicant name will come from confirmed application information.</p>
    {error && <div className="form-error" role="alert">{error}</div>}
    <div className="source-actions">
      <button type="button" className="button" disabled={saving} onClick={() => void create("csv")}>Upload Google Forms / CSV</button>
      <button type="button" className="button" disabled={saving} onClick={() => void create("documents")}>Upload documents</button>
      <button type="button" className="button" disabled={saving} onClick={() => void create("whatsapp")}>Paste / upload WhatsApp</button>
      <button type="button" className="button button-secondary" disabled={saving} onClick={() => void create()}>Create empty application</button>
    </div>
    {saving && <p role="status">Creating application…</p>}
  </section>;
}
