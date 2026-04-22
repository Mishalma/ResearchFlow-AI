# Job State Machine

This document defines the canonical workflow lifecycle for async PaperEasy jobs.

## Canonical States

The top-level `status` field may only contain one of the following values:

- `CREATED`
- `GENERATION_REQUESTED`
- `GENERATING`
- `GENERATED`
- `VALIDATION_REQUESTED`
- `VALIDATING`
- `DEEP_VALIDATION_REQUESTED`
- `FIX_REQUESTED`
- `FIXING`
- `FINALIZING`
- `DONE`
- `FAILED`

The coarse-grained `stage` field may only contain one of the following values:

- `job`
- `generation`
- `validation`
- `fix`
- `finalize`
- `done`
- `failed`

## State Ownership

Only one component may move a job out of a given state.

| State | Owner | Exit Rule |
| --- | --- | --- |
| `CREATED` | Orchestrator | Validate preconditions, persist job, and enqueue generation |
| `GENERATION_REQUESTED` | Orchestrator | Cloud Tasks dispatch succeeds or exhausts dispatch retries |
| `GENERATING` | Generation service | Write formatted draft or return terminal failure |
| `GENERATED` | Orchestrator | Enqueue fast validation |
| `VALIDATION_REQUESTED` | Orchestrator | Cloud Tasks dispatch succeeds or exhausts dispatch retries |
| `VALIDATING` | Validation service | Return `clean`, `borderline`, or `flagged` decision |
| `DEEP_VALIDATION_REQUESTED` | Orchestrator | Enqueue validation in `mode=deep` |
| `FIX_REQUESTED` | Orchestrator | Enqueue fix if iterations remain; otherwise finalize as `manual_review_required` |
| `FIXING` | Fix service | Write next draft version or return terminal failure |
| `FINALIZING` | Finalize service | Write final report and accepted draft pointer |
| `DONE` | None | Terminal |
| `FAILED` | None | Terminal |

## Transition Table

| From | To | Trigger | Owner |
| --- | --- | --- | --- |
| `CREATED` | `GENERATION_REQUESTED` | Job document created and generation preconditions satisfied | Orchestrator |
| `GENERATION_REQUESTED` | `GENERATING` | Generation task accepted by Cloud Tasks target | Orchestrator |
| `GENERATION_REQUESTED` | `FAILED` | Dispatch retries exhausted before worker acceptance | Orchestrator |
| `GENERATING` | `GENERATED` | Formatted draft artifact written successfully | Generation service |
| `GENERATING` | `FAILED` | Worker retries exhausted or non-retryable generation failure | Generation service |
| `GENERATED` | `VALIDATION_REQUESTED` | Orchestrator schedules fast validation | Orchestrator |
| `VALIDATION_REQUESTED` | `VALIDATING` | Validation task accepted | Orchestrator |
| `VALIDATION_REQUESTED` | `FAILED` | Validation dispatch retries exhausted | Orchestrator |
| `VALIDATING` | `FINALIZING` | Fast validation returns `clean` | Validation service |
| `VALIDATING` | `DEEP_VALIDATION_REQUESTED` | Fast validation returns `borderline` and `validation_mode=fast` | Validation service |
| `VALIDATING` | `FIX_REQUESTED` | Validation returns `flagged`, or deep validation returns `borderline` or `flagged` | Validation service |
| `VALIDATING` | `FAILED` | Validation retries exhausted or non-retryable validation failure | Validation service |
| `DEEP_VALIDATION_REQUESTED` | `VALIDATING` | Deep validation task accepted with `validation_mode=deep` | Orchestrator |
| `DEEP_VALIDATION_REQUESTED` | `FAILED` | Deep-validation dispatch retries exhausted | Orchestrator |
| `FIX_REQUESTED` | `FIXING` | Fix task accepted and `iteration < max_iterations` | Orchestrator |
| `FIX_REQUESTED` | `FINALIZING` | `iteration >= max_iterations` or no fixable sections remain | Orchestrator |
| `FIXING` | `VALIDATION_REQUESTED` | Revised draft written successfully; revalidate changed sections only | Fix service |
| `FIXING` | `FAILED` | Worker retries exhausted or non-retryable fix failure | Fix service |
| `FINALIZING` | `DONE` | Final report and accepted draft persisted | Finalize service |
| `FINALIZING` | `FAILED` | Finalize retries exhausted or non-retryable finalize failure | Finalize service |

## Execution Rules

### Routing

The decision engine applies these rules:

- `clean` -> `FINALIZING`
- `borderline` after fast validation -> `DEEP_VALIDATION_REQUESTED`
- `borderline` after deep validation -> `FIX_REQUESTED`
- `flagged` -> `FIX_REQUESTED`

### Fix Loop

- `max_iterations = 3`
- `iteration` counts completed fix attempts, not validation attempts
- revalidation after a fix must prefer changed sections only
- if a job reaches `max_iterations` and still cannot be classified as `clean`, finalization must mark the report disposition as `manual_review_required`

### Terminal Outcomes

Top-level job lifecycle ends in:

- `DONE`
- `FAILED`

The final report carries the business outcome:

- `accepted`
- `accepted_after_fix`
- `manual_review_required`
- `failed`

This keeps workflow completion separate from content disposition.
