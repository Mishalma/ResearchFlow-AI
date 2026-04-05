export type BackendHealthResponse = {
  status: string;
  message: string;
};

export type PaperSections = {
  abstract: string;
  introduction: string;
  methodology: string;
  conclusion: string;
};

export type UploadProjectResponse = {
  project_id: string;
  file_name: string;
  extracted_text: string;
  file_type: string;
  file_size: number;
  extraction_time_ms: number;
};

export type CitationSource = {
  title: string;
  authors: string[];
  year: number | null;
  source: string;
  query: string;
  ieee_reference: string;
};

export type GeneratedPaper = PaperSections & {
  references: string[];
  citation_sources: CitationSource[];
  formatted_paper: string;
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

export type ProjectResponse = {
  id: string;
  file_name: string;
  file_path: string;
  extracted_text: string;
  file_type: string;
  file_size: number;
  extraction_time_ms: number;
  generated_sections: PaperSections | null;
  edited_sections: PaperSections | null;
  sections: PaperSections | null;
  generated_paper: GeneratedPaper | null;
  generation_metadata: {
    provider: string;
    model: string;
    generation_time_ms: number;
    source_text_length: number;
    trace_id: string;
    agent_timings: AgentTiming[];
    mcp_tools_used: string[];
  } | null;
  updated_at: string | null;
};

export type SaveProjectResponse = {
  success: boolean;
  project_id: string;
  sections: PaperSections;
  updated_at: string;
};

const backendBaseUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

export const backendHealthEndpoint = `${backendBaseUrl}/health`;

function getProjectEndpoint(projectId: string) {
  return `${backendBaseUrl}/project/${projectId}`;
}

async function readBackendError(response: Response) {
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

  const response = await fetch(`${backendBaseUrl}/upload`, {
    method: "POST",
    body: formData,
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
  const response = await fetch(`${backendBaseUrl}/generate`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ project_id: projectId }),
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  return (await response.json()) as GenerateProjectResponse;
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

export async function saveProjectSections(
  projectId: string,
  sections: Partial<PaperSections>,
  signal?: AbortSignal,
): Promise<SaveProjectResponse> {
  const response = await fetch(`${backendBaseUrl}/save`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      project_id: projectId,
      sections,
    }),
    signal,
  });

  if (!response.ok) {
    throw new Error(await readBackendError(response));
  }

  return (await response.json()) as SaveProjectResponse;
}

export { backendBaseUrl };
