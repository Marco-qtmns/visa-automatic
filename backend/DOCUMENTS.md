# Manual document upload and matching

Milestone 5 connects received file bytes to the existing Document and
Requirement models. Upload and matching remain manual. Milestone 6 adds a
separate, explicitly triggered classification suggestion flow documented in
[CLASSIFICATION.md](CLASSIFICATION.md). Milestone 7 adds the separate quality
and completeness flow documented in [QUALITY.md](QUALITY.md).

## Storage architecture

Application services depend on the `StorageProvider` contract rather than the
local filesystem. The development implementation is `LocalStorageProvider`.
It supports saving, opening, existence checks, and deletion by opaque key. This
boundary allows a future S3-compatible implementation without changing the
Document or matching domain services.

Configure local development storage with:

```text
DOCUMENT_STORAGE_ROOT=backend/storage
MAX_UPLOAD_SIZE_MB=20
```

The default root is `backend/storage`, which is excluded by `.gitignore`.
Production must configure private storage outside the public source checkout.
No uploaded files belong in Git, fixtures, `Unterlagen/`, or `Sicherungen/`.

Physical filenames are random UUID keys. The client-supplied filename is
sanitized and retained only as display metadata; it never controls a storage
path. Normal API responses omit the internal storage reference, and file bytes
are retrieved through `GET /documents/{document_id}/content`.

## Upload policy

`POST /cases/{case_id}/documents/upload` accepts multipart form data containing
one file plus optional `document_type` and `person_id` fields. Unassigned files
are valid and remain visible to the existing `ASSIGN_DOCUMENT` Next Action.

Supported initial formats are PDF, JPEG, and PNG. Both the declared MIME type
and conservative file signature must agree. Size is limited by
`MAX_UPLOAD_SIZE_MB`. Upload itself performs no OCR, content parsing, or AI
transmission. Production malware
scanning, encrypted object storage, retention policies, and authenticated
access enforcement remain deployment hardening work.

Employee-assigned document types are validated against the Milestone 4 catalog.
Metadata edits are limited to document type and person; immutable upload
metadata and storage references are not employee-editable.

## Manual Requirement–Document matches

`RequirementDocumentMatch` is a persisted many-to-many association with:

- `requirement_id` and `document_id` foreign keys;
- a unique pair constraint;
- optional employee actor and note;
- creation timestamp.

A requirement can reference several files, and a file can support several
requirements when structurally compatible. A new match requires:

1. the same case;
2. an active requirement;
3. an assigned document type matching the requirement exactly;
4. an assigned person matching `owner_person_id`, or, when unresolved, a person
   holding the requirement's `owner_role`.

Compatibility is based only on employee-assigned metadata. The service never
inspects document contents. Existing matches are retained when a requirement is
deactivated. An incompatible type/person edit is rejected until the employee
explicitly removes or reassigns affected matches; matches are never silently
deleted.

Candidate, create, list, and remove operations are exposed through:

```text
GET    /documents/{document_id}/matching-requirements
GET    /documents/{document_id}/requirements
GET    /requirements/{requirement_id}/documents
POST   /requirements/{requirement_id}/documents/{document_id}
DELETE /requirements/{requirement_id}/documents/{document_id}
```

## Fulfilment and workflow boundary

A manual match means only that an employee associated received evidence with a
requirement. It does not mean the file is complete, readable, valid, accepted,
or quality-approved. Milestone 7 reevaluates completeness after a match change,
but only a compatible matched file with `passed` or `manual_accepted` quality
can contribute to automatic fulfilment.

Document upload, matching, quality, and completeness never mutate workflow
state. WorkflowService and Next Action remain authoritative.

Milestone 8 conversation imports are intentionally separate from this document
pipeline. WhatsApp messages and fact candidates never create `Document`
records, storage objects, matches, quality evaluations, or fulfilment evidence.
