import "server-only";

import { GoogleAuth } from "google-auth-library";

const auth = new GoogleAuth();

const hopByHopHeaders = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

const requestHeadersToDrop = new Set([
  ...hopByHopHeaders,
  "authorization",
  "content-length",
  "host",
  "x-serverless-authorization",
]);

const responseHeadersToDrop = new Set([
  ...hopByHopHeaders,
  "content-length",
]);

type ProxyError = {
  status: number;
  error: string;
};

function getCloudRunServiceUrl() {
  const value = process.env.CLOUD_RUN_SERVICE_URL?.trim();

  if (!value) {
    throw new Error(
      "Missing CLOUD_RUN_SERVICE_URL. Set the private Cloud Run base URL for the server-side proxy.",
    );
  }

  return new URL(value);
}

function getTargetAudience(serviceUrl: URL) {
  return process.env.CLOUD_RUN_ID_TOKEN_AUDIENCE?.trim() || serviceUrl.origin;
}

function buildTargetUrl(serviceUrl: URL, pathSegments: string[], search: string) {
  const targetUrl = new URL(serviceUrl.toString());
  const basePath = targetUrl.pathname.replace(/\/+$/, "");
  const encodedPath = pathSegments.map(encodeURIComponent).join("/");

  targetUrl.pathname = [basePath, encodedPath].filter(Boolean).join("/") || "/";
  targetUrl.search = search;

  return targetUrl;
}

function filterRequestHeaders(source: Headers) {
  const filtered = new Headers();

  for (const [key, value] of source.entries()) {
    const normalizedKey = key.toLowerCase();
    if (requestHeadersToDrop.has(normalizedKey)) {
      continue;
    }

    filtered.set(key, value);
  }

  return filtered;
}

function filterResponseHeaders(source: Headers) {
  const filtered = new Headers();

  for (const [key, value] of source.entries()) {
    const normalizedKey = key.toLowerCase();
    if (responseHeadersToDrop.has(normalizedKey)) {
      continue;
    }

    filtered.set(key, value);
  }

  return filtered;
}

function hasRequestBody(method: string) {
  return method !== "GET" && method !== "HEAD";
}

function normalizeProxyError(error: unknown): ProxyError {
  const message =
    error instanceof Error ? error.message : "Unexpected proxy failure.";

  if (
    /cloud_run_service_url|missing cloud_run_service_url/i.test(message)
  ) {
    return {
      status: 500,
      error: "The server proxy is missing its Cloud Run configuration.",
    };
  }

  if (
    /default credentials|application default credentials|google_application_credentials|does not exist, or it is not a file|enoent/i.test(
      message,
    )
  ) {
    return {
      status: 500,
      error: "Google Cloud authentication is not configured for the server proxy.",
    };
  }

  if (/permission|forbidden|invoker|403/i.test(message)) {
    return {
      status: 502,
      error: "The server proxy is not authorized to invoke the private Cloud Run service.",
    };
  }

  return {
    status: 502,
    error: "The server proxy could not reach the private Cloud Run service.",
  };
}

async function getCloudRunAuthHeaders(targetAudience: string, targetUrl: string) {
  const client = await auth.getIdTokenClient(targetAudience);
  const headers = await client.getRequestHeaders(targetUrl);

  return new Headers(headers);
}

async function buildRequestBody(request: Request) {
  if (!hasRequestBody(request.method)) {
    return undefined;
  }

  const body = await request.arrayBuffer();
  return body.byteLength > 0 ? body : undefined;
}

async function buildProxyResponse(targetUrl: URL, upstreamResponse: Response) {
  const headers = filterResponseHeaders(upstreamResponse.headers);
  const contentType = upstreamResponse.headers.get("content-type") ?? "";

  if (
    (upstreamResponse.status === 401 || upstreamResponse.status === 403) &&
    !contentType.includes("application/json")
  ) {
    console.error("Cloud Run proxy received an authorization response.", {
      targetUrl: targetUrl.toString(),
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
    });

    return Response.json(
      {
        error:
          "The server proxy could not authenticate with the private Cloud Run service.",
      },
      { status: 502 },
    );
  }

  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers,
  });
}

export async function proxyCloudRunRequest(
  request: Request,
  pathSegments: string[],
) {
  let targetUrl: URL | null = null;

  try {
    const serviceUrl = getCloudRunServiceUrl();
    const targetAudience = getTargetAudience(serviceUrl);

    targetUrl = buildTargetUrl(
      serviceUrl,
      pathSegments,
      new URL(request.url).search,
    );

    const outboundHeaders = filterRequestHeaders(request.headers);
    const authHeaders = await getCloudRunAuthHeaders(
      targetAudience,
      targetUrl.toString(),
    );
    const idTokenHeader =
      authHeaders.get("authorization") ?? authHeaders.get("Authorization");

    if (!idTokenHeader) {
      throw new Error(
        "Google authentication did not return an Authorization header for Cloud Run.",
      );
    }

    // Use the serverless header so any app-level Authorization header can stay separate.
    outboundHeaders.set("X-Serverless-Authorization", idTokenHeader);

    const requestBody = await buildRequestBody(request);
    const upstreamResponse = await fetch(targetUrl, {
      method: request.method,
      headers: outboundHeaders,
      body: requestBody,
      cache: "no-store",
      redirect: "manual",
    });

    return buildProxyResponse(targetUrl, upstreamResponse);
  } catch (error) {
    const proxyError = normalizeProxyError(error);

    console.error("Cloud Run proxy request failed.", {
      method: request.method,
      targetUrl: targetUrl?.toString() ?? "unresolved",
      error: error instanceof Error ? error.message : "Unknown error",
    });

    return Response.json(
      {
        error: proxyError.error,
      },
      { status: proxyError.status },
    );
  }
}
