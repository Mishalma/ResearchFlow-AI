# Cloud Tasks Dispatch Contract

Phase 0 freezes Cloud Tasks as the first-stage dispatch mechanism between the orchestrator and worker services.

## Queue Layout

The v1 workflow uses 5 queues:

- `papereasy-generation`
- `papereasy-validation-fast`
- `papereasy-validation-deep`
- `papereasy-fix`
- `papereasy-finalize`

Reason:

- each stage gets its own retry and concurrency policy
- deep validation can be throttled separately from fast validation

## Target Endpoints

| Queue | Target Endpoint |
| --- | --- |
| `papereasy-generation` | `POST /internal/generation/run` |
| `papereasy-validation-fast` | `POST /internal/validation/run` with `config.mode=fast` |
| `papereasy-validation-deep` | `POST /internal/validation/run` with `config.mode=deep` |
| `papereasy-fix` | `POST /internal/fix/run` |
| `papereasy-finalize` | `POST /internal/finalize/run` |

## Shared Task Payload

Every Cloud Task payload must conform to this structure:

```json
{
  "schema_version": "1.0.0",
  "task_id": "task_123",
  "job_id": "job_123",
  "project_id": "project_123",
  "user_id": "user_123",
  "attempt": 1,
  "idempotency_key": "idem_123",
  "expected_status": "VALIDATION_REQUESTED",
  "stage": "validation",
  "current_draft_uri": "gs://.../draft_v1.json",
  "artifacts": {
    "raw_upload": "gs://...",
    "extracted_text": "gs://..."
  },
  "config": {},
  "trace": {
    "request_id": "req_123",
    "parent_job_status": "VALIDATION_REQUESTED"
  }
}
```

## Required Headers

The orchestrator must send the following headers with each task:

- `Content-Type: application/json`
- `X-PaperEasy-Job-Id: <job_id>`
- `X-PaperEasy-Task-Id: <task_id>`
- `X-PaperEasy-Attempt: <attempt>`
- `X-PaperEasy-Expected-Status: <expected_status>`

Authentication is performed using service-to-service identity tokens. Worker endpoints must reject unauthenticated requests.

## Retry Policy

Retry responsibility is split into 2 layers:

- Cloud Tasks handles transport-level retries
- the worker handles service-local retries inside its own stage logic

### Per-Queue Retry Defaults

| Queue | Max Dispatch Attempts | Min Backoff | Max Backoff |
| --- | --- | --- | --- |
| `papereasy-generation` | 3 | 10s | 5m |
| `papereasy-validation-fast` | 3 | 5s | 2m |
| `papereasy-validation-deep` | 2 | 30s | 10m |
| `papereasy-fix` | 2 | 15s | 5m |
| `papereasy-finalize` | 3 | 5s | 2m |

## Dispatch Preconditions

Before enqueueing a task, the orchestrator must:

1. persist the job state transition to the relevant `*_REQUESTED` state
2. persist the expected worker input artifact pointers
3. persist `active_task.task_id`, `queue_name`, `worker_target`, and `attempt`

Workers must reject the task if:

- the persisted job state no longer matches `expected_status`
- the job already moved to a later state
- the targeted artifact pointer does not exist

This keeps task replay safe.

## Idempotency Rules

- `task_id` must be unique per stage attempt
- workers must treat `(job_id, task_id, attempt)` as the transport idempotency key
- fix workers additionally treat `target_draft_key` as a write-once artifact key
- finalize workers additionally treat `finalization_revision` as a write-once artifact key

## Future Compatibility

If later phases add Pub/Sub fan-out for parallel detectors:

- the public BFF APIs stay unchanged
- the orchestrator job model stays unchanged
- Pub/Sub is used only inside the validation subsystem
- the normalized validation output fed back into the orchestrator remains unchanged
