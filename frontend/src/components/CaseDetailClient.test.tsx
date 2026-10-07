import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api, loadCaseDetail } from "@/lib/api";
import { CaseDetailClient, visibleWorkflowTargets } from "./CaseDetailClient";
import { detail } from "@/test/fixtures";

vi.mock("@/lib/api", async () => { const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api"); return { ...actual, loadCaseDetail: vi.fn(), api: { ...actual.api, transition: vi.fn(), updateTask: vi.fn() } }; });

beforeEach(() => { vi.mocked(loadCaseDetail).mockResolvedValue(detail); vi.mocked(api.transition).mockResolvedValue({}); });
it("renders every case area, conflicts, and backend next action", async () => { render(<CaseDetailClient caseId="case-1" />); expect(await screen.findByText("Resolve passport conflict")).toBeInTheDocument(); for (const heading of ["Overview", "People", "Facts", "Requirements", "Documents", "Tasks", "Workflow"]) expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument(); expect(screen.getByText("conflict")).toBeInTheDocument(); expect(screen.getAllByText("passport.pdf").length).toBeGreaterThan(0); });
it("uses the transition endpoint instead of updating workflow state", async () => { const user = userEvent.setup(); render(<CaseDetailClient caseId="case-1" />); await screen.findByText("Allowed transitions"); await user.type(screen.getByLabelText("Reason for DOCUMENTS"), "Intake reviewed"); await user.click(screen.getByRole("button", { name: "Move to DOCUMENTS" })); expect(api.transition).toHaveBeenCalledWith("case-1", "DOCUMENTS", "manual-ui", "Intake reviewed"); });
it("surfaces transition gate errors", async () => { vi.mocked(api.transition).mockRejectedValue(new Error("Resolve conflicts first")); const user = userEvent.setup(); render(<CaseDetailClient caseId="case-1" />); await user.click(await screen.findByRole("button", { name: "Move to DOCUMENTS" })); expect(await screen.findByRole("alert")).toHaveTextContent("Resolve conflicts first"); });
it("displays backend transition history", async () => { vi.mocked(loadCaseDetail).mockResolvedValue({ ...detail, workflow: { ...detail.workflow, history: [{ id: "transition-1", case_id: "case-1", from_state: "INTAKE", to_state: "DOCUMENTS", actor: "employee", reason: "Intake checked", created_at: "2026-10-01T12:00:00Z" }] } }); render(<CaseDetailClient caseId="case-1" />); expect(await screen.findByText("Intake checked")).toBeInTheDocument(); expect(screen.getAllByText("INTAKE → DOCUMENTS")).toHaveLength(2); expect(screen.getByText("employee")).toBeInTheDocument(); });

it("shows only the concrete CASE_WORKER review return transition", () => {
  expect(visibleWorkflowTargets("REVIEW", ["DOCUMENTS", "PREPARE", "READY"], "CASE_WORKER"))
    .toEqual(["PREPARE"]);
  expect(visibleWorkflowTargets("READY", ["PREPARE", "REVIEW", "SUBMITTED"], "CASE_WORKER"))
    .toEqual([]);
  expect(visibleWorkflowTargets("REVIEW", ["DOCUMENTS", "PREPARE", "READY"], "REVIEWER"))
    .toEqual(["DOCUMENTS", "PREPARE", "READY"]);
});
