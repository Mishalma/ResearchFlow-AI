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
| `GENERATING` | Generation service | Structure the source, write and gate each section with Desklib, then write formatted draft plus remediation context, or stop with partial section artifacts |
| `GENERATED` | Orchestrator | Enqueue final Desklib AI check for the completed formatted draft |
| `VALIDATION_REQUESTED` | Orchestrator | Cloud Tasks dispatch succeeds or exhausts dispatch retries |
| `VALIDATING` | Validation service | Return `accepted` or `flagged` for `ai_check` or `final_report` |
| `FIX_REQUESTED` | Orchestrator | Enqueue one backstop humanizer remediation if final formatted validation regresses above the AI gate |
| `FIXING` | Fix service | Write next draft version, return no-change diagnostics, or return terminal failure |
| `FINALIZING` | Finalize service | Write final report and accepted draft pointer |
| `DONE` | None | Terminal |
| `FAILED` | None | Terminal |

## Transition Table

| From | To | Trigger | Owner |
| --- | --- | --- | --- |
| `CREATED` | `GENERATION_REQUESTED` | Job document created and generation preconditions satisfied | Orchestrator |
| `GENERATION_REQUESTED` | `GENERATING` | Generation task accepted by Cloud Tasks target | Orchestrator |
| `GENERATION_REQUESTED` | `FAILED` | Dispatch retries exhausted before worker acceptance | Orchestrator |
| `GENERATING` | `GENERATED` | All text sections passed the section AI gate, and formatted draft plus remediation context artifacts were written successfully | Generation service |
| `GENERATING` | `FINALIZING` | A section could not pass the section AI gate; generation returned `partial_draft_v1` and `section_workflow_v1` artifacts | Generation service |
| `GENERATING` | `FAILED` | Worker retries exhausted or non-retryable generation failure | Generation service |
| `GENERATED` | `VALIDATION_REQUESTED` | Orchestrator schedules Desklib AI check | Orchestrator |
| `VALIDATION_REQUESTED` | `VALIDATING` | Validation task accepted | Orchestrator |
| `VALIDATION_REQUESTED` | `FAILED` | Validation dispatch retries exhausted | Orchestrator |
| `VALIDATING` | `FINALIZING` | Final report returns `accepted`, or AI check passes and orchestrator moves to final report | Validation service |
| `VALIDATING` | `FIX_REQUESTED` | Desklib AI check returns `flagged` and fixable AI targets remain | Validation service |
| `VALIDATING` | `FAILED` | Validation retries exhausted or non-retryable validation failure | Validation service |
| `FIX_REQUESTED` | `FIXING` | Backstop fix task accepted and no backstop attempt has been used | Orchestrator |
| `FIX_REQUESTED` | `FINALIZING` | Backstop attempt already used or no fixable AI sections remain after final report is prepared | Orchestrator |
| `FIXING` | `VALIDATION_REQUESTED` | Revised draft written successfully and must be rechecked | Fix service |
| `FIXING` | `FAILED` | Worker retries exhausted or non-retryable fix failure | Fix service |
| `FINALIZING` | `DONE` | Final report and accepted draft persisted | Finalize service |
| `FINALIZING` | `FAILED` | Finalize retries exhausted or non-retryable finalize failure | Finalize service |

## Execution Rules

### Routing

The decision engine applies these rules:

- During `GENERATING`, each section is written and checked before the next section begins.
- Section gate accepted -> continue to the next section.
- Section gate rejected after writing candidates and section humanizer strategies -> stop early, store `partial_draft_v1.json` and `section_workflow_v1.json`, then finalize as `flagged`.
- `ai_check` with `ai_score <= 10%` -> run `final_report`
- `ai_check` with `ai_score > 10%` after formatting and fixable AI targets -> one backstop `FIX_REQUESTED`
- `ai_check` with `ai_score > 10%` and no remaining fix path -> run `final_report`, then finalize as `flagged`
- `final_report` accepted -> `FINALIZING`
- `final_report` flagged -> `FINALIZING`

### Section-Gated Generation

- Generation keeps the public job state as `GENERATING`; section progress is internal metadata, not a new public top-level state.
- Fixed section order: `abstract`, `introduction`, `related_work`, `methodology`, `results`, `discussion`, `limitations`, `conclusion`.
- For each section, the writing agent produces section candidates from the structured evidence map.
- The validation service scores candidates with Desklib-only candidate scoring: `accept_mode = ai_only`, `compute_overlap = false`.
- If a candidate reaches `ai_score <= 10%`, it is accepted and becomes context for later sections.
- If writing candidates fail, the section-only humanizer attempts `evidence_section` and `detector_feedback` full-section strategies.
- If the section still cannot pass, generation stops early and returns partial artifacts instead of continuing to expensive downstream stages.
- Figures, tables, citations, references, and IEEE formatting run only after all text sections pass the section AI gate.

### Fix Loop

- default backstop `max_iterations = 1` when section-gated generation is enabled
- `iteration` counts completed fix attempts, not validation attempts
- remediation uses the generation-time `remediation_context` artifact so flagged sections can be rebuilt from evidence notes instead of only paraphrased
- full-section candidate rewrites are ranked by Desklib improvement and protected-span/semantic safety checks
- revalidation after an applied fix must prefer changed sections only for the Desklib AI recheck
- overlap review runs after AI passes, plus once on the final flagged draft so the report includes final overlap metrics
- if the backstop cannot lower the formatted draft below the 10% AI threshold, finalization must mark the report disposition as `flagged`

### Terminal Outcomes

Top-level job lifecycle ends in:

- `DONE`
- `FAILED`

The final report carries the business outcome:

- `accepted`
- `accepted_after_fix`
- `flagged`
- `failed`

This keeps workflow completion separate from content disposition.
