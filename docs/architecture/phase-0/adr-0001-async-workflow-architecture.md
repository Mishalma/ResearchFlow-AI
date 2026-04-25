# ADR-0001: Async Workflow Architecture For PaperEasy

## Status

Accepted for Phase 0.

## Context

PaperEasy currently runs document generation as a synchronous backend operation. The processing UI waits for a single long-running request, and the backend route executes the full pipeline in-process before returning a result.

The current shape is:

`Browser -> Next.js BFF -> FastAPI -> run_pipeline(...) -> save project -> redirect to editor`

That design is simple, but it creates 5 constraints:

1. Request latency is bound to the full generation pipeline.
2. Retry behavior is coarse and tied to one HTTP request.
3. Humanizer and originality are tightly coupled to generation.
4. Progress reporting is mostly synthetic in the frontend.
5. Later detector and fix loops cannot be added cleanly without making the request path more fragile.

The target product requires:

- async generation
- multi-stage validation
- Desklib-first AI checks with a later final report pass
- bounded fix/humanizer loops
- immutable artifact history
- reportable workflow state

## Decision

PaperEasy will move to an async workflow architecture with the following boundaries.

### Public API Boundary

The public API remains behind the existing Next.js BFF for v1.

Reason:

- lowest-risk migration
- preserves existing auth/session and CSRF behavior
- avoids an early Cloud Run BFF cutover

### Workflow State Store

Workflow/job state will live in Firestore first.

Reason:

- flexible schema during rollout
- good fit for job documents, status, and event metadata
- avoids early relational migration work

### Artifact Store

Large workflow artifacts will live in GCS.

Reason:

- immutable draft and report blobs do not belong in Firestore
- generation and fix stages need stable blob pointers

### Stage Dispatch

Stage execution will use Cloud Tasks first.

Reason:

- deterministic stage control
- per-stage retry policies
- explicit ownership of "what runs next"

Pub/Sub may be added later for detector fan-out, but it is not part of the first cutover contract.

### Target Service Split

The target runtime split is:

- `Next.js BFF`
- `orchestrator-service`
- `generation-service`
- `validation-service`
- `fix-service`
- `finalize-service` or `aggregator/finalize-service`

The orchestrator owns state transitions and stage dispatch. Worker services do heavy work but do not decide the next stage.

### Generation Boundary

The future `generation-service` will own:

- structuring
- writing
- citation
- IEEE formatting

The extracted generation path stops after IEEE formatting.

### Validation Boundary

The future `validation-service` will own:

- Desklib AI checks as the primary remediation gate
- lexical/originality overlap checks
- citation-aware overlap checks
- final overlap/report assembly after the AI gate clears or the fix loop ends

### Fix Boundary

The future `fix-service` will own:

- humanizer behavior
- flagged-section-only rewriting
- rewrite/change tracking

The humanizer is no longer part of the default generation path.

### Finalization Boundary

The future finalize step owns:

- final score fusion
- final disposition
- normalized report generation
- accepted draft selection

## Consequences

### Positive

- generation can be retried without repeating the full public request
- progress becomes backend-driven instead of simulated
- validation and fix loops become explicit and auditable
- immutable draft versions support before/after comparisons
- later detector upgrades can plug into the workflow without changing the public API

### Negative

- more services and contracts must be managed
- job consistency becomes a first-class concern
- idempotency and duplicate-suppression become mandatory

## Rejected Alternatives

### Move the public boundary to Cloud Run immediately

Rejected for the first cutover because it combines workflow redesign with auth and traffic-boundary redesign.

### Keep the synchronous `/generate` route and add more logic inside it

Rejected because it would make retries, progress tracking, and multi-stage routing increasingly fragile.

### Split each existing agent into its own microservice immediately

Rejected because the current pipeline is already modular enough to extract at service boundaries larger than a single agent.
