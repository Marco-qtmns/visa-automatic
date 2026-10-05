import type { CaseDetailBundle } from "@/lib/api";

export const detail: CaseDetailBundle = {
  case: { id: "case-1", case_number: "CA-300", visa_type: "TRV", purpose: "Visit", workflow_state: "INTAKE", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  people: [{ id: "person-1", case_id: "case-1", first_name: "Amina", last_name: "Diallo", roles: ["applicant"], created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
  facts: [{ id: "fact-1", case_id: "case-1", person_id: "person-1", key: "passport.number", value_json: "P123", source_type: "manual", source_reference: "employee", confidence: 0.8, status: "conflict", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
  conversations: [],
  conversationMessages: [],
  factExtractionRuns: [],
  factCandidates: [],
  requirements: [{ id: "req-1", case_id: "case-1", document_type: "passport_bio_page", owner_role: "applicant", owner_person_id: "person-1", requirement_level: "required", rule_id: null, reason: "Identity", is_blocking: true, active: true, fulfillment_status: "pending", fulfillment_source: null, fulfillment_updated_at: null, completeness_policy_json: { mode: "single_document" }, waiver_reason: null, waived_by: null, waived_at: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
  documents: [{ id: "doc-1", case_id: "case-1", person_id: "person-1", document_type: "passport_bio_page", original_filename: "passport.pdf", mime_type: "application/pdf", source_type: "manual_upload", classification_status: "unclassified", quality_status: "not_checked", metadata_json: {}, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }],
  documentClassifications: [],
  documentQualityChecks: [],
  requirementCompletenessEvaluations: [],
  documentTypes: [{ id: "passport_bio_page", label: "Passport bio page" }, { id: "bank_statements", label: "Bank statements" }],
  documentMatches: [{ id: "match-1", requirement_id: "req-1", document_id: "doc-1", created_by: "manual-ui", note: null, created_at: "2026-01-01T00:00:00Z" }],
  tasks: [{ id: "task-1", case_id: "case-1", type: "review", title: "Review passport", description: "Check dates", status: "open", priority: "high", blocking: true, related_requirement_id: "req-1", related_document_id: "doc-1", created_at: "2026-01-01T00:00:00Z", completed_at: null }],
  workflow: { case_id: "case-1", current_state: "INTAKE", allowed_targets: ["DOCUMENTS"], history: [] },
  nextAction: { type: "resolve_fact_conflict", title: "Resolve passport conflict", case_id: "case-1", fact_id: "fact-1", fact_key: "passport.number", requirement_id: null, task_id: null, document_id: null, fact_candidate_id: null, target_state: null },
  canadaApplication: null,
  preparation: {
    package_status: "blocked", latest_run: null, current_run: null, payload_hash: null, integrity_error: null,
    readiness: {
      ready: false, policy_version: "m9c-1", schema_version: "m9d-1", payload_hash: null,
      blocking_count: 1, warning_count: 0, warnings: [],
      issues: [{ code: "missing_value", path: "applicant.passport.number", section: "passport", label: "Passport number", severity: "blocking", blocking: true, message: "Passport number is missing.", action: "Enter the passport number." }],
      sections: [{ section: "passport", label: "Passport", blocking_count: 1, warning_count: 0, issues: [{ code: "missing_value", path: "applicant.passport.number", section: "passport", label: "Passport number", severity: "blocking", blocking: true, message: "Passport number is missing.", action: "Enter the passport number." }] }],
    },
  },
  preparationRuns: [],
};
