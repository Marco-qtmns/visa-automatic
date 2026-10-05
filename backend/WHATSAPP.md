# WhatsApp conversation ingestion and fact review

Milestone 8 accepts pasted conversation text and uploaded `.txt` exports. It
does not connect to WhatsApp, read desktop application files, automate WhatsApp
Web, send messages, create documents, or invoke form/letter generation.

## Persistence and privacy

`ConversationImport` stores one private raw-text copy, SHA-256 identity,
source/filename, parser status, warnings and counts. `ConversationMessage`
stores ordered messages with sender and timestamp where recognized. API import
responses never return raw conversation text, and application code does not log
conversation or evidence contents. Exact duplicate content within one case is
rejected. `.txt` uploads are bounded by `MAX_CONVERSATION_IMPORT_MB`, accept
UTF-8/UTF-8-BOM or BOM-marked UTF-16, and reject binary/non-text input.

Raw imports belong in the private central database, never Git. The model keeps
candidate evidence and authoritative FACT source references independent enough
for a future retention policy to delete raw imports/messages while deciding
which audit evidence must remain. No retention/deletion endpoint is implemented
in this milestone.

## Parser

`WhatsAppConversationParser` is separate from semantic extraction. It supports
common bracketed iOS and dash-separated Android exports, two/four-digit years,
day-first or month-first slash dates, ISO dates, 12/24-hour times, system lines,
and multiline messages. Ambiguous numeric dates try day-first before
month-first. Unsupported timestamp-like lines are preserved as messages with
warnings rather than discarded. The parser does not process attachments,
media, deleted-message metadata, quoted-message structure, or every locale-
specific Unicode format.

## Controlled fact extraction

The strict versioned catalog at `app/config/facts/extraction_catalog.json`
allows only:

- `sponsor.exists`: boolean;
- `host.exists`: boolean;
- `trip.payer`: `applicant`, `sponsor`, or `other`.

Relationship labels, person identities, dates, employment, marital status and
other plausible values are intentionally excluded until their backend taxonomy
and review semantics are approved. Extraction never creates PERSON records.

`ConversationFactExtractionService` invokes a vendor-independent
`FactExtractor`, validates key/value/confidence/source-message output, rejects
unknown or malformed provider output, and persists extraction-run history plus
review candidates. Evidence is limited to a short excerpt and message IDs; no
reasoning trace is stored.

`FACT_EXTRACTION_PROVIDER=disabled` is the safe default. `local_rules` is a
small development-only extractor for explicit sponsor, host and payer phrases;
it is not a general production semantic model. No external provider is included
or called. A future opt-in external adapter must minimize context and document
governance and where conversation text is transmitted.

## Review, conflict and provenance

Candidates remain `proposed` or `conflict` until an employee accepts, corrects
or rejects them with actor and reason. A same-value candidate can attach to the
existing confirmed singleton FACT without creating a duplicate. When an
employee chooses a different WhatsApp value, prior confirmed singleton rows are
retained and moved to `rejected`; a new confirmed FACT records
`source_type=whatsapp` and references the conversation, candidate and source
messages. Corrections retain both predicted and corrected values.

Accepted/corrected facts trigger the existing deterministic RequirementEngine.
Extraction and review never change workflow state. Centralized Next Action
surfaces unresolved WhatsApp candidates after existing FACT conflicts and
before missing structural facts. Provider failure is recorded safely and leaves
manual FACT entry usable.
