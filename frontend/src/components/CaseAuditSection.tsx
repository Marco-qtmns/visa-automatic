"use client";

import { useEffect, useState } from "react";
import { api, type AuditEvent } from "@/lib/api";
import { AuditTable } from "./AdminUsersClient";

export function CaseAuditSection({ caseId }: { caseId: string }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { api.listCaseAudit(caseId).then(setEvents).catch(reason => setError(reason instanceof Error ? reason.message : "Audit could not be loaded.")); }, [caseId]);
  return <section className="section-card" id="audit"><h2>Case audit</h2>{error ? <div className="form-error" role="alert">{error}</div> : <AuditTable events={events} />}</section>;
}
