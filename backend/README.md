# PaperEasy Backend

FastAPI backend for uploading source documents, extracting clean text, generating research papers through a configurable multi-agent Vertex AI pipeline, and persisting projects with either local storage or Google Cloud services.

## What is included

- PDF and DOCX upload plus text extraction
- Configurable multi-agent pipeline powered by Gemini on Vertex AI
- A2A-style in-process message dispatch with a transport abstraction for future remote A2A
- MCP-style internal tool registry for citation and search tools
- Local persistence adapters for VS Code development
- Google Cloud adapters for Firestore and Cloud Storage
- Figure upload plus download URLs
- IEEE conference LaTeX export built from the official `conference_101719.tex` structure
- LaTeX, DOCX, and PDF export with cloud-safe artifact storage
- Cloud Run container and Cloud Build deployment config

## Architecture summary

### Agents

The generation pipeline runs specialized agents in a section-gated order:

1. `structuring_agent`
2. `writing_agent`
3. Desklib AI candidate scoring through the validation service
4. section-only humanizer remediation when a section is flagged
5. `figure_table_agent`
6. `citation_agent`
7. `formatting_agent`

Their runtime configuration lives in [agents/agent_specs.json](./agents/agent_specs.json). Each agent spec includes:

- `name`
- `role`
- `prompt_template`
- `input_schema`
- `output_schema`
- `model`
- `enabled_tools`
- `timeout_seconds`
- `retry_policy`

### Persistence backends

The backend supports two persistence modes controlled by `PERSISTENCE_BACKEND`:

- `local`
  - project metadata is stored as JSON under `backend/data/projects`
  - uploads, figures, and exports are stored on local disk
- `gcp`
  - project metadata is stored in Firestore
  - uploads, figures, and exports are stored in Cloud Storage

## Environment variables

The backend reads configuration from `backend/.env`.

```env
APP_NAME=PaperEasy Backend
DEBUG=true
PERSISTENCE_BACKEND=local
LOCAL_PROJECTS_DIR=./data/projects
TEMP_DIR=./.tmp
GCS_BUCKET_NAME=
FIRESTORE_PROJECTS_COLLECTION=papereasy-projects
AGENT_SPECS_PATH=./agents/agent_specs.json
MAX_UPLOAD_SIZE_MB=10
MAX_FIGURE_SIZE_MB=10
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=us-central1
VERTEX_MODEL=gemini-2.5-flash
VERTEX_SERVICE_ACCOUNT_FILE=
AI_REQUEST_TIMEOUT_SECONDS=60
AI_SOURCE_TEXT_MAX_CHARS=20000
AI_TEMPERATURE=0.2
AI_MAX_OUTPUT_TOKENS=2000
STRUCTURING_USE_LLM_REDUCER=false
AGENT_RETRY_ATTEMPTS=2
AGENT_RETRY_BACKOFF_SECONDS=1
CITATION_RESULT_LIMIT=3
PDFLATEX_TIMEOUT_SECONDS=60
```

Notes:

- For local development, keep `PERSISTENCE_BACKEND=local`.
- For Cloud Run, use `PERSISTENCE_BACKEND=gcp` and set `TEMP_DIR=/tmp`.
- On Cloud Run, prefer the attached service account instead of `VERTEX_SERVICE_ACCOUNT_FILE`.
- Locally, Vertex can use ADC from `gcloud auth application-default login`.
- `STRUCTURING_USE_LLM_REDUCER=false` keeps the fast deterministic structuring path enabled by default. Set it to `true` only if you explicitly want the slower LLM reduction pass.

## Install dependencies

```bash
pip install -r requirements.txt
```

## Run locally

From `backend/`:

```bash
uvicorn app.main:app --reload --port 8000
```

If `8000` is already in use, run another port such as `8001` or `8002`.

## Connect the local frontend

This repo uses a private Cloud Run proxy pattern in Next.js. The browser should call Next.js API routes, not the backend directly.

For a local backend during development, set the frontend backend URL in `.env.local`:

```env
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000
```

If you deploy the backend to Cloud Run, keep the browser on the Next.js app and configure the server-side proxy envs instead:

```env
CLOUD_RUN_SERVICE_URL=https://YOUR-CLOUD-RUN-URL
CLOUD_RUN_ID_TOKEN_AUDIENCE=https://YOUR-CLOUD-RUN-URL
```

