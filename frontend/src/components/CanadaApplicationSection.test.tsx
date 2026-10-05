import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api, type CanadaApplicationBundle } from "@/lib/api";
import { detail } from "@/test/fixtures";
import { CanadaApplicationSection } from "./CanadaApplicationSection";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, createCanadaApplication: vi.fn(), updateCanadaTripPlan: vi.fn(), saveOfficialAnswer: vi.fn(), listCanadaImports: vi.fn(), listCanadaImportChanges: vi.fn() } };
});

const bundle: CanadaApplicationBundle = {
  application: { id: "app-1", case_id: "case-1", applicant_person_id: "person-1", legal_guardian_person_id: null, official_application_date: null, application_date_review_state: "unreviewed", native_language_code: null, preferred_language_code: null, service_language_code: null, mailing_same_as_residential: null, created_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:00Z" },
  roles: [], biographies: [], citizenships: [], identifiers: [], contacts: [], addresses: [], applicant_residences: [], travel_documents: [],
  trip_plan: null, funding_sources: [], hosts: [], organizations: [], family_relationships: [], education: [], activities: [], residence_history: [], travel_history: [], official_answers: [], official_explanations: [], representative_authorization: null, provenance: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listCanadaImports).mockResolvedValue([]);
  vi.mocked(api.listCanadaImportChanges).mockResolvedValue([]);
});

it("requires explicit applicant selection when initializing", async () => {
  vi.mocked(api.createCanadaApplication).mockResolvedValue(bundle.application);
  const user = userEvent.setup();
  render(<CanadaApplicationSection caseId="case-1" people={detail.people} value={null} onChanged={vi.fn().mockResolvedValue(undefined)} />);
  await user.selectOptions(screen.getByLabelText("Applicant"), "person-1");
  await user.click(screen.getByRole("button", { name: "Initialize Canada application" }));
  expect(api.createCanadaApplication).toHaveBeenCalledWith("case-1", "person-1");
});

it("keeps intake and IMM5257 purpose separate and defaults answers to unknown", async () => {
  vi.mocked(api.updateCanadaTripPlan).mockResolvedValue({});
  vi.mocked(api.saveOfficialAnswer).mockResolvedValue({ id: "answer-1" });
  const user = userEvent.setup();
  render(<CanadaApplicationSection caseId="case-1" people={detail.people} value={bundle} onChanged={vi.fn().mockResolvedValue(undefined)} />);
  await user.type(screen.getByLabelText("Intake purpose text"), "Visit friends");
  await user.click(screen.getByRole("button", { name: "Save trip plan" }));
  expect(api.updateCanadaTripPlan).toHaveBeenCalledWith("app-1", expect.objectContaining({ intake_purpose_text: "Visit friends", imm5257_purpose_code: null }));
  await user.type(screen.getByLabelText("Question code"), "background.criminality");
  await user.click(screen.getByRole("button", { name: "Save official answer" }));
  expect(api.saveOfficialAnswer).toHaveBeenCalledWith("app-1", "background.criminality", expect.objectContaining({ answer: "unknown" }));
});
