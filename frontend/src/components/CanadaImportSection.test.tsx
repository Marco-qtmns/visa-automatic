import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api, type CanadaImportChange, type CanadaImportRun } from "@/lib/api";
import { CanadaImportSection } from "./CanadaImportSection";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api,
    listCanadaImports: vi.fn(), listCanadaImportChanges: vi.fn(),
    previewCanadaImport: vi.fn(), applyCanadaImport: vi.fn(),
    reviewCanadaImportChange: vi.fn(), resolveCanadaImportChange: vi.fn(),
    confirmCanadaImportChange: vi.fn(),
  }};
});

const run: CanadaImportRun = {
  id: "import-1", case_id: "case-1", source_type: "canada_case_json",
  source_identifier: "synthetic.canada-case.json", source_hash: "abc", mapping_version: "m9b-1",
  status: "previewed", imported_by: "tester", counts_json: { new: 1, same: 2, conflict: 1, ambiguous: 0, applied: 0 },
  warnings_json: ["Address needs component review"], error_summary: null,
  created_at: "2026-10-02T00:00:00Z", completed_at: null,
};
const base: CanadaImportChange = {
  id: "change-new", import_run_id: run.id, domain_section: "Applicant", employee_label: "Date of birth",
  target_label: "Applicant — Date of birth", classification: "SAFE_NEW",
  target_entity_type: "person_biography", target_entity_id: null, target_field: "date_of_birth",
  operation: "create_or_set", source_path: "identity.date_of_birth", source_record_key: "scalar",
  source_classification: "applicant_direct", source_reference: "case#identity.date_of_birth",
  raw_value_json: "17/04/1992",
  proposed_value_json: "1992-04-17", current_value_json: null, status: "new", conflict_type: null,
  review_policy: "safe_direct_batch", conflict_policy: "never_overwrite_reviewed",
  reviewed_by: null, reviewed_at: null, created_at: "2026-10-02T00:00:00Z",
};
const conflict: CanadaImportChange = { ...base, id: "change-conflict", domain_section: "Passport", employee_label: "Passport number", target_label: "Applicant — Passport number", classification: "CONFLICT", source_path: "passport.number", target_field: "number", current_value_json: "AB123456", proposed_value_json: "XY987654", status: "conflict", conflict_type: "confirmed_canonical_value" };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listCanadaImports).mockResolvedValue([run]);
  vi.mocked(api.listCanadaImportChanges).mockResolvedValue([base, conflict]);
  vi.mocked(api.applyCanadaImport).mockResolvedValue(run);
  vi.mocked(api.resolveCanadaImportChange).mockResolvedValue({ ...conflict, status: "accepted" });
  vi.mocked(api.confirmCanadaImportChange).mockResolvedValue({ ...conflict, status: "accepted" });
});

it("renders preview counts, warnings, and domain sections", async () => {
  render(<CanadaImportSection caseId="case-1" onChanged={vi.fn().mockResolvedValue(undefined)} />);
  expect(await screen.findByText("Applicant — Date of birth")).toBeInTheDocument();
  expect(screen.getByText("Address needs component review")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Needs attention" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Passport \(0\/1\)/ })).toBeInTheDocument();
});

it("requires a corrected invalid value before confirmation", async () => {
  const user = userEvent.setup();
  render(<CanadaImportSection caseId="case-1" onChanged={vi.fn().mockResolvedValue(undefined)} />);
  await screen.findByText("Applicant — Date of birth");
  await user.click(screen.getByRole("button", { name: /Passport \(0\/1\)/ }));
  const input = await screen.findByLabelText("Application value");
  expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
  await user.clear(input); await user.type(input, "ZZ123456");
  await user.click(screen.getByRole("button", { name: "Save correction and confirm" }));
  expect(api.confirmCanadaImportChange).toHaveBeenCalledWith("change-conflict", "ZZ123456", "manual-ui", undefined);
});

it("keeps section navigation and attention filtering in the unified form", async () => {
  const user = userEvent.setup();
  render(<CanadaImportSection caseId="case-1" onChanged={vi.fn().mockResolvedValue(undefined)} />);
  expect(await screen.findByText("Applicant — Date of birth")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Needs attention" }));
  expect(screen.getByText("Applicant — Date of birth")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Passport \(0\/1\)/ }));
  expect(await screen.findByText("Applicant — Passport number")).toBeInTheDocument();
});

it("keeps confirmed values editable and saves a correction", async () => {
  const user = userEvent.setup();
  const confirmed = { ...base, status: "applied", canonical_review_state: "confirmed" as const };
  vi.mocked(api.listCanadaImportChanges).mockResolvedValue([confirmed]);
  render(<CanadaImportSection caseId="case-1" onChanged={vi.fn().mockResolvedValue(undefined)} />);
  const input = await screen.findByLabelText("Application value");
  expect(input).toBeEnabled();
  await user.clear(input); await user.type(input, "1993-04-17");
  await user.click(screen.getByRole("button", { name: "Save correction and confirm" }));
  expect(api.confirmCanadaImportChange).toHaveBeenCalledWith("change-new", "1993-04-17", "manual-ui", undefined);
});