Restart the Next.js dev server after changing `.env.local`.

## API endpoints

### Health

```http
GET /
GET /health
```

### Upload source document

```http
POST /upload
```

Accepts `.pdf` and `.docx`.

Response example:

```json
{
  "project_id": "uuid",
  "file_name": "paper.docx",
  "extracted_text": "Clean extracted content...",
  "file_type": "docx",
  "file_size": 36765,
  "extraction_time_ms": 45.2
}
```

### Generate paper

```http
POST /generate
```

Request body:

```json
{
  "project_id": "uuid"
}
```

### Load project

```http
GET /project/{project_id}
```

Returns the stored project, including:

- `authors`
- `keywords`
- `generated_sections`
- `edited_sections`
- effective `sections`
- `figures`
- `exports`
- `generated_paper`
- `generation_metadata`

### Save edited sections

```http
POST /save
```

Request body:

```json
{
  "project_id": "uuid",
  "title": "Research Paper Title",
  "authors": ["Author Name, Affiliation"],
  "keywords": ["keyword one", "keyword two"],
  "sections": {
    "abstract": "Updated abstract",
    "introduction": "Updated introduction",
    "methodology": "Updated methodology",
    "conclusion": "Updated conclusion"
  }
}
```

### Upload figure

```http
POST /figure/upload
GET /figure/{project_id}/{figure_id}
```

Form fields for upload:

- `project_id`
- `caption`
- `section`
- `file`

Accepted figure types:

- `.png`
- `.jpg`
- `.jpeg`

### Export

```http
POST /export/latex
POST /export/docx
POST /export/pdf
GET /export/{project_id}/{export_id}
```

The `POST` export endpoints stream the file immediately and also persist an export artifact. The `GET` export endpoint downloads a previously stored artifact.

The LaTeX output follows the official IEEE conference template shape:

- `\documentclass[conference]{IEEEtran}`
- `\IEEEoverridecommandlockouts`
- IEEE title and author block formatting
- two-column `IEEEtran` document structure
- `figure` blocks using `\centerline{\includegraphics[width=\linewidth]{...}}`

## Cloud Run deployment

The backend includes:

- [Dockerfile](./Dockerfile)
- [cloudbuild.yaml](./cloudbuild.yaml)
- [cloudbuild-generation.yaml](./cloudbuild-generation.yaml)
- [cloudbuild-validation.yaml](./cloudbuild-validation.yaml)
- [cloudbuild-fix.yaml](./cloudbuild-fix.yaml)
- [agents/agent_specs.json](./agents/agent_specs.json)
- [templates/ieee_template.tex](./templates/ieee_template.tex)
- [templates/IEEEtran.cls](./templates/IEEEtran.cls)

Typical deploy flow:

1. Create an Artifact Registry repository.
2. Create a Cloud Storage bucket for project objects.
3. Enable Firestore in your Google Cloud project.
4. Grant the Cloud Run service account access to:
   - Vertex AI generation
   - Cloud Storage object read/write
   - Firestore document read/write
5. Grant the Next.js server-side runtime identity Cloud Run invocation access to the private backend.
6. Run Cloud Build or `gcloud run deploy` from `backend/`.

Example command:

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_SERVICE_ACCOUNT=YOUR_SERVICE_ACCOUNT,_GCS_BUCKET=YOUR_BUCKET
```

### Phase 2 generation-service deploy

Phase 2 now writes the paper section by section. Each text section is scored with Desklib AI-only candidate scoring before the next section starts. If a section cannot pass after writing candidates and section-only humanizer strategies, the service stores `partial_draft_v1.json` and `section_workflow_v1.json` and stops before figures, citations, references, and IEEE formatting. Deploy it with:

```bash
gcloud builds submit --config cloudbuild-generation.yaml \
  --substitutions=_SERVICE_ACCOUNT=YOUR_GENERATION_SERVICE_ACCOUNT,_GCS_BUCKET=YOUR_BUCKET
