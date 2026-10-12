import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { detail } from "@/test/fixtures";
import { CanonicalIntakeSection } from "./CanonicalIntakeSection";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, applyCanonicalDecisions: vi.fn() } };
});

it("saves manual intake as one canonical decision batch with explicit unknowns", async () => {
  vi.mocked(api.applyCanonicalDecisions).mockResolvedValue([]);
  const changed = vi.fn().mockResolvedValue(undefined);
  const user = userEvent.setup();
  render(<CanonicalIntakeSection caseId="case-1" status={detail.dynamicStatus} revisions={[]} people={detail.people} onChanged={changed} />);
  await user.selectOptions(screen.getByLabelText("Financial sponsor"), "no");
  await user.selectOptions(screen.getByLabelText("Host in Canada"), "unknown");
  await user.selectOptions(screen.getByLabelText("Trip payer"), "applicant");
  await user.type(screen.getByLabelText("Commercial instructions"), "Prioritize travel dates");
  await user.click(screen.getByRole("button", { name: "Save canonical information" }));
  expect(api.applyCanonicalDecisions).toHaveBeenCalledWith("case-1", expect.arrayContaining([
    { field_path: "sponsor.exists", value_json: false, expected_revision: 0 },
    { field_path: "host.exists", value_json: null, expected_revision: 0 },
    { field_path: "trip.payer", value_json: "applicant", expected_revision: 0 },
    { field_path: "commercial.instructions", value_json: "Prioritize travel dates", expected_revision: 0 },
  ]), "manual-ui");
  expect(changed).toHaveBeenCalled();
});
