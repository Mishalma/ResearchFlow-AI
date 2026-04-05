# PaperEasy Backend

FastAPI backend for uploading PDF and DOCX files, extracting clean text, and turning that raw content into a structured research paper through a modular multi-agent pipeline powered by Gemini on Vertex AI.

## What is included

- File upload and text extraction for `.pdf` and `.docx`
- In-memory project storage for MVP development
- `POST /generate` backed by a stateless multi-agent pipeline
- A2A-style JSON message passing between agents
- MCP-style tool registry for citation and search tools
- Vertex AI Gemini integration using `gemini-2.5-flash`
- Basic logging, retries, and per-agent timing metadata

## Agent pipeline

1. `StructuringAgent`
   Converts raw extracted text into `abstract`, `introduction`, `methodology`, and `conclusion`.
2. `WritingAgent`
   Improves clarity and academic tone without adding unsupported claims.
3. `CitationAgent`
   Calls simulated MCP tools to attach structured references.
4. `FormattingAgent`
   Produces an IEEE-style paper layout and final formatted output.

## Project structure

```text
backend/
+-- agents/
+-- app/
+-- core/
+-- mcp/
+-- models/
+-- orchestration/
+-- uploads/
+-- .env
+-- README.md
+-- requirements.txt
```

## Prerequisites

- Python 3.10+
- A Google Cloud project with Vertex AI enabled
- A service account JSON file with Vertex AI access

## Install dependencies

```bash
pip install -r requirements.txt
```

## Environment variables

The backend reads configuration from `backend/.env`.

```env
APP_NAME=PaperEasy Backend
DEBUG=true
MAX_UPLOAD_SIZE_MB=10
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
VERTEX_MODEL=gemini-2.5-flash
VERTEX_SERVICE_ACCOUNT_FILE=./service-account.json
AI_REQUEST_TIMEOUT_SECONDS=60
AI_SOURCE_TEXT_MAX_CHARS=20000
AI_TEMPERATURE=0.2
AI_MAX_OUTPUT_TOKENS=2000
AGENT_RETRY_ATTEMPTS=2
AGENT_RETRY_BACKOFF_SECONDS=1
CITATION_RESULT_LIMIT=3
```

`VERTEX_SERVICE_ACCOUNT_FILE` may be absolute or relative to `backend/`.

## Run the development server

```bash
uvicorn app.main:app --reload --port 8000
```

If port `8000` is already in use on your machine, run another port such as `8001`.

## API endpoints

### Health check

```bash
GET /
GET /health
```

### Upload a file

```bash
POST /upload
```

Accepted file types:

- `.pdf`
- `.docx`

Successful response example:

```json
{
  "project_id": "uuid",
  "file_name": "paper.pdf",
  "extracted_text": "Clean extracted content...",
  "file_type": "pdf",
  "file_size": 1024,
  "extraction_time_ms": 12.34
}
```

### Generate a research paper

```bash
POST /generate
```

Request body:

```json
{
  "project_id": "uuid"
}
```

Successful response example:

```json
{
  "project_id": "uuid",
  "generated_paper": {
    "abstract": "...",
    "introduction": "...",
    "methodology": "...",
    "conclusion": "...",
    "references": [
      "[1] A. Sharma and L. Chen, \"...\", Simulated MCP Research Index, 2022."
    ],
    "citation_sources": [
      {
        "title": "...",
        "authors": ["A. Sharma", "L. Chen"],
        "year": 2022,
        "source": "Simulated MCP Research Index",
        "query": "...",
        "ieee_reference": "[1] ..."
      }
    ],
    "formatted_paper": "RESEARCH PAPER\n\nAbstract\n..."
  },
  "provider": "vertex_ai",
  "model": "gemini-2.5-flash",
  "generation_time_ms": 1532.8,
  "trace_id": "uuid",
  "agent_timings": [
    {"agent": "structuring_agent", "duration_ms": 412.1},
    {"agent": "writing_agent", "duration_ms": 376.5},
    {"agent": "citation_agent", "duration_ms": 18.2},
    {"agent": "formatting_agent", "duration_ms": 1.1}
  ]
}
```

### Retrieve a project

```bash
GET /project/{project_id}
```

The stored project includes the effective editor `sections`, the original `generated_sections`, any `edited_sections`, and generation metadata after `/generate` succeeds.

### Save edited sections

```bash
POST /save
```

Request body:

```json
{
  "project_id": "uuid",
  "sections": {
    "abstract": "Updated abstract text",
    "introduction": "Updated introduction text"
  }
}
```

The save API supports partial updates, stores `edited_sections`, and updates `updated_at` in the in-memory project store.

## Testing workflow

1. Start the backend with `uvicorn app.main:app --reload`.
2. Upload a PDF or DOCX file from Postman, curl, or the frontend.
3. Confirm the response includes extracted text and a `project_id`.
4. Call `POST /generate` with the `project_id`.
5. Request `GET /project/{project_id}` to fetch the stored paper and metadata.

## Notes

- Uploaded files are stored in `backend/uploads`.
- Files larger than 10MB are rejected.
- Error responses use the shape `{ "error": "..." }`.
- CORS is enabled for `http://localhost:3000` and `http://127.0.0.1:3000`.
- The in-memory project store resets when the backend restarts.
- The MCP citation and search tools are simulated placeholders for now, designed so they can be replaced with real services later.
- The agents are stateless and structured to map cleanly onto ADK and future Vertex AI Agent Engine deployment.


## Figure uploads and export

### Upload a figure

```bash
POST /figure/upload
```

Form fields:

- `project_id`
- `caption`
- `section` (`abstract`, `introduction`, `methodology`, or `conclusion`)
- `file` (`.png`, `.jpg`, `.jpeg`)

Successful response example:

```json
{
  "project_id": "uuid",
  "figure": {
    "id": "uuid",
    "path": "static/figures/uuid.png",
    "public_url": "/static/figures/uuid.png",
    "caption": "Graph of results",
    "section": "methodology"
  }
}
```

### Export the document

```bash
POST /export/latex
POST /export/docx
POST /export/pdf
```

Request body:

```json
{
  "project_id": "uuid"
}
```

Each export endpoint streams the generated file as a download response and records the artifact in the in-memory project under `exports`.

- LaTeX uses `backend/templates/ieee_template.tex`
- DOCX uses `python-docx`
- PDF uses `pdflatex` and will return a service error if `pdflatex` is not installed or not on `PATH`

### Static assets

- Uploaded figures are stored in `backend/static/figures`
- Generated export files are stored in `backend/outputs`
- Figures are previewable through `/static/figures/<filename>`
