# Workflow architecture

Milestone 2 implements the workflow exclusively in `WorkflowService`. API
clients cannot set `CASE.workflow_state` through case create/update requests.

## States and transitions

```text
INTAKE    -> DOCUMENTS
DOCUMENTS -> INTAKE | PREPARE
PREPARE   -> DOCUMENTS | REVIEW
REVIEW    -> DOCUMENTS | PREPARE | READY
READY     -> DOCUMENTS | PREPARE | REVIEW | SUBMITTED
SUBMITTED -> terminal
```

Every successful transition updates the case and creates one
`workflow_transitions` audit record in the same transaction. Audit records
contain the previous state, target state, optional actor/reason, and timestamp.

## Gates

- `INTAKE -> DOCUMENTS`: `visa_type` and `purpose` must be populated, and
  confirmed `sponsor.exists` and `host.exists` facts must exist. Proposed,
  conflicting, and rejected facts do not satisfy the gate.
- Any unresolved FACT with status `conflict` blocks forward progression.
- `DOCUMENTS -> PREPARE`: every active blocking requirement must have
  `fulfillment_status` equal to `fulfilled` or `waived`. Waivers retain reason,
  actor when supplied, and timestamp.
- `PREPARE -> REVIEW`: requires a successful PreparationRun whose payload hash,
  schema, and policy match the current canonical payload and whose complete
  expected artifact set still exists with matching SHA-256 values. A generated
  DOCUMENT or completed `preparation_complete` TASK is no longer evidence.
- `REVIEW -> READY`: no open/in-progress blocking review task may remain and an
  actor must explicitly request approval.
- `READY -> SUBMITTED`: an explicit transition request records submission state;
  no external submission occurs.

Backward transitions use the explicit map above and do not bypass history.
`SUBMITTED` is terminal unless a later business rule introduces reopening.
Status evaluation regresses stale REVIEW/READY cases through this service to
PREPARE (or DOCUMENTS for unresolved blocking requirements). SUBMITTED is not
reopened; it reports an audit discrepancy.

## Requirement resolution

Milestone 2 adds `pending`, `fulfilled`, and `waived`. Milestone 7 distinguishes
manual, waived, and `automatic_document_evidence` provenance. Completeness may
derive or regress only automatic fulfilment; manual decisions remain protected.

## Next Action

`WorkflowService.get_next_action(case_id)` returns structured data using this
priority:

1. FACT conflicts
2. unreviewed/conflicting WhatsApp FACT candidates
3. missing structural information
4. unassigned documents
5. matched active documents requiring quality work
6. pending active blocking requirements
7. open/in-progress blocking tasks
8. preparation
9. review, submission, or submitted/no action

No presentation markup, AI, requirement generation, document matching, or PDF
generation is performed by this logic.
