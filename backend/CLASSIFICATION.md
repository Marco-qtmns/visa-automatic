# Automatic document classification

Milestone 6 adds employee-triggered suggestions for an uploaded document's
catalog type and existing case person. Suggestions are never authoritative on
their own and never create requirement matches, fulfil requirements, advance
workflow, or make quality decisions.

## Architecture and lifecycle

The server-side pipeline is:

```text
StorageProvider -> DocumentContentExtractor -> DocumentClassifier
                                          -> DocumentClassification audit row
                                          -> employee review
                                          -> safe document metadata update
```

`DefaultDocumentContentExtractor` reads bytes only through `StorageProvider`.
For PDFs it uses PyMuPDF to extract at most 12,000 characters of embedded text;
it does not OCR a text-bearing PDF. JPEG/PNG and image-only content is supplied
in memory to the configured provider boundary so a future vision provider can
handle it. Extracted text and document bytes are not persisted or logged.

`DocumentClassifier` is a vendor-neutral protocol. Domain models and services
do not import a vendor SDK. The default provider is disabled. The optional
`local_text` provider is a deterministic development implementation that maps
strong embedded-text markers to the version-controlled catalog. It cannot
inspect image pixels and returns no type rather than guessing. Tests inject a
deterministic fake and never call a paid or live service.

Configure explicitly:

```text
AI_PROVIDER=              # disabled when empty
AI_PROVIDER=local_text    # optional local development classifier
AI_MODEL=                 # reserved for isolated future providers
AI_API_KEY=               # placeholder only; never commit a value
```

Upload never invokes classification. An employee calls `POST
/documents/{document_id}/classify`. If no provider is configured, a controlled
failed attempt is recorded and manual type/person assignment remains available.

## Structured suggestion and audit history

Each run creates a new `DocumentClassification`; prior attempts are retained.
It stores catalog-limited suggested type, locally resolved person, normalized
confidence, concise evidence, provider/version, SHA-256 document version hash,
safe structured prediction fields, timestamps, failure status, and the later
employee decision. Full document text and binary content are not stored in the
classification record.

Classifier-created types outside `app/config/document_types.json` are
normalized to no suggestion with explanatory evidence. Confidence is bounded
to 0–1 and never authorizes an automatic change. Evidence is limited to ten
short observable features; chain-of-thought and large excerpts are excluded.
The current catalog permits `passport_bio_page`, `identity_document`,
`civil_status_document`, `digital_photo`, and `bank_statements` only.

Owner identity is a separate local step. A provider may return a short
extracted owner name, which is normalized and compared with full names of
existing people in the same case. Only one exact match yields a person ID.
No match or multiple matches yields `null` with evidence; no person is created.

## Employee review

The API exposes history and explicit review operations:

```text
GET  /documents/{document_id}/classifications
POST /documents/{document_id}/classifications/{id}/accept
POST /documents/{document_id}/classifications/{id}/correct
POST /documents/{document_id}/classifications/{id}/reject
```

Accept applies only non-null suggested fields, preserving manually assigned
metadata where the classifier made no suggestion. Correct requires a catalog
type and existing case person and preserves both prediction and correction.
Reject records reviewer/time and changes no authoritative metadata.

Accept and Correct call the Milestone 5 `DocumentMatchingService` update path.
An incompatible existing match therefore blocks the change until the employee
resolves it; matches are never deleted. After review, requirement matching is
still a separate explicit employee action.

The employee UI labels results as automatic suggestions, shows confidence and
concise evidence, offers Accept/Correct/Reject, and keeps a small attempt
history. Failure shows retry and manual assignment paths.

## Privacy and quality boundary

Passport, identity, bank, and immigration contents are sensitive. No external
provider is enabled implicitly. A future external adapter must be explicitly
configured, keep credentials in environment/secret management, document its
data-processing and retention behavior, avoid content logging, and receive
only the minimum necessary content after the employee initiates classification.

Classification answers only “what kind of document is this, and whose is it?”
It does not assess readability, completeness, validity, expiry, cropping, or
acceptability. Those quality decisions remain outside Milestone 6.
