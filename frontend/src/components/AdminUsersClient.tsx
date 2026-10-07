"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type AdminUser, type AuditEvent, type AuthUser } from "@/lib/api";
import { useCurrentUser } from "./AuthShell";

const roles: AuthUser["role"][] = ["CASE_WORKER", "REVIEWER", "ADMIN"];

export function AdminUsersClient() {
  const current = useCurrentUser();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [nextUsers, nextEvents] = await Promise.all([api.listUsers(), api.listSecurityAudit()]);
      setUsers(nextUsers); setEvents(nextEvents); setError("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Administration data could not be loaded."); }
  }, []);
  useEffect(() => { if (current?.role === "ADMIN") void load(); }, [current, load]);
  if (current?.role !== "ADMIN") return <div className="error-panel" role="alert">Administrator permission is required.</div>;

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    try {
      await api.createUser({ email: String(values.get("email")), display_name: String(values.get("display_name")), password: String(values.get("password")), role: String(values.get("role")) as AuthUser["role"] });
      event.currentTarget.reset(); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "User could not be created."); }
  }
  async function act(operation: () => Promise<unknown>, confirmation?: string) {
    if (confirmation && !window.confirm(confirmation)) return;
    try { await operation(); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Action failed."); }
  }

  return <div className="detail-stack">
    <div className="page-heading"><div><p className="eyebrow">Administration</p><h1>Users &amp; security audit</h1></div></div>
    {error ? <div className="error-panel" role="alert">{error}</div> : null}
    <section className="section-card"><h2>Create employee</h2><form className="form-grid" onSubmit={create}>
      <div className="field"><label>Email</label><input name="email" type="email" required /></div>
      <div className="field"><label>Display name</label><input name="display_name" required /></div>
      <div className="field"><label>Temporary password</label><input name="password" type="password" required /></div>
      <div className="field"><label>Role</label><select name="role">{roles.map(role => <option key={role}>{role}</option>)}</select></div>
      <div className="button-row field-full"><button className="button">Create user</button></div>
    </form></section>
    <section className="section-card"><h2>Employees</h2><div className="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>Status</th><th>MFA / sessions</th><th>Actions</th></tr></thead><tbody>{users.map(user => <tr key={user.id}>
      <td><strong>{user.display_name}</strong><div className="muted">{user.email}</div><div className="muted">Last login: {user.last_successful_login_at ? new Date(user.last_successful_login_at).toLocaleString() : "Never"}</div></td>
      <td><select aria-label={`Role for ${user.email}`} value={user.role} onChange={event => void act(() => api.updateUser(user.id, { role: event.target.value as AuthUser["role"] }), "Change this employee's role?")}>{roles.map(role => <option key={role}>{role}</option>)}</select></td>
      <td>{user.is_active ? "Active" : "Inactive"}</td><td>{user.mfa_enabled ? "Enrolled" : "Not enrolled"} · {user.active_session_count} active</td>
      <td><div className="button-row"><button className="button button-secondary button-small" onClick={() => void act(() => api.updateUser(user.id, { is_active: !user.is_active }), user.is_active ? "Deactivate this employee and revoke access?" : undefined)}>{user.is_active ? "Deactivate" : "Activate"}</button><button className="button button-secondary button-small" onClick={() => void act(() => api.revokeUserSessions(user.id), "Revoke all active sessions?")}>Revoke sessions</button><button className="button button-danger button-small" onClick={() => void act(() => api.resetUserMfa(user.id), "Reset MFA and revoke all sessions?")}>Reset MFA</button></div></td>
    </tr>)}</tbody></table></div></section>
    <section className="section-card"><h2>Security audit</h2><AuditTable events={events} /></section>
  </div>;
}

export function AuditTable({ events }: { events: AuditEvent[] }) {
  if (!events.length) return <div className="empty-state">No audit events recorded.</div>;
  return <div className="table-wrap"><table><thead><tr><th>Time</th><th>Action</th><th>Actor</th><th>Target</th><th>Details</th><th>Outcome</th></tr></thead><tbody>{events.map(event => <tr key={event.id}><td>{new Date(event.created_at).toLocaleString()}</td><td><strong>{event.action}</strong></td><td>{event.actor_display_name || event.actor_email || event.actor_role || "System"}<div className="muted">{event.actor_display_name && event.actor_email ? event.actor_email : event.actor_role}</div></td><td>{event.target_entity_type}{event.target_entity_id ? ` · ${event.target_entity_id}` : ""}</td><td className="muted">{Object.keys(event.metadata_json).length ? JSON.stringify(event.metadata_json) : "—"}</td><td>{event.outcome}</td></tr>)}</tbody></table></div>;
}
