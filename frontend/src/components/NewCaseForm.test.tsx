import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { NewCaseForm } from "./NewCaseForm";
import { api } from "@/lib/api";
import { detail } from "@/test/fixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", async () => { const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api"); return { ...actual, api: { ...actual.api, createCase: vi.fn() } }; });

it("creates a case and opens its detail", async () => { vi.mocked(api.createCase).mockResolvedValue(detail.case); const user = userEvent.setup(); render(<NewCaseForm />); await user.type(screen.getByLabelText("Case number"), "CA-300"); await user.type(screen.getByLabelText("Visa type"), "TRV"); await user.type(screen.getByLabelText("Purpose"), "Visit"); await user.click(screen.getByRole("button", { name: "Create case" })); expect(api.createCase).toHaveBeenCalledWith({ case_number: "CA-300", visa_type: "TRV", purpose: "Visit" }); expect(push).toHaveBeenCalledWith("/cases/case-1"); });
it("shows creation errors", async () => { vi.mocked(api.createCase).mockRejectedValue(new Error("Duplicate case number")); const user = userEvent.setup(); render(<NewCaseForm />); await user.type(screen.getByLabelText("Case number"), "CA-300"); await user.type(screen.getByLabelText("Visa type"), "TRV"); await user.type(screen.getByLabelText("Purpose"), "Visit"); await user.click(screen.getByRole("button", { name: "Create case" })); expect(await screen.findByRole("alert")).toHaveTextContent("Duplicate case number"); });
