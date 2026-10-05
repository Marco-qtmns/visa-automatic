# Visa Automatic employee frontend

Milestone 3 provides the first internal employee UI as a Next.js/React/TypeScript
application. It calls the central FastAPI backend and does not contain a local
database or duplicate workflow rules.

## Local development

```bash
cp frontend/.env.example frontend/.env.local
cd frontend
npm install
npm run dev
```

Run the backend separately on the URL configured as
`NEXT_PUBLIC_API_BASE_URL`. `NEXT_PUBLIC_WORKFLOW_ACTOR` is the temporary actor
name stored with manual transitions. The backend accepts browser origins from
its comma-separated `CORS_ORIGINS` environment variable.

The deployment build uses the relative `/api` base behind the D1 Caddy proxy,
so a browser on another computer does not attempt to reach its own localhost.
See [`../DEPLOYMENT_D1.md`](../DEPLOYMENT_D1.md).

Routes:

- `/cases` lists cases with applicant, progress, state, and backend Next Action.
- `/cases/new` creates a case.
- `/cases/[caseId]` edits case data, people, facts, requirements, document
  metadata, tasks, and executes backend-authorized workflow transitions.

Milestone 4 marks generated requirements as Automatic, shows their stable rule
ID, distinguishes them from Manual requirements, and provides an explicit
reevaluation button. Rule decisions and lifecycle changes remain authoritative
in the backend.

Milestone 5 adds manual PDF/JPEG/PNG upload, catalog-based type and person
assignment, controlled Open/Download links, deterministic candidate listing,
and explicit Match/Unmatch controls. Requirements show their matched filenames
with a clear warning that matching is not quality approval.

Milestone 6 adds an explicit Classify document action, clearly labelled
suggestions, confidence/evidence, history, and employee Accept/Correct/Reject
controls. Correction choices come only from the catalog and existing case
people. Failed or disabled classification leaves manual assignment available.
There is no upload-triggered AI, quality checking, desktop packaging, or
installer work in this milestone.

Milestone 7 adds explicit Run quality check/Rerun controls, structured findings
and issues, compact history, and clearly labelled manual accept/reject forms
that require a reason. Requirements separately show matched count, accepted
count, completeness, missing coverage, and fulfilment provenance. All decisions
remain backend-authoritative; the frontend contains no quality rules.

Milestone 8 adds a Communications section for pasted WhatsApp text and bounded
`.txt` exports. Employees explicitly request extraction, inspect catalog-limited
suggestions with confidence, evidence, and source-message context, and then
Accept, Correct, or Reject each candidate with a reason. Raw transcripts are
not rendered by the case view, extraction is disabled by default, and the
frontend neither writes facts directly nor changes workflow state.

Milestone 9A adds a **Canada application** section to case detail. Employees
explicitly initialize the aggregate with an applicant and can maintain
application/trip review fields, owned addresses, travel documents, applicant
activities, and official answers while seeing every structured collection.
It does not trigger form or letter generation.

Milestone 9B adds a **Canada intake import** subsection. Employees upload a
supported legacy source, inspect counts, warnings, and domain-grouped changes,
resolve conflicts individually, and can accept only safe direct-source values
in a batch. All policies and Next Action priority remain backend-authoritative.

Milestone 9C adds a **Preparation readiness** section with grouped canonical
blockers/warnings, employee actions, section links, policy/schema versions, and
the payload hash once ready. Readiness and Next Action remain backend-owned;
the UI contains no duplicated policy and intentionally has no Generate button.

Milestone 9D extends this into **Preparation**. Ready cases can be generated
explicitly; current artifacts have controlled Open/Download actions; stale,
failed, generating, integrity, and submitted-discrepancy states are distinct;
and compact historical run manifests remain inspectable. The backend owns all
generation and status decisions. There is no letter UI or external submission.

## Verify

```bash
cd frontend
npm run test:run
npm run build
```
