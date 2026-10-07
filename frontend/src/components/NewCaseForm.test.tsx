import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { NewCaseForm } from "./NewCaseForm";
import { api } from "@/lib/api";
import { detail } from "@/test/fixtures";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", async () => { const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api"); return { ...actual, api: { ...actual.api, createCase: vi.fn() } }; });

it("creates an unnamed application and opens its workspace", async () => { vi.mocked(api.createCase).mockResolvedValue(detail.case); const user = userEvent.setup(); render(<NewCaseForm />); await user.click(screen.getByRole("button", { name: "Create empty application" })); expect(api.createCase).toHaveBeenCalledWith({}); expect(push).toHaveBeenCalledWith("/cases/case-1"); });
it("routes a selected source into the new workspace", async () => { vi.mocked(api.createCase).mockResolvedValue(detail.case); const user = userEvent.setup(); render(<NewCaseForm />); await user.click(screen.getByRole("button", { name: "Upload Google Forms / CSV" })); expect(push).toHaveBeenCalledWith("/cases/case-1#canada-import"); });
it("shows creation errors", async () => { vi.mocked(api.createCase).mockRejectedValue(new Error("Case could not be created")); const user = userEvent.setup(); render(<NewCaseForm />); await user.click(screen.getByRole("button", { name: "Create empty application" })); expect(await screen.findByRole("alert")).toHaveTextContent("Case could not be created"); });
