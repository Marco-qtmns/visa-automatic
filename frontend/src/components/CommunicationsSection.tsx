"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import {
  api,
  type ConversationImport,
  type ConversationMessage,
  type Fact,
  type FactExtractionCandidate,
  type FactExtractionRun,
} from "@/lib/api";
import { StatusBadge } from "./StatusBadge";

const reviewer = process.env.NEXT_PUBLIC_WORKFLOW_ACTOR ?? "manual-ui";

function valueText(value: unknown) {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function parsedValue(value: string): unknown {
  try { return JSON.parse(value); } catch { return value; }
}

type Props = {
  caseId: string;
  conversations: ConversationImport[];
  messages: ConversationMessage[];
  runs: FactExtractionRun[];
  candidates: FactExtractionCandidate[];
  facts: Fact[];
  onChanged: () => Promise<void>;
};

export function CommunicationsSection({ caseId, conversations, messages, runs, candidates, facts, onChanged }: Props) {
  const [pasteOpen, setPasteOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [reviewing, setReviewing] = useState<{ candidate: FactExtractionCandidate; action: "accept" | "correct" | "reject" } | null>(null);

  async function paste(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setMessage("");
    const text = String(new FormData(event.currentTarget).get("conversation") ?? "");
    try { const result = await api.pasteConversation(caseId, text, reviewer); setMessage(`${result.message_count} messages imported.`); setPasteOpen(false); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Conversation could not be imported."); }
  }
  async function upload() {
    if (!file) { setError("Select a WhatsApp .txt export."); return; }
    setBusy("upload"); setError(""); setMessage("");
    try { const result = await api.uploadConversation(caseId, file, reviewer); setMessage(`${result.message_count} messages imported from ${file.name}.`); setFile(null); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Conversation export could not be imported."); }
    finally { setBusy(null); }
  }
  async function extract(conversationId: string) {
    setBusy(conversationId); setError(""); setMessage("");
    try { const run = await api.extractConversationFacts(conversationId); setMessage(run.status === "failed" ? "Fact extraction unavailable. Manual fact entry remains available." : `${run.candidate_count} fact candidates extracted.`); await onChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Fact extraction could not be completed."); }
    finally { setBusy(null); }
  }
  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!reviewing) return;
    const data = new FormData(event.currentTarget); const reason = String(data.get("reason") ?? "").trim();
    setError("");
    try {
      if (reviewing.action === "accept") await api.acceptFactCandidate(reviewing.candidate.id, reviewer, reason);
      else if (reviewing.action === "reject") await api.rejectFactCandidate(reviewing.candidate.id, reviewer, reason);
      else await api.correctFactCandidate(reviewing.candidate.id, reviewer, reason, parsedValue(String(data.get("value_json") ?? "")));
      setReviewing(null); await onChanged();
    } catch (reasonValue) { setError(reasonValue instanceof Error ? reasonValue.message : "Candidate review could not be saved."); }
  }
  function selectFile(event: ChangeEvent<HTMLInputElement>) { setFile(event.target.files?.[0] ?? null); }

  const pending = candidates.filter(item => item.status === "proposed" || item.status === "conflict");
  return <section className="section-card" id="communications">
    <div className="section-heading"><div><h2>WhatsApp communications</h2><span className="muted">Imported conversations are evidence. Facts become authoritative only after employee review.</span></div><button className="button button-small" onClick={() => setPasteOpen(!pasteOpen)}>Paste conversation</button></div>
    {message && <div className="success-message" role="status">{message}</div>}{error && <div className="form-error" role="alert">{error}</div>}
    {pasteOpen && <form className="form-grid" onSubmit={paste}><div className="field field-full"><label htmlFor="whatsapp-paste">Conversation text</label><textarea id="whatsapp-paste" name="conversation" required /></div><div className="button-row field-full"><button className="button">Import pasted conversation</button><button className="button button-secondary" type="button" onClick={() => setPasteOpen(false)}>Cancel</button></div></form>}
    <div className="form-grid"><div className="field field-full"><label htmlFor="whatsapp-file">Import WhatsApp .txt</label><input id="whatsapp-file" type="file" accept="text/plain,.txt" onChange={selectFile} /><span className="muted">Plain-text exports only; attachments are not imported.</span></div><div className="button-row field-full"><button className="button button-secondary" type="button" disabled={busy === "upload"} onClick={() => void upload()}>{busy === "upload" ? "Importing…" : "Import selected .txt"}</button></div></div>

    {!conversations.length ? <div className="empty-state">No WhatsApp conversations imported.</div> : <div className="record-list">{conversations.map(item => {
      const history = runs.filter(run => run.conversation_import_id === item.id);
      return <div className="record" key={item.id}><div className="record-head"><div><h3>{item.original_filename ?? "Pasted WhatsApp conversation"}</h3><div className="record-meta"><StatusBadge value={item.parse_status} /><span className="badge">{item.message_count} messages</span></div><p className="muted">Imported {new Date(item.imported_at).toLocaleString()}{item.imported_by ? ` by ${item.imported_by}` : ""}</p></div><button className="button button-secondary button-small" disabled={busy === item.id} onClick={() => void extract(item.id)}>{busy === item.id ? "Extracting…" : "Extract facts"}</button></div>
        {item.parse_warnings_json.length > 0 && <details><summary>Parser warnings ({item.parse_warnings_json.length})</summary><ul>{item.parse_warnings_json.map((warning, index) => <li key={index}>{warning.line ? `Line ${warning.line}: ` : ""}{warning.message}</li>)}</ul></details>}
        {history.length > 0 && <details><summary>Extraction history ({history.length})</summary><ul>{history.map(run => <li key={run.id}>{new Date(run.created_at).toLocaleString()} — {run.status}; {run.candidate_count} candidates{run.failure_reason ? `; ${run.failure_reason}` : ""}</li>)}</ul></details>}
      </div>;
    })}</div>}

    <h3>WhatsApp facts to review</h3>
    {!pending.length ? <div className="empty-state">No extracted facts require review.</div> : <div className="record-list">{pending.map(candidate => {
      const sourceMessages = candidate.source_message_ids_json.map(id => messages.find(item => item.id === id)).filter((item): item is ConversationMessage => Boolean(item));
      const sourceImport = conversations.find(item => item.id === candidate.conversation_import_id);
      const current = candidate.conflicting_fact_id ? facts.find(item => item.id === candidate.conflicting_fact_id) : undefined;
      return <div className={`record ${candidate.status === "conflict" ? "record-conflict" : ""}`} key={candidate.id}><div className="record-head"><div><h3>{candidate.key}{candidate.status === "conflict" ? " — conflict" : ""}</h3><div className="record-meta"><StatusBadge value={candidate.status} /><span className="badge">{Math.round(candidate.confidence * 100)}% confidence</span></div></div></div>
        {current && <p><strong>Current confirmed value:</strong> {valueText(current.value_json)}</p>}<p><strong>WhatsApp suggestion:</strong> {valueText(candidate.value_json)}</p><blockquote>{candidate.evidence}</blockquote>
        {sourceImport && <p className="muted">Import: {sourceImport.original_filename ?? `pasted conversation from ${new Date(sourceImport.imported_at).toLocaleString()}`}</p>}
        {sourceMessages.map(source => <p className="muted" key={source.id}>Source: {source.sender ?? "System/unknown sender"}{source.message_timestamp ? ` · ${new Date(source.message_timestamp).toLocaleString()}` : ""} · message {source.sequence_number}</p>)}
        <div className="button-row"><button className="button button-small" onClick={() => setReviewing({ candidate, action: "accept" })}>{candidate.status === "conflict" ? "Use WhatsApp value" : "Accept"}</button><button className="button button-secondary button-small" onClick={() => setReviewing({ candidate, action: "correct" })}>Correct</button><button className="button button-danger button-small" onClick={() => setReviewing({ candidate, action: "reject" })}>{candidate.status === "conflict" ? "Keep current value" : "Reject"}</button></div>
      </div>;
    })}</div>}
    {reviewing && <form className="form-grid" onSubmit={review}><h3 className="field-full">Review {reviewing.candidate.key}</h3>{reviewing.action === "correct" && <div className="field field-full"><label htmlFor="candidate-value">Correct value</label><input id="candidate-value" name="value_json" required defaultValue={valueText(reviewing.candidate.value_json)} /></div>}<div className="field field-full"><label htmlFor="candidate-reason">Reason</label><textarea id="candidate-reason" name="reason" required minLength={3} /></div><div className="button-row field-full"><button className="button">Save decision</button><button className="button button-secondary" type="button" onClick={() => setReviewing(null)}>Cancel</button></div></form>}
  </section>;
}
