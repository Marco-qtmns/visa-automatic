"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { loadCaseSummaries, type CaseSummary } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

export function CaseListClient() {
  const [items, setItems] = useState<CaseSummary[] | null>(null);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      setItems(await loadCaseSummaries());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Cases could not be loaded.");
    }
  }

  useEffect(() => { void load(); }, []);
  if (error) return <div className="error-panel" role="alert">{error} <button className="button button-small" onClick={() => void load()}>Retry</button></div>;
  if (items === null) return <div className="state-panel">Loading cases…</div>;
  if (!items.length) return <div className="state-panel"><div><h2>No cases yet</h2><p>Create the first case to begin manual intake.</p><Link className="button" href="/cases/new">Create case</Link></div></div>;

  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Case</th><th>Applicant</th><th>Visa / purpose</th><th>State</th><th>Progress</th><th>Next action</th><th>Last updated</th></tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.case.id}>
              <td><Link className="case-link" href={`/cases/${item.case.id}`}>{item.case.case_number}</Link></td>
              <td>{item.applicantName}</td>
              <td>{item.case.visa_type}<br /><span className="muted">{item.case.purpose}</span></td>
              <td><StatusBadge value={item.case.workflow_state} /></td>
              <td>{item.requirementProgress}</td>
              <td>{item.nextAction.title}</td>
              <td>{new Date(item.case.updated_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
