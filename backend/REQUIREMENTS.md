# TRV requirement engine

Milestone 4 adds a deterministic, auditable requirement engine for the Canada
TRV workflow. It does not attempt to encode a complete immigration checklist or
provide legal advice. Rules are limited to requirements supported by the
project's verified internal sources.

## Configuration

Version-controlled JSON is used so the engine has no additional runtime parser
dependency:

- `app/config/document_types.json` defines canonical document types and reusable
  requirement groups.
- `app/config/rules/trv.json` defines stable rule IDs, conditions, groups, and
  human-readable reasons.

Configuration is loaded and strictly validated at application import time.
Unknown fields, malformed conditions, duplicate rule or document IDs, unknown
groups, and unknown document types fail fast. Paths are resolved relative to
the application package and are independent of the host operating system.

## Supported rules

- `TRV_BASE_INTERNAL_001` creates an internal applicant checklist for passport
  bio page, identity document, civil-status document, and digital photo. The
  project sources describe uploads as optional and do not establish these as
  universal legal requirements, so these entries are supporting and
  nonblocking.
- `TRV_SPONSOR_BANK_001` creates a required, blocking sponsor bank-statement
  requirement only when the latest applicable `sponsor.exists` fact is
  confirmed and exactly `true`.
- `TRV_HOST_BRANCH_001` records the confirmed-host branch as applicable but
  intentionally generates no document. The available sources do not specify a
  concrete host document requirement safely enough to encode one.

No rules are inferred for employment, self-employment, studies, previous
travel, host documents, sponsor identity/tax/payroll/business documents, or
other financial evidence. Those branches remain unsupported until a reviewed
source defines their exact condition, ownership, level, and blocking behavior.

## Fact and ownership policy

Only facts with status `confirmed` participate in rule evaluation. Proposed,
conflicting, and rejected facts do not activate conditional rules. Where more
than one confirmed fact has the same key, the latest persisted fact wins.

Generated requirements keep the configured `owner_role`. `owner_person_id` is
set only when exactly one person in the case has that role; otherwise it remains
null. Person creation and role changes trigger reevaluation so a unique owner
can be linked later without inventing an identity.

## Lifecycle and auditability

The stable generated identity is `(rule_id, document_type, owner_role)`.
Evaluation is idempotent:

- a missing applicable requirement is created;
- an inactive applicable requirement is reactivated;
- a no-longer-applicable generated requirement is deactivated, never deleted;
- an already-correct requirement is unchanged.

Manual requirements have no `rule_id` and are never modified by the engine.
Generated requirements retain their database identity, fulfilment state,
waiver metadata, and history across deactivation and reactivation. The engine
updates only derived configuration fields such as ownership, level, reason, and
blocking status.

Milestone 7 adds a validated completeness policy. Existing and generated rules
default to `single_document`. A `month_coverage` policy is available only with
explicit required `YYYY-MM` values; current TRV rules do not invent a period.
Reactivation evaluates existing accepted matched evidence. Automatically
derived fulfilment can regress when evidence disappears, while manual
fulfilment and waivers remain protected. See [QUALITY.md](QUALITY.md).

## Triggers and API

The application service evaluates requirements after case creation or update,
after person creation or update, and after creation or update of a fact key used
by the current rule catalog. Operators can also request an explicit idempotent
reevaluation:

```text
POST /cases/{case_id}/requirements/evaluate
```

The response separates `created`, `reactivated`, `deactivated`, and `unchanged`
requirements. The employee UI exposes this action and identifies Automatic
requirements with their rule provenance separately from Manual entries.

## Workflow boundary

The requirement engine never changes workflow state. Existing workflow and
Next Action services consume active blocking requirements through their normal
gate logic. A newly activated blocker can therefore change the reported Next
Action, but it does not silently regress or advance the case state.

No schema migration is required for Milestone 4 because the Milestone 1/2
Requirement model already contains `rule_id`, `active`, ownership, level,
blocking, fulfilment, and waiver fields.

Milestone 8 may add confirmed `sponsor.exists` or `host.exists` FACTS only after
employee review of a WhatsApp extraction candidate. The existing application
service and RequirementEngine boundary is then invoked; the extractor never
creates requirements itself. See [WHATSAPP.md](WHATSAPP.md).
