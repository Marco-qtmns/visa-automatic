import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CaseListClient } from "./CaseListClient";
import { loadCaseSummaries } from "@/lib/api";
import { detail } from "@/test/fixtures";

vi.mock("@/lib/api", async () => ({ ...(await vi.importActual<typeof import("@/lib/api")>("@/lib/api")), loadCaseSummaries: vi.fn() }));
const mocked = vi.mocked(loadCaseSummaries);

describe("CaseListClient", () => {
  beforeEach(() => mocked.mockReset());
  it("shows backend-derived case summary", async () => { mocked.mockResolvedValue([{ case: detail.case, applicantName: "Amina Diallo", nextAction: detail.nextAction, requirementProgress: "0/1 requirements · 1 documents" }]); render(<CaseListClient />); expect(await screen.findByText("CA-300")).toBeInTheDocument(); expect(screen.getByText("Amina Diallo")).toBeInTheDocument(); expect(screen.getByText("TRV")).toBeInTheDocument(); expect(screen.getByText("INTAKE")).toBeInTheDocument(); expect(screen.getByText("Resolve passport conflict")).toBeInTheDocument(); });
  it("shows empty state", async () => { mocked.mockResolvedValue([]); render(<CaseListClient />); expect(await screen.findByText("No cases yet")).toBeInTheDocument(); });
  it("shows and retries errors", async () => { mocked.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([]); render(<CaseListClient />); expect(await screen.findByRole("alert")).toHaveTextContent("offline"); screen.getByRole("button", { name: "Retry" }).click(); await waitFor(() => expect(screen.getByText("No cases yet")).toBeInTheDocument()); });
});
