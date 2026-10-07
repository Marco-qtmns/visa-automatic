import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  vi.clearAllMocks();
  vi.mocked(api.listUsers).mockResolvedValue([user]);
  vi.mocked(api.listSecurityAudit).mockResolvedValue([]);
  vi.mocked(api.createUser).mockResolvedValue(user);
  vi.mocked(api.updateUser).mockResolvedValue({ ...user, role: "REVIEWER" });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

it("resets the create-user form after an awaited successful request", async () => {
  const browser = userEvent.setup();
  render(<AdminUsersClient />);
  await screen.findByText("worker@example.com");
  await browser.type(screen.getByLabelText("Email"), "new@example.com");
  await browser.type(screen.getByLabelText("Display name"), "New Employee");
  await browser.type(screen.getByLabelText("Temporary password"), "ValidPassword123");
  await browser.selectOptions(screen.getByLabelText("Role"), "REVIEWER");
  await browser.click(screen.getByRole("button", { name: "Create user" }));

  await waitFor(() => expect(api.createUser).toHaveBeenCalledWith({
    email: "new@example.com",
    display_name: "New Employee",
    password: "ValidPassword123",
    role: "REVIEWER",
  }));
  expect(screen.getByLabelText("Email")).toHaveValue("");
  expect(screen.getByLabelText("Display name")).toHaveValue("");
  expect(screen.getByLabelText("Temporary password")).toHaveValue("");
  expect(screen.getByLabelText("Role")).toHaveValue("CASE_WORKER");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("renders admin users and confirms role changes", async () => {
  render(<AdminUsersClient />);
  expect(await screen.findByText("worker@example.com")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Role for worker@example.com"), { target: { value: "REVIEWER" } });
  await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith("worker", { role: "REVIEWER" }));
  expect(window.confirm).toHaveBeenCalled();
});
