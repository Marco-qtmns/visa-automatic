import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { AdminUsersClient } from "./AdminUsersClient";

vi.mock("./AuthShell", () => ({ useCurrentUser: () => ({ id: "admin", role: "ADMIN" }) }));
vi.mock("@/lib/api", () => ({ api: {
  listUsers: vi.fn(), listSecurityAudit: vi.fn(), createUser: vi.fn(), updateUser: vi.fn(),
  revokeUserSessions: vi.fn(), resetUserMfa: vi.fn(),
} }));

const user = { id: "worker", email: "worker@example.com", display_name: "Worker", role: "CASE_WORKER" as const, is_active: true, mfa_enabled: true, created_at: "2026-10-06T10:00:00Z", last_successful_login_at: null, active_session_count: 2 };

beforeEach(() => {
  vi.mocked(api.listUsers).mockResolvedValue([user]);
  vi.mocked(api.listSecurityAudit).mockResolvedValue([]);
  vi.mocked(api.updateUser).mockResolvedValue({ ...user, role: "REVIEWER" });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

it("renders admin users and confirms role changes", async () => {
  render(<AdminUsersClient />);
  expect(await screen.findByText("worker@example.com")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Role for worker@example.com"), { target: { value: "REVIEWER" } });
  await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith("worker", { role: "REVIEWER" }));
  expect(window.confirm).toHaveBeenCalled();
});
