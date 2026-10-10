import type {
  CaseCreate,
  CaseDetailBundle,
  CaseRecord,
  CaseSummary,
  CaseUpdate,
  ConversationImport,
  ConversationMessage,
  DocumentRecord,
  DocumentTypeDefinition,
  DocumentUpdate,
  Fact,
  FactExtractionCandidate,
  FactExtractionRun,
  FactInput,
  NextAction,
  PreparationStatus,
  PreparationRun,
  Person,
  PersonInput,
  Requirement,
  RequirementCreate,
  RequirementEvaluationResult,
  RequirementDocumentMatch,
  DocumentClassification,
  DocumentQualityCheck,
  RequirementCompletenessEvaluation,
  RequirementUpdate,
  TaskInput,
  TaskRecord,
  Workflow,
  WorkflowState,
  CanadaApplicationBundle,
  CanadaApplicationRecord,
  CanadaImportRun,
  CanadaImportChange,
  IntakeMetrics,
  IntakeSubmission,
} from "./types";

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (typeof detail === "object" && detail !== null && "message" in detail) {
    const message = String(detail.message);
    const location = [
      "section" in detail ? String(detail.section ?? "") : "",
      "field_path" in detail ? String(detail.field_path ?? "") : "",
    ].filter(Boolean).join(" · ");
    const rawReasons = "blocking_reasons" in detail && Array.isArray(detail.blocking_reasons)
      ? detail.blocking_reasons
      : "issues" in detail && Array.isArray(detail.issues) ? detail.issues : [];
    const reasons = rawReasons
          .map((item) => typeof item === "object" && item !== null && "message" in item ? String(item.message) : null)
          .map((item, index) => item ?? (typeof rawReasons[index] === "string" ? String(rawReasons[index]) : null))
          .filter(Boolean)
      ;
    const located = location ? `${location}: ${message}` : message;
    return reasons.length ? `${located} ${reasons.join("; ")}` : located;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        typeof item === "object" && item !== null && "msg" in item
          ? String(item.msg)
          : null,
      )
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      cache: "no-store",
      credentials: "include",
      headers: {
        ...(init?.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...(!["GET", "HEAD"].includes((init?.method ?? "GET").toUpperCase())
          ? { "X-CSRF-Token": csrfTokenFromCookie() }
          : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError("Visa Automatic backend is not reachable.");
  }
  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event("visa-auth-expired"));
    }
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(
      errorMessage(detail, "Changes could not be saved."),
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function csrfTokenFromCookie(): string {
  if (typeof document === "undefined") return "";
  const item = document.cookie.split(";").map((value) => value.trim())
    .find((value) => value.startsWith("va_csrf="));
  return item ? decodeURIComponent(item.slice("va_csrf=".length)) : "";
}

export type AuthUser = {
  id: string; email: string; display_name: string;
  role: "ADMIN" | "CASE_WORKER" | "REVIEWER";
  is_active: boolean; mfa_enabled: boolean;
};
export type LoginChallenge = {
  status: "mfa_required" | "mfa_enrollment_required";
  challenge_token: string; expires_in_seconds: number;
  enrollment_secret: string | null; provisioning_uri: string | null;
};
export type Authenticated = { status: "authenticated"; user: AuthUser; csrf_token: string };
export type ApplicationBootstrap = {
  user: AuthUser;
  case_summary: CaseSummary[];
  timings_ms: { database: number; total: number };
};
export type AdminUser = AuthUser & {
  created_at: string; last_successful_login_at: string | null; active_session_count: number;
};
export type AuditEvent = {
  id: string; created_at: string; actor_user_id: string | null; actor_role: string | null;
  actor_display_name: string | null; actor_email: string | null;
  action: string; target_entity_type: string; target_entity_id: string | null;
  case_id: string | null; outcome: string; metadata_json: Record<string, unknown>;
};

const json = (method: "POST" | "PATCH" | "PUT", body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export const api = {
  login: (email: string, password: string) =>
    request<LoginChallenge>("/auth/login", json("POST", { email, password })),
  verifyMfa: (challengeToken: string, code: string) =>
    request<Authenticated>("/auth/mfa/verify", json("POST", { challenge_token: challengeToken, code })),
  me: () => request<{ user: AuthUser }>("/auth/me"),
  bootstrap: () => request<ApplicationBootstrap>("/app/bootstrap"),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  listUsers: () => request<AdminUser[]>("/auth/users"),
  createUser: (payload: { email: string; display_name: string; password: string; role: AuthUser["role"] }) =>
    request<AuthUser>("/auth/users", json("POST", payload)),
  updateUser: (userId: string, payload: { display_name?: string; role?: AuthUser["role"]; is_active?: boolean }) =>
    request<AdminUser>(`/auth/users/${userId}`, json("PATCH", payload)),
  revokeUserSessions: (userId: string) =>
    request<{ status: "ok"; user_id: string; revoked_sessions: number }>(`/auth/users/${userId}/sessions/revoke`, json("POST", {})),
  resetUserMfa: (userId: string) =>
    request<{ status: "ok"; user_id: string; revoked_sessions: number }>(`/auth/users/${userId}/mfa/reset`, json("POST", {})),
  listSecurityAudit: () => request<AuditEvent[]>("/auth/audit-events"),
  listCaseAudit: (caseId: string) => request<AuditEvent[]>(`/cases/${caseId}/audit-events`),
  listIntakeSubmissions: () => request<IntakeSubmission[]>("/intake/submissions"),
  intakeMetrics: () => request<IntakeMetrics>("/intake/metrics"),
  uploadGoogleFormsIntake: (file: File, sourceExternalId?: string, caseId?: string) => {
    const body = new FormData(); body.set("file", file);
    if (sourceExternalId) body.set("source_external_id", sourceExternalId);
    if (caseId) body.set("case_id", caseId);
    return request<IntakeSubmission>("/intake/submissions/google-forms-csv", { method: "POST", body });
  },
  retryIntakeSubmission: (submissionId: string, caseId?: string) =>
    request<IntakeSubmission>(`/intake/submissions/${submissionId}/retry`, json("POST", { case_id: caseId || null })),
  listCases: () => request<CaseRecord[]>("/cases"),
  createCase: (payload: CaseCreate) =>
    request<CaseRecord>("/cases", json("POST", payload)),
  getCase: (caseId: string) => request<CaseRecord>(`/cases/${caseId}`),
  updateCase: (caseId: string, payload: CaseUpdate) =>
    request<CaseRecord>(`/cases/${caseId}`, json("PATCH", payload)),

  listPeople: (caseId: string) => request<Person[]>(`/cases/${caseId}/persons`),
  createPerson: (caseId: string, payload: PersonInput) =>
    request<Person>(`/cases/${caseId}/persons`, json("POST", payload)),
  updatePerson: (personId: string, payload: Partial<PersonInput>) =>
    request<Person>(`/persons/${personId}`, json("PATCH", payload)),

  listFacts: (caseId: string) => request<Fact[]>(`/cases/${caseId}/facts`),
  createFact: (caseId: string, payload: FactInput) =>
    request<Fact>(`/cases/${caseId}/facts`, json("POST", payload)),
  updateFact: (factId: string, payload: Partial<FactInput>) =>
    request<Fact>(`/facts/${factId}`, json("PATCH", payload)),

  pasteConversation: (caseId: string, text: string, importedBy?: string) =>
    request<ConversationImport>(
      `/cases/${caseId}/conversations/whatsapp/paste`,
      json("POST", { text, ...(importedBy ? { imported_by: importedBy } : {}) }),
    ),
  uploadConversation: (caseId: string, file: File, importedBy?: string) => {
    const form = new FormData(); form.set("file", file);
    if (importedBy) form.set("imported_by", importedBy);
    return request<ConversationImport>(`/cases/${caseId}/conversations/whatsapp/upload`, { method: "POST", body: form });
  },
  listConversations: (caseId: string) =>
    request<ConversationImport[]>(`/cases/${caseId}/conversations`),
  listConversationMessages: (conversationId: string) =>
    request<ConversationMessage[]>(`/conversations/${conversationId}/messages`),
  extractConversationFacts: (conversationId: string) =>
    request<FactExtractionRun>(`/conversations/${conversationId}/extract-facts`, json("POST", {})),
  listFactExtractionRuns: (conversationId: string) =>
    request<FactExtractionRun[]>(`/conversations/${conversationId}/extraction-runs`),
  listFactCandidates: (conversationId: string) =>
    request<FactExtractionCandidate[]>(`/conversations/${conversationId}/fact-candidates`),
  acceptFactCandidate: (candidateId: string, reviewedBy: string, reason: string) =>
    request<FactExtractionCandidate>(`/fact-candidates/${candidateId}/accept`, json("POST", { reviewed_by: reviewedBy, reason })),
  correctFactCandidate: (candidateId: string, reviewedBy: string, reason: string, valueJson: unknown) =>
    request<FactExtractionCandidate>(`/fact-candidates/${candidateId}/correct`, json("POST", { reviewed_by: reviewedBy, reason, value_json: valueJson })),
  rejectFactCandidate: (candidateId: string, reviewedBy: string, reason: string) =>
    request<FactExtractionCandidate>(`/fact-candidates/${candidateId}/reject`, json("POST", { reviewed_by: reviewedBy, reason })),

  listRequirements: (caseId: string) =>
    request<Requirement[]>(`/cases/${caseId}/requirements`),
  createRequirement: (caseId: string, payload: RequirementCreate) =>
    request<Requirement>(
      `/cases/${caseId}/requirements`,
      json("POST", payload),
    ),
  updateRequirement: (requirementId: string, payload: RequirementUpdate) =>
    request<Requirement>(
      `/requirements/${requirementId}`,
      json("PATCH", payload),
    ),
  evaluateRequirements: (caseId: string) =>
    request<RequirementEvaluationResult>(
      `/cases/${caseId}/requirements/evaluate`,
      json("POST", {}),
    ),

  listDocuments: (caseId: string) =>
    request<DocumentRecord[]>(`/cases/${caseId}/documents`),
  listDocumentTypes: () => request<DocumentTypeDefinition[]>("/document-types"),
  uploadDocument: (
    caseId: string,
    file: File,
    documentType?: string,
    personId?: string,
  ) => {
    const form = new FormData();
    form.set("file", file);
    if (documentType) form.set("document_type", documentType);
    if (personId) form.set("person_id", personId);
    return request<DocumentRecord>(`/cases/${caseId}/documents/upload`, {
      method: "POST",
      body: form,
    });
  },
  updateDocument: (documentId: string, payload: DocumentUpdate) =>
    request<DocumentRecord>(
      `/documents/${documentId}`,
      json("PATCH", payload),
    ),
  classifyDocument: (documentId: string) =>
    request<DocumentClassification>(
      `/documents/${documentId}/classify`,
      json("POST", {}),
    ),
  listDocumentClassifications: (documentId: string) =>
    request<DocumentClassification[]>(`/documents/${documentId}/classifications`),
  acceptClassification: (documentId: string, classificationId: string, reviewedBy: string) =>
    request<DocumentClassification>(
      `/documents/${documentId}/classifications/${classificationId}/accept`,
      json("POST", { reviewed_by: reviewedBy }),
    ),
  correctClassification: (
    documentId: string,
    classificationId: string,
    payload: { reviewed_by: string; document_type: string; person_id: string },
  ) => request<DocumentClassification>(
    `/documents/${documentId}/classifications/${classificationId}/correct`,
    json("POST", payload),
  ),
  rejectClassification: (documentId: string, classificationId: string, reviewedBy: string) =>
    request<DocumentClassification>(
      `/documents/${documentId}/classifications/${classificationId}/reject`,
      json("POST", { reviewed_by: reviewedBy }),
    ),
  runQualityCheck: (documentId: string) =>
    request<DocumentQualityCheck>(`/documents/${documentId}/quality-check`, json("POST", {})),
  listQualityChecks: (documentId: string) =>
    request<DocumentQualityCheck[]>(`/documents/${documentId}/quality-checks`),
  acceptQuality: (documentId: string, checkId: string, reviewedBy: string, reason: string) =>
    request<DocumentQualityCheck>(
      `/documents/${documentId}/quality-checks/${checkId}/accept`,
      json("POST", { reviewed_by: reviewedBy, reason }),
    ),
  rejectQuality: (documentId: string, checkId: string, reviewedBy: string, reason: string) =>
    request<DocumentQualityCheck>(
      `/documents/${documentId}/quality-checks/${checkId}/reject`,
      json("POST", { reviewed_by: reviewedBy, reason }),
    ),
  matchingRequirements: (documentId: string) =>
    request<Requirement[]>(`/documents/${documentId}/matching-requirements`),
  listDocumentMatches: (caseId: string) =>
    request<RequirementDocumentMatch[]>(`/cases/${caseId}/document-matches`),
  matchDocument: (requirementId: string, documentId: string, createdBy?: string) =>
    request<RequirementDocumentMatch>(
      `/requirements/${requirementId}/documents/${documentId}`,
      json("POST", createdBy ? { created_by: createdBy } : {}),
    ),
  unmatchDocument: (requirementId: string, documentId: string) =>
    request<void>(`/requirements/${requirementId}/documents/${documentId}`, {
      method: "DELETE",
    }),
  evaluateCompleteness: (requirementId: string) =>
    request<RequirementCompletenessEvaluation>(
      `/requirements/${requirementId}/evaluate-completeness`, json("POST", {}),
    ),
  listCompletenessEvaluations: (requirementId: string) =>
    request<RequirementCompletenessEvaluation[]>(
      `/requirements/${requirementId}/completeness-evaluations`,
    ),
  documentContentUrl: (documentId: string) =>
    `${API_BASE_URL}/documents/${documentId}/content`,

  listTasks: (caseId: string) => request<TaskRecord[]>(`/cases/${caseId}/tasks`),
  createTask: (caseId: string, payload: TaskInput) =>
    request<TaskRecord>(`/cases/${caseId}/tasks`, json("POST", payload)),
  updateTask: (taskId: string, payload: Partial<TaskInput>) =>
    request<TaskRecord>(`/tasks/${taskId}`, json("PATCH", payload)),

  getWorkflow: (caseId: string) =>
    request<Workflow>(`/cases/${caseId}/workflow`),
  getNextAction: (caseId: string) =>
    request<NextAction>(`/cases/${caseId}/next-action`),
  getPreparation: (caseId: string) =>
    request<PreparationStatus>(`/cases/${caseId}/preparation`),
  prepare: (caseId: string, initiatedBy: string) =>
    request<PreparationRun>(`/cases/${caseId}/prepare`, json("POST", { initiated_by: initiatedBy })),
  listPreparationRuns: (caseId: string) =>
    request<PreparationRun[]>(`/cases/${caseId}/preparation-runs`),
  preparationArtifactContentUrl: (artifactId: string, download = false) =>
    `${API_BASE_URL}/preparation-artifacts/${artifactId}/content${download ? "?download=true" : ""}`,
  transition: (
    caseId: string,
    targetState: WorkflowState,
    actor: string,
    reason?: string,
  ) =>
    request(`/cases/${caseId}/transition`,
      json("POST", {
        target_state: targetState,
        actor,
        ...(reason ? { reason } : {}),
      }),
    ),

  getCanadaApplicationBundle: (caseId: string) =>
    request<CanadaApplicationBundle>(`/cases/${caseId}/canada-application/bundle`),
  createCanadaApplication: (caseId: string, applicantPersonId: string) =>
    request<CanadaApplicationRecord>(`/cases/${caseId}/canada-application`, json("POST", { applicant_person_id: applicantPersonId })),
  updateCanadaApplication: (applicationId: string, payload: Record<string, unknown>) =>
    request<CanadaApplicationRecord>(`/canada-applications/${applicationId}`, json("PATCH", payload)),
  updateCanadaTripPlan: (applicationId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/canada-applications/${applicationId}/trip-plan`, json("PUT", payload)),
  createCanadaAddress: (applicationId: string, payload: Record<string, unknown>) =>
    request<{ id: string }>(`/canada-applications/${applicationId}/addresses`, json("POST", payload)),
  createCanadaTravelDocument: (applicationId: string, payload: Record<string, unknown>) =>
    request<{ id: string }>(`/canada-applications/${applicationId}/travel-documents`, json("POST", payload)),
  createCanadaActivity: (applicationId: string, payload: Record<string, unknown>) =>
    request<{ id: string }>(`/canada-applications/${applicationId}/activities`, json("POST", payload)),
  saveOfficialAnswer: (applicationId: string, questionCode: string, payload: Record<string, unknown>) =>
    request<{ id: string }>(`/canada-applications/${applicationId}/official-answers/${encodeURIComponent(questionCode)}`, json("PUT", payload)),
  previewCanadaImport: (caseId: string, sourceType: string, file: File, importedBy?: string) => {
    const form = new FormData();
    form.set("source_type", sourceType); form.set("file", file);
    if (importedBy) form.set("imported_by", importedBy);
    return request<CanadaImportRun>(`/cases/${caseId}/canada-imports/preview`, { method: "POST", body: form });
  },
  listCanadaImports: (caseId: string) => request<CanadaImportRun[]>(`/cases/${caseId}/canada-imports`),
  listCanadaImportChanges: (importId: string) => request<CanadaImportChange[]>(`/canada-imports/${importId}/changes`),
  applyCanadaImport: (importId: string, mode: "accepted" | "safe", reviewedBy?: string) =>
    request<CanadaImportRun>(`/canada-imports/${importId}/apply`, json("POST", { mode, reviewed_by: reviewedBy ?? null })),
  reviewCanadaImportChange: (changeId: string, action: "accept" | "reject", reviewedBy?: string) =>
    request<CanadaImportChange>(`/canada-import-changes/${changeId}/${action}`, json("POST", { reviewed_by: reviewedBy ?? null })),
  resolveCanadaImportChange: (changeId: string, decision: "keep_current" | "use_imported", reviewedBy?: string, hostType?: "person" | "organization") =>
    request<CanadaImportChange>(`/canada-import-changes/${changeId}/resolve`, json("POST", { decision, reviewed_by: reviewedBy ?? null, ...(hostType ? { host_type: hostType } : {}) })),
  confirmCanadaImportChange: (changeId: string, value: unknown, reviewedBy?: string, hostType?: "person" | "organization") =>
    request<CanadaImportChange>(`/canada-import-changes/${changeId}/confirm`, json("POST", { value, reviewed_by: reviewedBy ?? null, ...(hostType ? { host_type: hostType } : {}) })),
};

export async function loadCaseSummaries(): Promise<CaseSummary[]> {
  return (await api.bootstrap()).case_summary;
}

class CaseDetailLoadError extends Error {}

async function loadCaseDetailData(caseId: string): Promise<CaseDetailBundle> {
  const [caseRecord, people, facts, requirements, documents, documentTypes, documentMatches, conversations, tasks, workflow, nextAction, canadaApplication, preparation, preparationRuns] =
    await Promise.all([
      api.getCase(caseId),
      api.listPeople(caseId).catch(() => {
        throw new CaseDetailLoadError("People could not be loaded.");
      }),
      api.listFacts(caseId),
      api.listRequirements(caseId),
      api.listDocuments(caseId),
      api.listDocumentTypes(),
      api.listDocumentMatches(caseId),
      api.listConversations(caseId),
      api.listTasks(caseId),
      api.getWorkflow(caseId),
      api.getNextAction(caseId),
      api.getCanadaApplicationBundle(caseId).catch(error => {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }),
      api.getPreparation(caseId),
      api.listPreparationRuns(caseId),
    ]);
  const documentClassifications = (
    await Promise.all(documents.map(document => api.listDocumentClassifications(document.id)))
  ).flat();
  const [documentQualityChecks, requirementCompletenessEvaluations] = await Promise.all([
    Promise.all(documents.map(document => api.listQualityChecks(document.id))).then(items => items.flat()),
    Promise.all(requirements.map(requirement => api.listCompletenessEvaluations(requirement.id))).then(items => items.flat()),
  ]);
  const [conversationMessages, factExtractionRuns, factCandidates] = await Promise.all([
    Promise.all(conversations.map(item => api.listConversationMessages(item.id))).then(items => items.flat()),
    Promise.all(conversations.map(item => api.listFactExtractionRuns(item.id))).then(items => items.flat()),
    Promise.all(conversations.map(item => api.listFactCandidates(item.id))).then(items => items.flat()),
  ]);
  return {
    case: caseRecord,
    people,
    facts,
    requirements,
    documents,
    documentClassifications,
    documentQualityChecks,
    requirementCompletenessEvaluations,
    documentTypes,
    documentMatches,
    conversations,
    conversationMessages,
    factExtractionRuns,
    factCandidates,
    tasks,
    workflow,
    nextAction,
    canadaApplication,
    preparation,
    preparationRuns,
  };
}

export async function loadCaseDetail(caseId: string): Promise<CaseDetailBundle> {
  try {
    return await loadCaseDetailData(caseId);
  } catch (error) {
    if (error instanceof CaseDetailLoadError) throw error;
    throw new CaseDetailLoadError("Some case information could not be loaded.");
  }
}
