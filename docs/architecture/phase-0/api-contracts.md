# API Contracts

This document freezes the public and internal API contracts for the async workflow cutover.

## Public API: Next.js BFF

The browser continues to talk only to the Next.js BFF. The BFF remains responsible for:

- session verification
- CSRF validation
- rate limiting
- request shaping
- forwarding trusted identity to the orchestrator

### `POST /api/jobs`

Creates a workflow job for a project that already has extracted text.

#### Request Headers

- `Content-Type: application/json`
- `x-csrf-token: <token>`
- `Idempotency-Key: <client-generated-stable-key>`

#### Request Body

```json
{
  "project_id": "project_123",
  "config": {
    "validation_depth": "standard",
    "enable_fix_loop": true,
    "max_iterations": 3
  }
}
```

#### Response

Status: `202 Accepted`

```json
{
  "job_id": "job_123",
  "status": "CREATED",
  "stage": "job",
  "poll_url": "/api/jobs/job_123",
  "result_url": "/api/jobs/job_123/result"
}
```

#### Idempotency Behavior

- The BFF forwards the `Idempotency-Key` unchanged.
- The orchestrator treats `(user_id, project_id, idempotency_key)` as the dedupe key.
- If the same request is retried and the prior job is still active, the existing `job_id` is returned.
- If the same request is retried after the prior job completed, the existing `job_id` is returned instead of creating a duplicate.

### `GET /api/jobs/{job_id}`

Returns the current workflow state.

#### Response

Status: `200 OK`

```json
{
  "job_id": "job_123",
  "project_id": "project_123",
  "status": "VALIDATING",
  "stage": "validation",
  "validation_mode": "ai_check",
  "iteration": 1,
  "progress": {
    "current_step": "validation",
    "percent": 60
  },
  "current_draft_uri": "gs://papereasy-workflows/projects/project_123/jobs/job_123/drafts/draft_v1.json",
  "scores": {
    "ai_score": 0.42,
    "plagiarism_score": 0.0,
    "confidence_band": "medium",
    "routing_decision": "flagged"
  },
  "error": null
}
```

#### Behavior

- `404` if the job does not exist or does not belong to the current user
- never blocks waiting for downstream work
- safe for aggressive polling from the processing screen

### `GET /api/jobs/{job_id}/result`

Returns the final normalized report once the job is complete.

#### Response

Status: `200 OK` when `status = DONE`

Body: the document described by `final-report.schema.json`

#### Non-terminal Behavior

- `409 Conflict` while the job is still running
- `404` if the job is unknown or belongs to another user

## Internal API: Orchestrator To Worker Services

All internal worker endpoints are authenticated using Google-signed service-to-service identity. They are not browser-facing.

### Shared Request Envelope

Every internal endpoint accepts this shared outer envelope:

```json
{
  "schema_version": "1.0.0",
  "task_id": "task_123",
  "job_id": "job_123",
  "project_id": "project_123",
  "user_id": "user_123",
  "attempt": 1,
  "idempotency_key": "idem_123",
  "expected_status": "GENERATION_REQUESTED",
  "artifacts": {
    "raw_upload": "gs://...",
    "extracted_text": "gs://..."
  },
  "config": {}
}
```

Worker implementations must reject the call if the current persisted job state does not match `expected_status`.

## `POST /internal/generation/run`

Runs structuring, writing, citation, and IEEE formatting.

### Request Additions

```json
{
  "config": {
    "stop_after": "ieee_formatting"
  }
}
```

### Response

```json
{
  "job_id": "job_123",
  "status": "GENERATED",
  "stage": "generation",
  "output": {
    "draft_artifact_key": "draft_v1",
    "draft_uri": "gs://.../draft_v1.json",
    "metadata_uri": "gs://.../generation_metadata.json"
  }
}
```

### Timeout / Retry / Idempotency

