import { afterEach, expect, it, vi } from "vitest";
import { api } from "./client";


afterEach(() => vi.unstubAllGlobals());


it("sends document uploads as browser-managed multipart form data", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({
      id: "doc-1",
      case_id: "case-1",
      person_id: "person-1",
      document_type: "passport_bio_page",
      original_filename: "synthetic.pdf",
      mime_type: "application/pdf",
      source_type: "manual_upload",
      classification_status: "unclassified",
      quality_status: "not_checked",
      metadata_json: {},
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    }), { status: 201, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const file = new File(["%PDF-1.4 synthetic"], "synthetic.pdf", {
    type: "application/pdf",
  });

  await api.uploadDocument("case-1", file, "passport_bio_page", "person-1");

  const [, init] = fetchMock.mock.calls[0];
  expect(init.method).toBe("POST");
  expect(init.body).toBeInstanceOf(FormData);
  expect((init.body as FormData).get("file")).toBe(file);
  expect((init.body as FormData).get("document_type")).toBe("passport_bio_page");
  expect(init.headers).not.toHaveProperty("Content-Type");
});

it("includes credentials and the CSRF cookie on mutations without storing auth tokens", async () => {
  document.cookie = "va_csrf=csrf-test-value; path=/";
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), {
    status: 201, headers: { "Content-Type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetchMock);
  await api.createCase({ case_number: "SYN-1", visa_type: "TRV", purpose: "test" });
  const [, init] = fetchMock.mock.calls[0];
  expect(init.credentials).toBe("include");
  expect(init.headers["X-CSRF-Token"]).toBe("csrf-test-value");
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});
