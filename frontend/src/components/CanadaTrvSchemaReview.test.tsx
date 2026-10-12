import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api, type CanadaTrvReviewApplication, type CanadaTrvReviewDetail } from "@/lib/api";
import { CanadaTrvSchemaReview } from "./CanadaTrvSchemaReview";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api,
    listCanadaTrvReviews: vi.fn(), getCanadaTrvReview: vi.fn(), importCanadaTrvReview: vi.fn(),
    updateCanadaTrvReviewField: vi.fn(), confirmCanadaTrvReviewField: vi.fn(),
    confirmCanadaTrvReviewSection: vi.fn(), confirmCanadaTrvReview: vi.fn(),
  }};
});

const application: CanadaTrvReviewApplication = {
  id: "review-1", import_id: "batch-1", case_id: "case-1", import_row_number: 2,
  status: "in_progress", confirmed_by: null, confirmed_at: null,
  created_at: "2026-10-11T10:00:00Z", updated_at: "2026-10-11T10:00:00Z",
};
const detail: CanadaTrvReviewDetail = {
  application, schema_id: "canada_trv_google_form_2026", schema_version: "3.0.0",
  variant_id: "username_absent", source_filename: "synthetic.csv",
  sections: [{ id: "personal", title: "Dados Pessoais", ui_group_title_pt: "Dados Pessoais", order: 1, reviewable: true, evidence: "screenshot_verified" }],
  fields: [{
    id: "field-1", field_id: "GF_003", section_id: "personal", target_path: "applicant.name.surname",
    source_csv_column_1based: 2, source_header: "Sobrenome completo, conforme o passaporte",
    raw_value: "Silva", normalized_value_json: "Silva", edited_value_json: null,
    applicability: "applicable", review_status: "pending", evidence: "screenshot_verified",
    requirement_mode: "review_when_applicable", reviewer_id: null, reviewed_at: null,
    label_pt: "Sobrenome completo, conforme o passaporte", normalized_type: "text",
    ui: { group_id: "personal", group_title_pt: "Dados Pessoais", label: "Sobrenome", section_ordinal: 1, record_index_0based: null, span_columns: 1, show_in_review: true },
    revisions: [],
  }],
  normalized_data: { applicant: { name: { surname: "Silva" } } }, validation_issues: [], section_reviews: {},
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listCanadaTrvReviews).mockResolvedValue([application]);
  vi.mocked(api.getCanadaTrvReview).mockResolvedValue(detail);
  vi.mocked(api.updateCanadaTrvReviewField).mockResolvedValue({ ...detail.fields[0], edited_value_json: "Souza", review_status: "corrected_pending_confirmation" });
});

it("renders a schema field with its answer directly below the accessible label", async () => {
  render(<CanadaTrvSchemaReview caseId="case-1" onChanged={vi.fn().mockResolvedValue(undefined)} />);
  const input = await screen.findByLabelText("Sobrenome completo, conforme o passaporte");
  expect(input).toHaveValue("Silva");
  expect(screen.getByText("0 / 1")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Dados Pessoais 0\/1/ })).toBeInTheDocument();
});

it("saves a correction separately and preserves source provenance", async () => {
  const user = userEvent.setup();
  render(<CanadaTrvSchemaReview caseId="case-1" onChanged={vi.fn().mockResolvedValue(undefined)} />);
  const input = await screen.findByLabelText("Sobrenome completo, conforme o passaporte");
  await user.clear(input); await user.type(input, "Souza");
  await user.click(screen.getByRole("button", { name: "Save correction" }));
  expect(api.updateCanadaTrvReviewField).toHaveBeenCalledWith("field-1", "Souza");
  await user.click(screen.getByText("Source and history"));
  expect(screen.getByText(/Original: Silva/)).toBeInTheDocument();
});
