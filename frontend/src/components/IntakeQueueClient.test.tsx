import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { api, type IntakeSubmission } from "@/lib/api";
import { IntakeQueueClient } from "./IntakeQueueClient";


vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: {
    ...actual.api,
    listIntakeSubmissions: vi.fn(), intakeMetrics: vi.fn(), bootstrap: vi.fn(),
    uploadGoogleFormsIntake: vi.fn(), retryIntakeSubmission: vi.fn(),
  }};
});

const failed: IntakeSubmission = {
  id: "intake-1", source_type: "GOOGLE_FORMS_CSV", source_external_id: "google-1",
  source_filename: "submission.csv", source_hash: "a".repeat(64),
  received_at: "2026-10-07T10:00:00Z", mapping_version: "m9b-1",
  processing_status: "FAILED", case_id: null, import_run_id: null,
  processing_started_at: "2026-10-07T10:00:01Z", processing_completed_at: "2026-10-07T10:00:02Z",
  failure_code: "SOURCE_VALIDATION_FAILED", failure_message: "The source could not be parsed or validated.",
  issue_count: 1, duplicate_receive_count: 0, retry_count: 0,
  applicant_display_name: null, case_number: null, can_retry: true,
};
const caseSummary = { id: "case-1", case_number: "CA-2026-1", display_name: "Amina Diallo", visa_type: "canada_trv", purpose: "Visit", workflow_state: "INTAKE" as const, issue_count: 0, next_action: "Continue application", queue: "WAITING" as const, updated_at: "2026-10-07T10:00:00Z" };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listIntakeSubmissions).mockResolvedValue([failed]);
  vi.mocked(api.intakeMetrics).mockResolvedValue({ submissions_received: 1, successfully_processed: 0, duplicates_ignored: 0, new_cases_created: 0, existing_cases_matched: 0, review_required: 0, failed: 1 });
  vi.mocked(api.bootstrap).mockResolvedValue({ user: { id: "worker", email: "worker@example.invalid", display_name: "Worker", role: "CASE_WORKER", is_active: true, mfa_enabled: true }, case_summary: [caseSummary], timings_ms: { database: 1, total: 2 } });
  vi.mocked(api.uploadGoogleFormsIntake).mockResolvedValue({ ...failed, id: "intake-2", processing_status: "PROCESSED", failure_code: null, failure_message: null, issue_count: 0, case_id: "case-1", case_number: "CA-2026-1", applicant_display_name: "Amina Diallo" });
  vi.mocked(api.retryIntakeSubmission).mockResolvedValue({ ...failed, processing_status: "PROCESSED", failure_code: null, failure_message: null, issue_count: 0, case_id: "case-1", case_number: "CA-2026-1", applicant_display_name: "Amina Diallo" });
});

it("shows the exception queue and operational counters without raw internals", async () => {
  render(<IntakeQueueClient />);
  expect(await screen.findByRole("heading", { name: "Applicant not identified yet" })).toBeInTheDocument();
  expect(screen.getByText("The source could not be parsed or validated.")).toBeInTheDocument();
  expect(screen.getByText("Duplicates ignored")).toBeInTheDocument();
  expect(screen.queryByText("a".repeat(64))).not.toBeInTheDocument();
});

it("uploads a CSV through the automated intake endpoint", async () => {
  const user = userEvent.setup();
  render(<IntakeQueueClient />);
  await screen.findByText("submission.csv", { exact: false });
  const file = new File(["synthetic"], "new.csv", { type: "text/csv" });
  await user.upload(screen.getByLabelText("CSV source"), file);
  await user.type(screen.getByLabelText("Google submission ID (optional)"), "google-2");
  await user.selectOptions(screen.getByLabelText("Existing application (optional)"), "case-1");
  await user.click(screen.getByRole("button", { name: "Receive and process" }));
  await waitFor(() => expect(api.uploadGoogleFormsIntake).toHaveBeenCalledWith(file, "google-2", "case-1"));
});

it("retries an exception with an employee-selected application", async () => {
  const user = userEvent.setup();
  render(<IntakeQueueClient />);
  await screen.findByText("submission.csv", { exact: false });
  await user.selectOptions(screen.getByLabelText("Application for submission.csv"), "case-1");
  await user.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(api.retryIntakeSubmission).toHaveBeenCalledWith("intake-1", "case-1"));
});

it("offers deterministic reprocessing for a processed submission with a stale mapping", async () => {
  const user = userEvent.setup();
  vi.mocked(api.listIntakeSubmissions).mockResolvedValue([{
    ...failed, processing_status: "PROCESSED", failure_code: null,
    failure_message: null, issue_count: 0, case_id: "case-1",
    case_number: "CA-2026-1", can_retry: true,
  }]);
  render(<IntakeQueueClient />);
  await user.click(await screen.findByRole("button", { name: "Reprocess" }));
  await waitFor(() => expect(api.retryIntakeSubmission).toHaveBeenCalledWith("intake-1", undefined));
});
