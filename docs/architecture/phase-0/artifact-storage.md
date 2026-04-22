# Artifact Storage And Versioning

This document defines the immutable artifact model for async workflow jobs.

## Storage Split

- GCS stores large blobs and immutable workflow artifacts.
- Firestore stores job state, scores, metadata, and pointers to artifacts.

Workers never embed large draft or report bodies directly in Firestore.

## Bucket Layout

Phase 0 freezes the logical layout to:

```text
gs://<workflow-bucket>/projects/<project_id>/jobs/<job_id>/
```

Each job owns a private artifact subtree.

## Canonical Object Paths

| Artifact | Path |
| --- | --- |
| `raw_upload` | `projects/<project_id>/jobs/<job_id>/sources/raw_upload.bin` |
| `extracted_text` | `projects/<project_id>/jobs/<job_id>/sources/extracted_text.json` |
| `draft_v1` | `projects/<project_id>/jobs/<job_id>/drafts/draft_v1.json` |
| `draft_v2` | `projects/<project_id>/jobs/<job_id>/drafts/draft_v2.json` |
| `draft_v3` | `projects/<project_id>/jobs/<job_id>/drafts/draft_v3.json` |
| generation metadata | `projects/<project_id>/jobs/<job_id>/metadata/generation.json` |
| validation sidecar | `projects/<project_id>/jobs/<job_id>/metadata/validation_<mode>_<revision>.json` |
| fix sidecar | `projects/<project_id>/jobs/<job_id>/metadata/fix_<revision>.json` |
| `final_report` | `projects/<project_id>/jobs/<job_id>/reports/final_report.json` |
| `final_accepted_draft` | `projects/<project_id>/jobs/<job_id>/reports/final_accepted_draft.json` |

## Versioning Rules

### Immutable Writes

- `draft_v1`, `draft_v2`, and `draft_v3` are write-once artifact keys.
- no worker may overwrite an existing draft artifact
- if a task retries after a successful write, it must return the existing artifact pointer

### Draft Progression

- `draft_v1` is created only by the generation stage
- `draft_v2` and `draft_v3` may only be created by the fix stage
- `current_draft_uri` on the job always points to the most recent accepted draft version for the workflow

### Final Outputs

- `final_report` is created only by finalize
- `final_accepted_draft` is created only by finalize
- `final_accepted_draft` points to the accepted content body after all validation and fix decisions have completed

## Artifact Ownership

| Artifact | Owner Service |
| --- | --- |
| `raw_upload` | upload flow or migration adapter |
| `extracted_text` | upload flow or migration adapter |
| `draft_v1` | generation-service |
| `draft_v2` | fix-service |
| `draft_v3` | fix-service |
| `final_report` | finalize-service |
| `final_accepted_draft` | finalize-service |

## Compatibility With Current Project Records

During the first migration phases, the current project record may still be the source of truth for uploaded content and extracted text.

To support that transition:

- `raw_upload` and `extracted_text` may be backfilled into the job artifact model from existing project storage
- once a job is created, downstream stages must consume the job artifact pointers instead of reading mutable project state directly

This allows the upload flow to migrate later without blocking the async workflow cutover.

## Metadata Requirements

Every artifact pointer stored in Firestore must include:

- full GCS URI
- owner service
- version key
- content type
- creation timestamp
- optional checksum

## Deletion And Retention

Phase 0 freezes the retention behavior at the policy level:

- drafts are not deleted during active job execution
- final reports are retained for audit and support workflows
- cleanup of intermediate artifacts is a later operational policy and must never break replay of active jobs
