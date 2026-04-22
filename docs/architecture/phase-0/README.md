# Phase 0: Async Workflow Architecture Freeze

This folder contains the Phase 0 specification package for moving PaperEasy from the current synchronous generation flow to an async workflow architecture.

Phase 0 is intentionally documentation-first. It does not introduce runtime behavior yet. Its job is to freeze the contracts that later phases will implement.

## Why This Exists

Today, the main flow still runs as one blocking request:

- the frontend processing screen calls `generateProjectPaper(...)`
- the Next.js BFF forwards the request to the backend
- the backend route runs the full pipeline synchronously

That behavior currently lives in:

- `app/(protected)/processing/processing-client.tsx`
- `lib/backend.ts`
- `backend/app/api/routes/generate.py`
- `backend/orchestration/pipeline.py`

Phase 0 freezes the target shape for replacing that flow with:

`create job -> orchestrate async stages -> finalize report -> poll results`

## Deliverables In This Folder

- [adr-0001-async-workflow-architecture.md](./adr-0001-async-workflow-architecture.md)
  Architecture decisions, ownership split, and infra defaults.
- [job-state-machine.md](./job-state-machine.md)
  Canonical job lifecycle, legal transitions, and state ownership.
- [job.schema.json](./job.schema.json)
  Frozen schema for workflow jobs and stage-owned metadata.
- [api-contracts.md](./api-contracts.md)
  Public BFF APIs and internal service APIs with request/response contracts.
- [cloud-tasks-dispatch.md](./cloud-tasks-dispatch.md)
  Dispatch model, queue layout, headers, payload contract, and retry rules.
- [artifact-storage.md](./artifact-storage.md)
  GCS layout, versioning rules, and artifact ownership.
- [final-report.schema.json](./final-report.schema.json)
  Normalized final report contract for AI/originality results.
- [migration-map.md](./migration-map.md)
  Mapping from the current monolith flow to the target async workflow.

## Acceptance Checklist

Phase 0 is complete only if all of the following are true:

- Every state transition has one owner and one next-step rule.
- Every public or internal API specifies input, output, timeout, retry behavior, and idempotency behavior.
- Every worker-written artifact has a deterministic GCS path and immutable version rule.
- The future processing UI can be built using only `job status` and `job result` APIs.
- Later phases do not need to invent new public endpoints or replace the job model.

## Chosen Defaults

- Keep the existing Next.js BFF as the public API boundary in v1.
- Use Firestore for workflow/job state first.
- Use Cloud Tasks first for orchestrator-to-worker stage dispatch.
- Keep generation synchronous inside the future `generation-service`.
- Stop the extracted generation path after IEEE formatting.
- Move the current humanizer into the future `fix-service`.
- Treat deep GPU validation as a later phase, not a cutover prerequisite.
