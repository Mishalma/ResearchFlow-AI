export type BackendHealthResponse = {
  status: string;
  message: string;
};

const backendBaseUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export const backendHealthEndpoint = `${backendBaseUrl}/health`;

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
    throw new Error(
      `Health check failed with status ${response.status} ${response.statusText}`.trim(),
    );
  }

  return (await response.json()) as BackendHealthResponse;
}
