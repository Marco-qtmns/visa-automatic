import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import LoginPage from "./page";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
afterEach(() => vi.unstubAllGlobals());

it("renders password login then mandatory MFA enrollment", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    status: "mfa_enrollment_required", challenge_token: "challenge-token-value-long-enough",
    expires_in_seconds: 300, enrollment_secret: "JBSWY3DPEHPK3PXP",
    provisioning_uri: "otpauth://totp/Visa%20Automatic:test",
  }), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  render(<LoginPage />);
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "ValidPassword123" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(screen.getByRole("heading", { name: "Set up MFA" })).toBeInTheDocument());
  expect(screen.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
  expect(screen.getByLabelText("Authentication code")).toBeInTheDocument();
});

it("renders the returning-user MFA challenge without revealing a setup secret", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    status: "mfa_required", challenge_token: "challenge-token-value-long-enough",
    expires_in_seconds: 300, enrollment_secret: null, provisioning_uri: null,
  }), { status: 200, headers: { "Content-Type": "application/json" } })));
  render(<LoginPage />);
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "ValidPassword123" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(screen.getByRole("heading", { name: "Verify MFA" })).toBeInTheDocument());
  expect(screen.queryByText("Setup key")).not.toBeInTheDocument();
});
