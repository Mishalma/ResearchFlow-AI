# Migration Map: Current Monolith To Target Async Workflow

This document maps the current PaperEasy implementation to the target workflow architecture frozen in Phase 0.

## Migration Principles

- keep the existing Next.js BFF
- keep upload and project persistence behavior working during the cutover
- extract generation before adding AI-check and final-report workflow complexity
- move humanizer out of the default pipeline and into the later fix loop
- replace third-party originality scanning with internal validation in later phases

## Mapping Table

| Current Component | Current Behavior | Future Owner | Action | Notes |
| --- | --- | --- | --- | --- |
| `Next.js BFF` | Browser calls curated `app/api/*` routes that forward to backend | Next.js BFF | Keep | Public API boundary remains here in v1 |
| `POST /generate` backend route | Runs full pipeline synchronously and returns generated paper | Orchestrator + generation/finalize services | Retire as public workflow entrypoint | Replace with `POST /api/jobs` and async orchestration |
| `run_pipeline(...)` through formatting | Structuring, writing, figure/table, citation, formatting | Generation service | Extract | Future generation service stops after IEEE formatting |
| `run_pipeline(...)` humanizer step | Runs by default after formatting | Fix service | Extract and remove from default path | Humanizer becomes conditional fix behavior |
| `run_pipeline(...)` originality step | Provider-backed originality/compliance gate | Validation service + finalize service | Replace | Internal validation stack will own scores and routing |
| Current originality scanner | Uses Winston AI with Copyleaks fallback | Validation service | Retire | Replaced by internal overlap/AI validation |
| Current processing screen | Calls one blocking generate request and waits | Processing status flow | Replace | Future screen creates job and polls status |
| Current project record | Stores generated paper and generation metadata | Project service + job/result adapter | Keep and adapt | Remains useful for editor-facing content while workflow state lives in Firestore |
| Current editor load | Reads saved paper and allows edits/exports | Editor flow | Keep | Editor later consumes accepted draft + final report |

## Phase-Oriented Cutover

### Phase 1

- add job creation and status APIs
- keep the current backend doing the work behind the scenes
- switch the processing UI from blocking request to polling

### Phase 2

- extract current generation path into a dedicated generation service
- stop generation after IEEE formatting
- persist `draft_v1`

### Phase 3

- introduce validation service
- replace provider-backed originality with internal validation
- add first aggregator/finalize behavior

### Phase 4

- extract humanizer into fix service
- introduce bounded fix loop with immutable draft versions

### Phase 5+

- add richer detector fan-out if needed without changing the public job API
- enrich report UI without changing the public job API

## Retired Behaviors

These behaviors are intentionally phased out:

- one long-running `/generate` request as the user-facing workflow contract
- default humanizer execution inside generation
- external originality providers as the baseline validation dependency
- synthetic frontend-only progress disconnected from backend state

## Kept Behaviors

These remain stable through the cutover:

- browser talks to Next.js, not directly to worker services
- project upload and extraction still create the starting project data
- editor remains the destination for accepted drafts
- export behavior stays tied to accepted paper content