- timeout budget: `20 minutes`
- transport retries: `2`
- non-retryable failures: malformed final stage output after service-local validation retries are exhausted
- idempotent key: `(job_id, task_id, attempt)`
- repeated call with the same envelope must return the same `draft_v1` pointer rather than writing a second `draft_v1`

### Artifact Ownership

- writes `draft_v1`
- may write generation metadata sidecar blobs
- must not write `final_report` or any later draft version

## `POST /internal/validation/run`

Runs validation in either `ai_check` or `final_report` mode.

### Request Additions

```json
{
  "config": {
    "mode": "ai_check",
    "changed_sections_only": false
  },
  "current_draft_uri": "gs://.../draft_v1.json"
}
```

### Response

```json
{
  "job_id": "job_123",
  "status": "VALIDATING",
  "stage": "validation",
  "output": {
    "mode": "ai_check",
    "ai_score": 0.42,
    "plagiarism_score": 0.0,
    "confidence_band": "medium",
    "routing_decision": "flagged",
    "section_flags": [
      {
        "section_id": "introduction",
        "flag_type": "ai",
        "score": 0.72
      }
    ]
  }
}
```

### Timeout / Retry / Idempotency

- `ai_check` timeout budget: `2 minutes`
- `final_report` timeout budget: `10 minutes`
- transport retries: `2`
- repeated validation for the same `(job_id, task_id, attempt)` must return the same result summary

### Artifact Ownership

- may write validation result sidecars
- must not write draft versions
- must not write `final_report`

### Validation Semantics

- `ai_check` runs Desklib AI detection on the current draft and decides whether the workflow should enter the humanizer loop.
- `final_report` runs overlap/plagiarism scoring and assembles the final validation report using the latest accepted or flagged draft.
- the primary acceptance gate for entering or skipping the humanizer loop is `ai_score <= 10%`
- overlap is evaluated after AI passes, and once on the final flagged draft so the report includes both initial and final scores

## `POST /internal/fix/run`

Rewrites only flagged sections and produces the next immutable draft version.

### Request Additions

```json
{
  "current_draft_uri": "gs://.../draft_v1.json",
  "config": {
    "target_draft_key": "draft_v2",
    "max_iterations": 3
  },
  "flags": [
    {
      "section_id": "introduction",
      "flag_type": "ai",
      "reason": "formulaic_style"
    }
  ]
}
```

### Response

```json
{
  "job_id": "job_123",
  "status": "FIXING",
  "stage": "fix",
  "output": {
    "updated_draft_key": "draft_v2",
    "updated_draft_uri": "gs://.../draft_v2.json",
    "changed_sections": [
      "introduction"
    ]
  }
}
```

### Timeout / Retry / Idempotency

- timeout budget: `8 minutes`
- transport retries: `1`
- idempotent key: `(job_id, target_draft_key)`
- repeated call must return the same draft pointer and change summary

### Artifact Ownership

- writes only the next immutable draft version
- may write change logs and before/after sidecars
- must not overwrite prior draft artifacts

## `POST /internal/finalize/run`

Creates the normalized final report and selects the accepted draft pointer.

### Request Additions

```json
{
  "current_draft_uri": "gs://.../draft_v2.json",
  "config": {
    "final_disposition": "accepted_after_fix"
  },
  "validation_summary": {
    "ai_score": 0.16,
    "plagiarism_score": 2.8,
    "confidence_band": "high"
  }
}
```

### Response

```json
{
  "job_id": "job_123",
  "status": "DONE",
  "stage": "done",
  "output": {
    "final_report_uri": "gs://.../final_report.json",
    "final_accepted_draft_uri": "gs://.../final_accepted_draft.json",
    "final_disposition": "accepted_after_fix"
  }
}
```

### Timeout / Retry / Idempotency

- timeout budget: `60 seconds`
- transport retries: `2`
- idempotent key: `(job_id, finalization_revision)`
- repeated calls must return the same `final_report` and `final_accepted_draft` pointers

### Artifact Ownership

- writes `final_report`
- writes `final_accepted_draft`
- must not modify prior drafts
