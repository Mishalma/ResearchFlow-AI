import { getBrowserCsrfToken } from "@/lib/auth/browser";

export type BackendHealthResponse = {
  status: string;
  message: string;
};

export type FigureSection =
  | "abstract"
  | "introduction"
  | "related_work"
  | "methodology"
  | "results"
  | "discussion"
  | "limitations"
  | "conclusion";

export type IEEESections = {
  introduction: string;
  related_work: string;
  methodology: string;
  results: string;
  discussion: string;
  limitations: string;
  conclusion: string;
};

export type ResearchPaper = {
  title: string;
  abstract: string;
  keywords: string[];
  sections: IEEESections;
  references: string[];
};

export type UploadProjectResponse = {
  project_id: string;
  file_name: string;
  extracted_text: string;
  file_type: string;
  file_size: number;
  extraction_time_ms: number;
};

export type FigureRecord = {
  id: string;
  original_file_name: string;
  stored_file_name: string;
  file_size: number;
  content_type: string;
  path: string;
  public_url: string;
  caption: string;
  section: FigureSection;
  uploaded_at: string;
};

export type ExportArtifact = {
  id: string;
  format: "pdf" | "docx" | "latex";
  file_name: string;
  path: string;
  download_url: string;
  created_at: string;
};

export type GeneratedPaper = {
  paper: ResearchPaper;
  formatted_text: string;
  latex_ready: string;
};

export type AgentTiming = {
  agent: string;
  duration_ms: number;
};

export type GenerateProjectResponse = {
  project_id: string;
  generated_paper: GeneratedPaper;
  provider: string;
  model: string;
  generation_time_ms: number;
  trace_id: string;
  agent_timings: AgentTiming[];
};

export type ProjectSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ProjectResponse = {
  id: string;
  title: string;
  authors: string[];
  display_paper_text: string;
  paper: ResearchPaper | null;
  figures: FigureRecord[];
};

export type SaveProjectPayload = {
  project_id?: string;
  title: string;
  authors?: string[];
  keywords?: string[];
  content?: string;
  paper?: ResearchPaper;
};

export type SaveProjectResponse = {
  success: boolean;
  project: ProjectResponse;
};

export type FigureUploadPayload = {
  projectId: string;
  caption: string;
  section: FigureSection;
  file: File;
};

export type FigureUploadResponse = {
  project_id: string;
  figure: FigureRecord;
};

export type ExportFormat = "pdf" | "docx" | "latex";

export type ExportDocumentResult = {
  blob: Blob;
  fileName: string;
  exportId: string | null;
  exportFormat: ExportFormat;
};

const apiBaseUrl = "/api";
export const backendHealthEndpoint = `${apiBaseUrl}/health`;

function getProjectEndpoint(projectId: string) {
  return `${apiBaseUrl}/project/${projectId}`;
}

function parseContentDispositionFileName(
  headerValue: string | null,
  fallback: string,
) {
  if (!headerValue) {
    return fallback;
  }

  const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const basicMatch = headerValue.match(/filename="?([^";]+)"?/i);
  if (basicMatch?.[1]) {
    return basicMatch[1];
  }

  return fallback;
}

async function readBackendError(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    try {
      const data = (await response.json()) as {
        error?: string;
        detail?: string;
        message?: string;
      };

      return (
        data.error ??
        data.detail ??
        data.message ??
        `Request failed with status ${response.status} ${response.statusText}`.trim()
      );
    } catch {
      return `Request failed with status ${response.status} ${response.statusText}`.trim();
    }
  }

  try {
    const text = (await response.text()).trim();
    if (text) {
      return text;
    }
  } catch {
    // Ignore text parsing failures and fall back to status text.
  }

  return `Request failed with status ${response.status} ${response.statusText}`.trim();
}

function buildMutationHeaders(contentType = "application/json") {
  const headers = new Headers({
    Accept: "application/json",
    "x-csrf-token": getBrowserCsrfToken(),
  });

  if (contentType) {
    headers.set("Content-Type", contentType);
  }

  return headers;
}

export function buildFigureAssetUrl(projectId: string, figureId: string) {
  return `${apiBaseUrl}/figure/${projectId}/${figureId}`;
}

export function buildStoredExportUrl(projectId: string, exportId: string) {
  return `${apiBaseUrl}/export/file/${projectId}/${exportId}`;
}

export async function fetchBackendHealth(
  signal?: AbortSignal,
): Promise<BackendHealthResponse> {
  const response = await fetch(backendHealthEndpoint, {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  return (await response.json()) as BackendHealthResponse;
}

export async function uploadSourceDocument(
  file: File,
  signal?: AbortSignal,
): Promise<UploadProjectResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${apiBaseUrl}/upload`, {
    method: "POST",
    body: formData,
    headers: {
      "x-csrf-token": getBrowserCsrfToken(),
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  return (await response.json()) as UploadProjectResponse;
}

export async function generateProjectPaper(
  projectId: string,
  signal?: AbortSignal,
): Promise<GenerateProjectResponse> {
  const response = await fetch(`${apiBaseUrl}/generate`, {
    method: "POST",
    headers: buildMutationHeaders(),
    body: JSON.stringify({ project_id: projectId }),
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  return (await response.json()) as GenerateProjectResponse;
}

export async function fetchProjects(
  signal?: AbortSignal,
): Promise<ProjectSummary[]> {
  const response = await fetch(`${apiBaseUrl}/projects`, {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  return (await response.json()) as ProjectSummary[];
}

export async function fetchProject(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectResponse> {
  const response = await fetch(getProjectEndpoint(projectId), {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  return (await response.json()) as ProjectResponse;
}

export async function saveProject(
  payload: SaveProjectPayload,
  signal?: AbortSignal,
): Promise<SaveProjectResponse> {
  const response = await fetch(`${apiBaseUrl}/save`, {
    method: "POST",
    headers: buildMutationHeaders(),
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  return (await response.json()) as SaveProjectResponse;
}

export async function uploadProjectFigure(
  payload: FigureUploadPayload,
  signal?: AbortSignal,
): Promise<FigureUploadResponse> {
  const formData = new FormData();
  formData.append("project_id", payload.projectId);
  formData.append("caption", payload.caption);
  formData.append("section", payload.section);
  formData.append("file", payload.file);

  const response = await fetch(`${apiBaseUrl}/figure/upload`, {
    method: "POST",
    body: formData,
    headers: {
      "x-csrf-token": getBrowserCsrfToken(),
    },
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  return (await response.json()) as FigureUploadResponse;
}

export async function exportProjectDocument(
  projectId: string,
  format: ExportFormat,
  signal?: AbortSignal,
): Promise<ExportDocumentResult> {
  const response = await fetch(`${apiBaseUrl}/export/${format}`, {
    method: "POST",
    headers: (() => {
      const headers = buildMutationHeaders();
      headers.set(
        "Accept",
        "application/octet-stream, application/pdf, application/x-tex, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/json",
      );
      return headers;
    })(),
    body: JSON.stringify({ project_id: projectId }),
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  const blob = await response.blob();
  const fileName = parseContentDispositionFileName(
    response.headers.get("content-disposition"),
    `research-paper.${format}`,
  );

  return {
    blob,
    fileName,
    exportId: response.headers.get("x-export-id"),
    exportFormat:
      (response.headers.get("x-export-format") as ExportFormat | null) ?? format,
  };
}

export function downloadBlob(blob: Blob, fileName: string) {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  window.setTimeout(() => {
    anchor.remove();
    URL.revokeObjectURL(url);
  }, 1000);
}
