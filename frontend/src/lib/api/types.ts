export const WORKFLOW_STATES = [
  "INTAKE",
  "DOCUMENTS",
  "PREPARE",
  "REVIEW",
  "READY",
  "SUBMITTED",
] as const;

export type WorkflowState = (typeof WORKFLOW_STATES)[number];
export type PersonRole =
  | "applicant"
  | "sponsor"
  | "host"
  | "representative"
  | "spouse"
  | "child"
  | "other";
export type FactStatus = "confirmed" | "proposed" | "conflict" | "rejected";
export type FactSource = "google_form" | "whatsapp" | "document" | "manual" | "derived";
export type RequirementLevel = "required" | "conditional" | "supporting" | "optional";
export type FulfillmentStatus = "pending" | "fulfilled" | "waived";
export type FulfillmentSource = "manual" | "automatic_document_evidence" | "waived";
export type DocumentQualityState = "not_checked" | "checking" | "passed" | "failed" | "manual_review" | "manual_accepted" | "manual_rejected" | "error";
export type TaskStatus = "open" | "in_progress" | "completed" | "cancelled";

export interface CaseRecord {
  id: string;
  case_number: string;
  visa_type: string;
  purpose: string;
  workflow_state: WorkflowState;
  created_at: string;
  updated_at: string;
}

export type CaseCreate = Partial<Pick<CaseRecord, "case_number" | "visa_type" | "purpose">>;
export type CaseUpdate = Partial<CaseCreate>;

export interface Person {
  id: string;
  case_id: string;
  first_name: string;
  last_name: string;
  roles: PersonRole[];
  created_at: string;
  updated_at: string;
}

export type PersonInput = Pick<Person, "first_name" | "last_name" | "roles">;

export interface Fact {
  id: string;
  case_id: string;
  person_id: string | null;
  key: string;
  value_json: unknown;
  source_type: FactSource;
  source_reference: string;
  confidence: number | null;
  status: FactStatus;
  created_at: string;
  updated_at: string;
}

export interface ConversationImport {
  id: string;
  case_id: string;
  source_type: "whatsapp_paste" | "whatsapp_export";
  original_filename: string | null;
  imported_by: string | null;
  content_hash: string;
  parse_status: "parsed" | "parsed_with_warnings" | "failed";
  parse_warnings_json: { line?: number; message: string }[];
  message_count: number;
  imported_at: string;
}

export interface ConversationMessage {
  id: string;
  conversation_import_id: string;
  case_id: string;
  sequence_number: number;
  sender: string | null;
  message_timestamp: string | null;
  text: string;
  source_reference: string;
  created_at: string;
}

