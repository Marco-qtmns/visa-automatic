"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { loadCaseSummaries, type CaseSummary } from "@/lib/api";
import { useBootstrapCases } from "./AuthShell";
import { StatusBadge } from "./StatusBadge";

export function CaseListClient() {
  const bootstrapCases = useBootstrapCases();
  const [items, setItems] = useState<CaseSummary[] | null>(bootstrapCases);
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      setItems(await loadCaseSummaries());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Cases could not be loaded.");
    }
  }

  useEffect(() => { if (bootstrapCases === null) void load(); }, [bootstrapCases]);
  if (error) return <div className="error-panel" role="alert">{error} <button className="button button-small" onClick={() => void load()}>Retry</button></div>;
  if (items === null) return <div className="state-panel">Loading cases…</div>;
  if (!items.length) return <div className="state-panel"><div><h2>No applications yet</h2><p>Start with a source or create an empty application.</p><Link className="button" href="/cases/new">New application</Link></div></div>;

  const queues: CaseSummary["queue"][] = ["ACTION_REQUIRED", "REVIEW", "READY", "WAITING"];
  return <div className="case-queues">
    {queues.map(queue => {
      const group = items.filter(item => item.queue === queue);
      if (!group.length) return null;
      return <section key={queue} className="section-card"><div className="section-heading"><h2>{queue.replaceAll("_", " / ")}</h2><span className="badge">{group.length}</span></div><div className="table-wrap">
      <table>
        <thead><tr><th>Applicant</th><th>Case</th><th>Stage</th><th>Open issues</th><th>Next action</th><th>Last updated</th></tr></thead>
        <tbody>
          {group.map((item) => (
            <tr key={item.id}>
              <td><Link className="case-link" href={`/cases/${item.id}`}>{item.display_name}</Link></td>
              <td>{item.case_number}<br /><span className="muted">{item.visa_type}</span></td>
              <td><StatusBadge value={item.workflow_state} /></td>
              <td>{item.issue_count}</td>
              <td>{item.next_action}</td>
              <td>{new Date(item.updated_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div></section>;
    })}
  </div>;
}