```

This deploys `papereasy-generation` with:

- public ingress with authenticated invocation only (`--ingress=all` plus `--no-allow-unauthenticated`)
- authenticated invocation only
- a 30 minute request timeout
- `uvicorn app.generation_main:app`
- section-gated generation enabled (`GENERATION_SECTION_GATE_ENABLED=true`)
- Desklib candidate scoring delegated to the validation service with overlap disabled during section gating
- figures, citations, references, and IEEE formatting run only after all text sections pass the AI gate

After the generation service is deployed, update the main backend service to call it by setting:

```env
WORKFLOW_GENERATION_BACKEND=service
GENERATION_SERVICE_BASE_URL=https://YOUR-GENERATION-SERVICE-URL
GENERATION_SERVICE_AUDIENCE=https://YOUR-GENERATION-SERVICE-URL
GENERATION_SERVICE_TIMEOUT_SECONDS=1500
```

The backend service account must also have `roles/run.invoker` on the generation service.

The generation service also needs access to validation scoring when section gating is enabled:

```env
WORKFLOW_VALIDATION_BACKEND=service
VALIDATION_SERVICE_BASE_URL=https://YOUR-VALIDATION-SERVICE-URL
VALIDATION_SERVICE_AUDIENCE=https://YOUR-VALIDATION-SERVICE-URL
VALIDATION_SERVICE_TIMEOUT_SECONDS=600
```

If the validation URL is left empty, section gating cannot run because Desklib scoring is the required acceptance gate.

### Phase 3 validation-service deploy

Phase 3 adds a separate internal validation service for Desklib AI checks, final overlap reporting, and internal candidate scoring. Deploy it with:

```bash
gcloud builds submit --config cloudbuild-validation.yaml \
  --substitutions=_SERVICE_ACCOUNT=YOUR_VALIDATION_SERVICE_ACCOUNT,_GCS_BUCKET=YOUR_BUCKET
```

This deploys `papereasy-validation` with:

- public ingress with authenticated invocation only
- a 3 minute request timeout
- `uvicorn app.validation_main:app`
- `ai_check` and `final_report` execution
- `POST /internal/validation/score-candidates` for generation preflight and fix-service ranking

After the validation service is deployed, update the main backend service to call it by setting:

```env
WORKFLOW_VALIDATION_BACKEND=service
VALIDATION_SERVICE_BASE_URL=https://YOUR-VALIDATION-SERVICE-URL
VALIDATION_SERVICE_AUDIENCE=https://YOUR-VALIDATION-SERVICE-URL
VALIDATION_SERVICE_TIMEOUT_SECONDS=120
```

The backend service account must also have `roles/run.invoker` on the validation service.

### Phase 4 fix-service deploy

Phase 4 adds a separate internal fix service for a one-pass backstop remediation after final formatted validation. Deploy it with:

```bash
gcloud builds submit --config cloudbuild-fix.yaml \
  --substitutions=_SERVICE_ACCOUNT=YOUR_FIX_SERVICE_ACCOUNT,_GCS_BUCKET=YOUR_BUCKET
```

This deploys `papereasy-fix` with:

- public ingress with authenticated invocation only
- a 20 minute request timeout
- `uvicorn app.fix_main:app`
- Vertex-backed section rewriting enabled
- deterministic fallback disabled
- full-section candidate rewriting enabled (`FIX_FULL_SECTION_REWRITE=true`)
- Desklib-guided acceptance and no-change behavior when no safe candidate improves the score

After the fix service is deployed, update the main backend service to call it by setting:

```env
WORKFLOW_FIX_BACKEND=service
FIX_SERVICE_BASE_URL=https://YOUR-FIX-SERVICE-URL
FIX_SERVICE_AUDIENCE=https://YOUR-FIX-SERVICE-URL
FIX_SERVICE_TIMEOUT_SECONDS=1200
```

The backend service account must also have `roles/run.invoker` on the fix service.

## Verification

Validated locally after this refactor:

- `python -m compileall backend`
- `npx tsc --noEmit`
- `eslint app/editor/editor-client.tsx lib/backend.ts app/api/upload/route.ts app/api/export/pdf/route.ts app/api/export/docx/route.ts app/api/export/latex/route.ts`
- upload flow with local persistence
- project save/load flow with persisted JSON records
- figure upload plus figure download route
- IEEE LaTeX export plus artifact download route
- DOCX export plus artifact download route

PDF export still depends on `pdflatex` being installed and available on `PATH`.
