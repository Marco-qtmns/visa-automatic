import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { AuthShell } from "./AuthShell";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ usePathname: () => "/cases", useRouter: () => ({ replace }) }));
vi.mock("@/lib/api/client", () => ({
  ApiError: class ApiError extends Error { constructor(message: string, public status?: number) { super(message); } },
  api: {
    me: vi.fn().mockResolvedValue({ user: { id: "1", email: "admin@example.com", display_name: "Admin User", role: "ADMIN", is_active: true, mfa_enabled: true } }),
    logout: vi.fn().mockResolvedValue(undefined),
  },
}));

it("gates application rendering on the backend identity and supports logout", async () => {
  render(<AuthShell><div>Protected cases</div></AuthShell>);
  await waitFor(() => expect(screen.getByText("Protected cases")).toBeInTheDocument());
  expect(screen.getByText("Admin User · ADMIN")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Log out" }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
});
