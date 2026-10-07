import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CaseListClient } from "./CaseListClient";
import { loadCaseSummaries } from "@/lib/api";
import { detail } from "@/test/fixtures";

vi.mock("@/lib/api", async () => ({ ...(await vi.importActual<typeof import("@/lib/api")>("@/lib/api")), loadCaseSummaries: vi.fn() }));
const mocked = vi.mocked(loadCaseSummaries);

describe("CaseListClient", () => {
  beforeEach(() => mocked.mockReset());
  it("shows the backend work-queue summary without inventing readiness", async () => { mocked.mockResolvedValue([{ id: detail.case.id, case_number: "CA-300", display_name: "Amina Diallo", visa_type: "TRV", purpose: "Visit", workflow_state: "INTAKE", issue_count: 2, next_action: "Resolve passport conflict", queue: "ACTION_REQUIRED", updated_at: detail.case.updated_at }]); render(<CaseListClient />); expect(await screen.findByText("CA-300")).toBeInTheDocument(); expect(screen.getByText("Amina Diallo")).toBeInTheDocument(); expect(screen.getByText("INTAKE")).toBeInTheDocument(); expect(screen.getByText("Resolve passport conflict")).toBeInTheDocument(); expect(screen.getByRole("columnheader", { name: "Open issues" })).toBeInTheDocument(); });
  it("shows empty state", async () => { mocked.mockResolvedValue([]); render(<CaseListClient />); expect(await screen.findByText("No applications yet")).toBeInTheDocument(); });
  it("shows and retries errors", async () => { mocked.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([]); render(<CaseListClient />); expect(await screen.findByRole("alert")).toHaveTextContent("offline"); screen.getByRole("button", { name: "Retry" }).click(); await waitFor(() => expect(screen.getByText("No applications yet")).toBeInTheDocument()); });
});
