# Canada TRV schema review

The Canada TRV review flow imports the exact Google Forms CSV layouts described
by schema `canada_trv_google_form_2026` version `3.0.0`. It is a review and
normalization layer. It does not fill an IRCC PDF, generate a supporting letter,
or silently apply values to the canonical Canada application.

## Runtime schema and CSV matching

The runtime definition is
`app/config/canada_trv/canada_trv_review_schema_v3.json`. The adjacent YAML is a
review copy. Both files are protected by checked SHA-256 values at application
startup, so a change requires an explicit schema-version review.

The importer accepts only the two registered ordered-header variants:

- 235 columns, including `Nome de usuário` at column 2;
- 234 columns, with only that optional metadata column absent.

Headers, order, whitespace, duplicate-header occurrence, and the canonical
header digest must match exactly. An unknown layout is rejected with the first
mismatching position and a request for a new schema version; no fuzzy matching
is used. UTF-8, UTF-8 with BOM, CSV quoting, quoted line breaks, and multiple
response rows are supported. Each non-empty response row creates an independent
review application and case. The source object is retained in private intake
storage, and the ordered raw headers, ordered raw row, source column, source
header, and original value are stored for provenance.

## Normalized and reviewed data

Fields are written to the schema's existing `target_path` model. Safe dates,
yes/no values, email syntax, and file references are normalized while raw values
remain unchanged. The four activity groups and five child groups become arrays;
untouched groups are omitted, while partial groups remain visible and are marked
for review. Unstructured repeatable answers keep `raw_text`, an empty
`candidates` list, and `requires_manual_review` instead of invented records.

Applicability uses a declarative three-valued evaluator (`true`, `false`, or
`unknown`). Empty false branches become `not_applicable`; unknown dependencies
and conditional conflicts remain visible as review issues. The review states,
normalized payload, validation issues, section state, reviewer, timestamps, and
the complete correction history are persisted in migration
`0017_import_review_state`.

An edit retains the original raw value, records an immutable revision, and
invalidates prior confirmation. Field confirmation is explicit. Section and
application confirmation are blocked until every applicable review field is
confirmed and no blocking validation issue remains. Re-import creates a new
review run and never overwrites an earlier confirmed run.

## API and employee UI

Apply the migration before starting the service:

```bash
alembic -c backend/alembic.ini upgrade head
```

The authenticated API provides:

- `GET /canada-trv-review-schema`
- `POST /canada-trv-reviews/import`
- `GET /cases/{case_id}/canada-trv-reviews`
- `GET /canada-trv-reviews/{application_id}`
- `PATCH /canada-trv-review-fields/{field_id}`
- `POST /canada-trv-review-fields/{field_id}/confirm`
- `POST /canada-trv-reviews/{application_id}/confirm-section`
- `POST /canada-trv-reviews/{application_id}/confirm`

The case page exposes the schema-driven review in the existing Canada section.
It includes source metadata, import-run selection, progress, section navigation,
issue/status filters, an optional not-applicable view, accessible form labels,
correction history, and field/section/application confirmation. The field grid
uses three columns at 1100 px and above, two from 700–1099 px, and one below
700 px; long answers span the grid without horizontal overflow.

## Verification and current boundary

Automated coverage uses synthetic data only and checks both CSV variants,
duplicate-header resolution, multi-row case creation, conditional logic,
repeated arrays, file-reference markers, security-field isolation, persistence,
reload, corrections, API behavior, accessibility, and responsive CSS classes.

The referenced real CSV exports, ordered PDF, and target UI screenshot were not
included in the supplied implementation archive. Consequently, real-file
acceptance, comparison against the ordered PDF, and pixel-level comparison with
the reference screenshot remain pending. Do not commit those source files if
they contain customer data.
