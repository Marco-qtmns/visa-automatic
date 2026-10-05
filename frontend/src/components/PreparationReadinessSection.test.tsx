import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { PreparationSection } from "./PreparationReadinessSection";
import { detail } from "@/test/fixtures";
import type { PreparationRun, PreparationStatus } from "@/lib/api";

const artifact = {
  id: "artifact-1", preparation_run_id: "run-1", case_id: "case-1",
  artifact_type: "imm5257" as const, display_filename: "IMM5257-DRAFT.pdf",
  mime_type: "application/pdf", generator: "legacy_canada_xfa", generator_version: "test",
  template_identifier: "templates/IMM5257.pdf", template_hash: "a".repeat(64),
  file_hash: "b".repeat(64), created_at: "2026-01-01T00:00:00Z",
};
const run: PreparationRun = {
  id: "run-1", case_id: "case-1", status: "succeeded", initiated_by: "employee",
  payload_schema_version: "m9d-1", preparation_policy_version: "m9c-1",
  payload_hash: "c".repeat(64), adapter_version: "m9d-1", generator_version: "test",
  started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:01:00Z",
  error_code: null, error_summary: null, created_at: "2026-01-01T00:00:00Z",
  artifacts: [artifact],
};
const ready: PreparationStatus = {
  ...detail.preparation,
  package_status: "not_generated", payload_hash: run.payload_hash,
  readiness: { ...detail.preparation.readiness, ready: true, payload_hash: run.payload_hash, issues: [], sections: [], blocking_count: 0 },
};

it("renders structured blockers and links to their canonical section", () => {
  render(<PreparationSection caseId="case-1" value={detail.preparation} history={[]} onChanged={async () => {}} />);
  expect(screen.getByRole("heading", { name: "Preparation" })).toBeInTheDocument();
  expect(screen.getByText("Passport number")).toBeInTheDocument();
  expect(screen.getByText("Enter the passport number.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open relevant canonical section" })).toHaveAttribute("href", "#canada-application");
  expect(screen.queryByRole("button", { name: /generate/i })).not.toBeInTheDocument();
});

it("shows explicit generation only when canonical data is ready", () => {
  render(<PreparationSection caseId="case-1" value={ready} history={[]} onChanged={async () => {}} />);
  expect(screen.getByRole("button", { name: "Generate application package" })).toBeInTheDocument();
});

it("renders current artifacts with controlled open and download links", () => {
  render(<PreparationSection caseId="case-1" value={{ ...ready, package_status: "current", latest_run: run, current_run: run }} history={[run]} onChanged={async () => {}} />);
  expect(screen.getByText("Application package is current.")).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "Open" })[0]).toHaveAttribute("href", expect.stringContaining("/preparation-artifacts/artifact-1/content"));
  expect(screen.getAllByRole("link", { name: "Download" })[0]).toHaveAttribute("href", expect.stringContaining("download=true"));
  expect(screen.getByText(/Run 1 · succeeded · Current/)).toBeInTheDocument();
});

it("renders stale and failed states with safe actions", () => {
  const { rerender } = render(<PreparationSection caseId="case-1" value={{ ...ready, package_status: "stale", latest_run: run }} history={[run]} onChanged={async () => {}} />);
  expect(screen.getByText("Application data changed since this package was generated.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument();
  const failed = { ...run, id: "run-2", status: "failed" as const, error_code: "generator_failed", error_summary: "Application package generation failed.", artifacts: [] };
  rerender(<PreparationSection caseId="case-1" value={{ ...ready, package_status: "failed", latest_run: failed }} history={[failed, run]} onChanged={async () => {}} />);
  expect(screen.getAllByText("Application package generation failed.")).toHaveLength(2);
  expect(screen.getByText(/Run 2 · failed/)).toBeInTheDocument();
  expect(screen.getByText(/Run 1 · succeeded · Outdated/)).toBeInTheDocument();
});

it("does not expose a letter generator or letter artifact", () => {
  render(<PreparationSection caseId="case-1" value={{ ...ready, package_status: "current", current_run: run }} history={[run]} onChanged={async () => {}} />);
  expect(screen.queryByText(/letter generator|submission letter|supporting letter/i)).not.toBeInTheDocument();
});