export interface FactExtractionRun {
  id: string;
  conversation_import_id: string;
  status: "running" | "completed" | "failed";
  provider: string;
  model_version: string | null;
  candidate_count: number;
  rejected_output_count: number;
  failure_reason: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface FactExtractionCandidate {
  id: string;
  case_id: string;
  conversation_import_id: string | null;
  extraction_run_id: string | null;
  key: string;
  value_json: unknown;
  confidence: number;
  evidence: string;
  source_message_ids_json: string[];
  provider: string;
  model_version: string | null;
  status: "proposed" | "conflict" | "accepted" | "corrected" | "rejected";
  conflicting_fact_id: string | null;
  authoritative_fact_id: string | null;
  corrected_value_json: unknown | null;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_reason: string | null;
}

export type FactInput = Omit<Fact, "id" | "case_id" | "created_at" | "updated_at">;

export interface Requirement {
  id: string;
  case_id: string;
  document_type: string;
  owner_role: PersonRole;
  owner_person_id: string | null;
  requirement_level: RequirementLevel;
  rule_id: string | null;
  reason: string;
  is_blocking: boolean;
  active: boolean;
  fulfillment_status: FulfillmentStatus;
  fulfillment_source: FulfillmentSource | null;
  fulfillment_updated_at: string | null;
  completeness_policy_json: { mode: "single_document" } | { mode: "month_coverage"; required_months: string[] };
  waiver_reason: string | null;
  waived_by: string | null;
  waived_at: string | null;
  created_at: string;
  updated_at: string;
}

export type RequirementCreate = Pick<
  Requirement,
  | "document_type"
  | "owner_role"
  | "owner_person_id"
  | "requirement_level"
  | "rule_id"
  | "reason"
  | "is_blocking"
  | "active"
>;

export type RequirementUpdate = Partial<
  RequirementCreate &
    Pick<Requirement, "fulfillment_status" | "waiver_reason" | "waived_by">
>;

export interface RequirementEvaluationResult {
  created: Requirement[];
  reactivated: Requirement[];
  deactivated: Requirement[];
  unchanged: Requirement[];
}

export interface DocumentRecord {
  id: string;
  case_id: string;
  person_id: string | null;
  document_type: string | null;
  original_filename: string;
  mime_type: string;
  source_type: string;
  classification_status: "unclassified" | "classification_pending" | "suggestion_available" | "confirmed" | "classification_failed";
  quality_status: DocumentQualityState;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export type DocumentUpdate = Pick<DocumentRecord, "person_id" | "document_type">;

export interface DocumentTypeDefinition {
  id: string;
  label: string;
}

export interface ClassificationEvidence {
  type: string;
  value: string;
}

export interface DocumentClassification {
  id: string;
  document_id: string;
  suggested_document_type: string | null;
  suggested_person_id: string | null;
  extracted_owner_name: string | null;
  confidence: number | null;
  evidence_json: ClassificationEvidence[];
  provider: string;
  model_version: string | null;
  document_hash: string | null;
  raw_result_json: Record<string, unknown> | null;
  status: "pending" | "suggested" | "accepted" | "corrected" | "rejected" | "failed";
  failure_reason: string | null;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  corrected_document_type: string | null;
  corrected_person_id: string | null;
}

export interface QualityCheckResult {
  check_id: string;
  status: "pass" | "fail" | "unknown" | "manual_review" | "not_applicable";
  evidence: string | null;
  issue: string | null;
  evaluator: string;
  confidence: number | null;
}

export interface DocumentQualityCheck {
  id: string;
  document_id: string;
  status: "checking" | "passed" | "failed" | "manual_review" | "error";
  checks_json: QualityCheckResult[];
  issues_json: { check_id: string; message: string }[];
  extracted_metadata_json: Record<string, unknown>;
  provider: string;
  evaluator_version: string | null;
  document_hash: string | null;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_decision: "accepted" | "rejected" | null;
  review_reason: string | null;
}

export interface RequirementCompletenessEvaluation {
  id: string;
  requirement_id: string;
  status: "complete" | "incomplete" | "not_evaluable";
  matched_document_ids_json: string[];
  accepted_document_ids_json: string[];
  matched_count: number;
  accepted_count: number;
  coverage_json: Record<string, unknown>;
  missing_json: string[];
  explanation: string;
  trigger: string;
  created_at: string;
}

export interface RequirementDocumentMatch {
  id: string;
  requirement_id: string;
  document_id: string;
  created_by: string | null;
  note: string | null;
  created_at: string;
}

export interface TaskRecord {
  id: string;
  case_id: string;
  type: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: string;
  blocking: boolean;
  related_requirement_id: string | null;
  related_document_id: string | null;
  created_at: string;
  completed_at: string | null;
}

export type TaskInput = Omit<TaskRecord, "id" | "case_id" | "created_at">;

export interface WorkflowTransition {
  id: string;
  case_id: string;
  from_state: WorkflowState;
  to_state: WorkflowState;
  actor: string | null;
  reason: string | null;
  created_at: string;
}

export interface Workflow {
  case_id: string;
  current_state: WorkflowState;
  allowed_targets: WorkflowState[];
  history: WorkflowTransition[];
}

export interface NextAction {
  type: string;
  title: string;
  case_id: string;
  fact_id: string | null;
  fact_key: string | null;
  requirement_id: string | null;
  task_id: string | null;
  document_id: string | null;
  fact_candidate_id: string | null;
  import_run_id?: string | null;
  preparation_issue_code?: string | null;
  preparation_path?: string | null;
  target_state: WorkflowState | null;
}

export interface PreparationIssue {
  code: "missing_value" | "review_required" | "unresolved_import_conflict" |
    "unresolved_fact_conflict" | "missing_selection" | "invalid_cardinality" |
    "inconsistent_data" | "blocking_requirement" | "unsupported_value" |
    "missing_collection_record" | "incomplete_collection" | "ambiguous_reference";
  path: string;
  section: string;
  label: string;
  severity: "blocking" | "warning";
  blocking: boolean;
  message: string;
  action: string;
}

export interface PreparationSection {
  section: string;
  label: string;
  blocking_count: number;
  warning_count: number;
  issues: PreparationIssue[];
}

export interface PreparationReadiness {
  ready: boolean;
  policy_version: string;
  schema_version: string;
  payload_hash: string | null;
  issues: PreparationIssue[];
  warnings: PreparationIssue[];
  sections: PreparationSection[];
  blocking_count: number;
  warning_count: number;
}

export interface PreparationArtifact {
  id: string;
  preparation_run_id: string;
  case_id: string;
  artifact_type: "imm5257" | "imm5707" | "imm5476" | "imm5257_continuation";
  display_filename: string;
  mime_type: string;
  generator: string;
  generator_version: string;
  template_identifier: string;
  template_hash: string;
  file_hash: string;
  created_at: string;
}

export interface PreparationRun {
  id: string;
  case_id: string;
  status: "running" | "succeeded" | "failed";
  initiated_by: string;
  payload_schema_version: string;
  preparation_policy_version: string;
  payload_hash: string;
  adapter_version: string;
  generator_version: string;
  started_at: string;
  completed_at: string | null;
  error_code: string | null;
  error_summary: string | null;
  created_at: string;
  artifacts: PreparationArtifact[];
}

export interface PreparationStatus {
  readiness: PreparationReadiness;
  latest_run: PreparationRun | null;
  current_run: PreparationRun | null;
  payload_hash: string | null;
  package_status: "blocked" | "not_generated" | "generating" | "current" | "stale" | "failed" | "integrity_error" | "submitted_discrepancy";
  integrity_error: string | null;
}

export interface CaseSummary {
  id: string;
  case_number: string;
  display_name: string;
  visa_type: string;
  purpose: string;
  workflow_state: WorkflowState;
  issue_count: number;
  next_action: string;
  queue: "ACTION_REQUIRED" | "WAITING" | "REVIEW" | "READY";
  updated_at: string;
}

export interface IntakeSubmission {
  id: string;
  source_type: string;
  source_external_id: string | null;
  source_filename: string | null;
  source_hash: string;
  received_at: string;
  mapping_version: string;
  processing_status: "RECEIVED" | "PROCESSING" | "PROCESSED" | "NEEDS_REVIEW" | "FAILED";
  case_id: string | null;
  import_run_id: string | null;
  processing_started_at: string | null;
  processing_completed_at: string | null;
  failure_code: string | null;
  failure_message: string | null;
  issue_count: number;
  duplicate_receive_count: number;
  retry_count: number;
  applicant_display_name: string | null;
  case_number: string | null;
}

export interface IntakeMetrics {
  submissions_received: number;
  successfully_processed: number;
  duplicates_ignored: number;
  new_cases_created: number;
  existing_cases_matched: number;
  review_required: number;
  failed: number;
}

export interface CanadaApplicationRecord {
  id: string;
  case_id: string;
  applicant_person_id: string | null;
  legal_guardian_person_id: string | null;
  official_application_date: string | null;
  application_date_review_state: string;
  native_language_code: string | null;
  preferred_language_code: string | null;
  service_language_code: string | null;
  mailing_same_as_residential: boolean | null;
  created_at: string;
  updated_at: string;
}

export interface CanadaTripPlan {
  id: string;
  intake_purpose_text: string | null;
  imm5257_purpose_code: string | null;
  purpose_review_state: string;
  arrival_date: string | null;
  departure_date: string | null;
}

export interface CanadaApplicationBundle {
  application: CanadaApplicationRecord;
  roles: Record<string, unknown>[];
  biographies: Record<string, unknown>[];
  citizenships: Record<string, unknown>[];
  identifiers: Record<string, unknown>[];
  contacts: Record<string, unknown>[];
  addresses: Record<string, unknown>[];
  applicant_residences: Record<string, unknown>[];
  travel_documents: Record<string, unknown>[];
  trip_plan: CanadaTripPlan | null;
  funding_sources: Record<string, unknown>[];
  hosts: Record<string, unknown>[];
  organizations: Record<string, unknown>[];
  family_relationships: Record<string, unknown>[];
  education: Record<string, unknown>[];
  activities: Record<string, unknown>[];
  residence_history: Record<string, unknown>[];
  travel_history: Record<string, unknown>[];
  official_answers: Record<string, unknown>[];
  official_explanations: Record<string, unknown>[];
  representative_authorization: Record<string, unknown> | null;
  provenance: Record<string, unknown>[];
}

export interface CanadaImportRun {
  id: string;
  case_id: string;
  source_type: string;
  source_identifier: string;
  source_hash: string;
  mapping_version: string;
  status: string;
  imported_by: string | null;
  counts_json: Record<string, number>;
  warnings_json: string[];
  error_summary: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface CanadaImportChange {
  id: string;
  import_run_id: string;
  domain_section: string;
  employee_label: string;
  target_label: string;
  classification: string;
  target_entity_type: string;
  target_entity_id: string | null;
  target_field: string;
  operation: string;
  source_path: string;
  source_record_key: string;
  source_classification: string;
  source_reference: string;
  raw_value_json: unknown;
  proposed_value_json: unknown;
  current_value_json: unknown;
  status: string;
  conflict_type: string | null;
  review_policy: string;
  conflict_policy: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface CaseDetailBundle {
  case: CaseRecord;
  people: Person[];
  facts: Fact[];
  requirements: Requirement[];
  documents: DocumentRecord[];
  documentClassifications: DocumentClassification[];
  documentQualityChecks: DocumentQualityCheck[];
  requirementCompletenessEvaluations: RequirementCompletenessEvaluation[];
  documentTypes: DocumentTypeDefinition[];
  documentMatches: RequirementDocumentMatch[];
  conversations: ConversationImport[];
  conversationMessages: ConversationMessage[];
  factExtractionRuns: FactExtractionRun[];
  factCandidates: FactExtractionCandidate[];
  tasks: TaskRecord[];
  workflow: Workflow;
  nextAction: NextAction;
  canadaApplication: CanadaApplicationBundle | null;
  preparation: PreparationStatus;
  preparationRuns: PreparationRun[];
}
