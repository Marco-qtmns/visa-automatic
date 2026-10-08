# Canonical Canada application model (Milestone 9A)

Milestone 9A introduces the central, typed data model used to maintain a Canada
visitor-visa application. It does not generate forms or letters and does not
read Google Forms, CSV, `.canada-case.json`, or other legacy data.

## Aggregate and authority rules

`CanadaApplication` is one-to-one with a case and is the aggregate root. A
person must be explicitly selected as applicant; list order and legacy person
roles are never used as an implicit selection.

- `TripPlan.intake_purpose_text` and `TripPlan.imm5257_purpose_code` are the
  only purpose fields. They are independent and no silent mapping is applied.
  The pre-existing `Case.purpose` remains for Milestone 1-8 compatibility and
  is not an authoritative Canada-form purpose.
- `CasePersonRole` contains operational roles only: applicant, representative,
  sponsor, host, and other.
- `FamilyRelationship` is authoritative for spouse, former spouse, parent, and
  child. The same person may also have an operational role, such as father and
  sponsor.
- Current applicant occupation comes from a current `ActivityRecord`.
  `PersonBiography.occupation_text` is used only for non-applicants without a
  modeled activity history; it is not an applicant fallback.
- Contextual addresses are separate owned rows. Residential and mailing rows
  are owned by the application; host and family addresses are owned by their
  respective stable domain record. Editing one does not mutate another.
- General contact points belong only to a person. Representative contact and
  address data are stored in immutable `RepresentativeProfileRevision` rows.
- `RepresentativeAuthorization` references one immutable revision, so later
  revisions cannot rewrite case history.

## Review and provenance

Review states are `unreviewed`, `confirmed`, `corrected`, `needs_review`, and
`rejected`. Official yes/no answers also support `unknown` and
`not_applicable`; unknown is never treated as no.

`FieldProvenanceReview` has a constrained entity catalog and references stable
entity IDs and real typed field names. A new provenance entry supersedes the
previous active metadata entry for that field but does not change the typed
value. All writes pass through `CanadaApplicationService`.

## Collections and constraints

Family, education, activity, residence-history, travel-history, passport,
funding, and host records have stable UUID identities and explicit sort order.
Reordering changes only the order. The database and service layer enforce
primary passport and host uniqueness, host person/organization XOR, one current
spouse, date ordering, constrained enum values, and at most one applicant role.
The service enforces the stronger requirement that a usable application has
exactly one explicitly selected applicant.

Apply migration `0007_canada_application_model`. The employee UI exposes the
aggregate in the Canada application section and the API bundle is available at
`GET /cases/{case_id}/canada-application/bundle`.

## Explicitly deferred

M9A does not include a FormFillerAdapter, LetterGeneratorAdapter, generation
payload, PreparationRun, PDF generation, legacy generator calls, automatic
legacy/Google import, or PREPARE-to-REVIEW workflow changes. Application
narratives are deferred to the future letter-generation milestone.

## Generator audit coverage

Every one of the 138 audited current-generator input paths now has a canonical
destination category: existing Case/Person fields, a typed M9A entity, a keyed
official answer/explanation, an immutable representative revision, or a
deterministic derivation such as duration from trip dates. The four prior
ambiguities are resolved structurally by separate intake/official purpose,
host party XOR, stable child UUIDs, and explicit child order.

This is structural coverage, not a migration or generation claim. Existing
legacy cases are not copied automatically, and the future adapter still must
perform a field-by-field mapping and equivalence verification before the legacy
sources can be retired. The six optional letter narratives are outside the
current generator inventory and remain deferred.
## Person roles and family relationships

`case_person_roles` is the authoritative store for operational Case roles:
`applicant`, `representative`, `sponsor`, `host`, and `other`.
`persons.roles` remains a persisted compatibility projection and is updated in
the same transaction by supported services. It uses exactly the same vocabulary.

Kinship is an independent dimension stored in `family_relationships` as
`spouse`, `former_spouse`, `parent`, or `child`; `parent_type` carries explicit
mother/father semantics when the source actually provides them. A relative may
also hold an operational role (for example, a parent who is a sponsor) without
either dimension overwriting the other.

`FamilyRelationship.is_current` models partner history, not whether a
biological or legal family connection still exists. It is true only for the
current `spouse`. It is false for `former_spouse`, `parent`, and `child`; those
relationship types carry their own enduring semantics without this flag.
