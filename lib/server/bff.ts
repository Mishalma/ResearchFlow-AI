import "server-only";

import { createHash } from "node:crypto";

import { ZodError, type ZodType } from "zod";

import {
  SESSION_COOKIE_NAME,
  USER_EMAIL_HEADER,
  USER_ID_HEADER,
  USER_NAME_HEADER,
} from "@/lib/auth/constants";
import { assertValidCsrf } from "@/lib/server/auth/csrf";
import {
  type AuthenticatedUser,
  verifySessionCookie,
} from "@/lib/server/auth/session";
import { getCloudRunIdToken } from "@/lib/server/gcp-auth";
import {
  acquireDistributedLock,
  enforceRateLimit,
  releaseDistributedLock,
} from "@/lib/server/security/rate-limit";

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
  "cookie",
  "host",
  "origin",
  "referer",
  "x-csrf-token",
  "x-serverless-authorization",
  "x-paper-easy-user-id",
  "x-paper-easy-user-email",
  "x-paper-easy-user-name",
]);

const responseHeadersToDrop = new Set([...hopByHopHeaders, "content-length"]);

export class ApiRouteError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function parseCookieValue(cookieHeader: string | null, name: string) {
  if (!cookieHeader) {
    return null;
  }

  const cookies = cookieHeader.split(/;\s*/);
  for (const cookie of cookies) {
    const separatorIndex = cookie.indexOf("=");
    if (separatorIndex <= 0) {
      continue;
    }

    const key = decodeURIComponent(cookie.slice(0, separatorIndex));
    if (key !== name) {
      continue;
    }

    return decodeURIComponent(cookie.slice(separatorIndex + 1));
  }

  return null;
}

function getCloudRunServiceUrl() {
  const value = process.env.CLOUD_RUN_SERVICE_URL?.trim();

  if (!value) {
    throw new ApiRouteError(
      500,
      "The server proxy is missing its Cloud Run configuration.",
    );
  }

  return new URL(value);
}

function getTargetAudience(serviceUrl: URL) {
  return process.env.CLOUD_RUN_ID_TOKEN_AUDIENCE?.trim() || serviceUrl.origin;
}

function buildTargetUrl(serviceUrl: URL, pathSegments: string[], search = "") {
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
    if (requestHeadersToDrop.has(key.toLowerCase())) {
      continue;
    }
    filtered.set(key, value);
  }

  return filtered;
}

function filterResponseHeaders(source: Headers) {
  const filtered = new Headers();

  for (const [key, value] of source.entries()) {
    if (responseHeadersToDrop.has(key.toLowerCase())) {
      continue;
    }
    filtered.set(key, value);
  }

  return filtered;
}

function normalizeProxyError(error: unknown): ApiRouteError {
  const message = error instanceof Error ? error.message : "Unexpected proxy failure.";

  if (/missing cloud_run_service_url/i.test(message)) {
    return new ApiRouteError(
      500,
      "The server proxy is missing its Cloud Run configuration.",
    );
  }

  if (/default credentials|application default credentials|google authentication/i.test(message)) {
    return new ApiRouteError(
      500,
      "Google Cloud authentication is not configured for the server proxy.",
    );
  }

  if (/permission|forbidden|invoker|unauthorized|401|403/i.test(message)) {
    return new ApiRouteError(
      502,
      "The server proxy could not authenticate with the private Cloud Run service.",
    );
  }

  return new ApiRouteError(
    502,
    "The server proxy could not reach the private Cloud Run service.",
  );
}

function getClientIp(request: Request) {
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) {
    return forwardedFor.split(",")[0]?.trim() || "unknown";
  }

  return request.headers.get("x-real-ip")?.trim() || "unknown";
}

function hashIp(ip: string) {
  return createHash("sha256").update(ip).digest("hex").slice(0, 24);
}

export function getRateLimitIdentity(request: Request, user?: AuthenticatedUser | null) {
  const ipHash = hashIp(getClientIp(request));
  return {
    ipKey: ipHash,
    userKey: user?.uid ? `user:${user.uid}` : `ip:${ipHash}`,
  };
}

export async function enforceNamedRateLimit(
  key: string,
  limit: number,
  windowSeconds: number,
) {
  const result = await enforceRateLimit({ key, limit, windowSeconds });
  if (!result.allowed) {
    throw new ApiRouteError(
      429,
      `Rate limit exceeded. Retry in ${result.retryAfterSeconds} seconds.`,
    );
  }

  return result;
}

export async function withGenerationLock<T>(userId: string, task: () => Promise<T>) {
  const lockKey = `lock:generate:${userId}`;
  const acquired = await acquireDistributedLock(lockKey, 60 * 10);
  if (!acquired) {
    throw new ApiRouteError(
      429,
      "A generation request is already in progress for this account.",
    );
  }

  try {
    return await task();
  } finally {
    await releaseDistributedLock(lockKey);
  }
}

export async function parseJsonBody<T>(request: Request, schema: ZodType<T>) {
  let payload: unknown;

  try {
    payload = await request.json();
  } catch {
    throw new ApiRouteError(400, "Invalid JSON request body.");
  }

  try {
    return schema.parse(payload);
  } catch (error) {
    if (error instanceof ZodError) {
      const issue = error.issues[0];
      throw new ApiRouteError(422, issue?.message ?? "Invalid request payload.");
    }

    throw error;
  }
}

export async function requireAuthenticatedUser(request: Request) {
  const sessionCookie = parseCookieValue(
    request.headers.get("cookie"),
    SESSION_COOKIE_NAME,
  );
  const user = await verifySessionCookie(sessionCookie);

  if (!user || !user.email) {
    throw new ApiRouteError(401, "Authentication is required.");
  }

  return user;
}

export function requireCsrfProtection(request: Request) {
  try {
    assertValidCsrf(request);
  } catch (error) {
    const message = error instanceof Error ? error.message : "CSRF validation failed.";
    throw new ApiRouteError(403, message);
  }
}

function ensureCloudRunAuthHeader(headers: Headers, idToken: string) {
  headers.set("X-Serverless-Authorization", `Bearer ${idToken}`);
}

function attachTrustedUserHeaders(headers: Headers, user: AuthenticatedUser) {
  headers.set(USER_ID_HEADER, user.uid);
  headers.set(USER_EMAIL_HEADER, user.email);
  headers.set(USER_NAME_HEADER, user.name);
}

export async function forwardCloudRunRequest(options: {
  request: Request;
  pathSegments: string[];
  user?: AuthenticatedUser;
  body?: BodyInit;
  headers?: HeadersInit;
  search?: string;
}) {
  let targetUrl: URL | null = null;

  try {
    const serviceUrl = getCloudRunServiceUrl();
    const targetAudience = getTargetAudience(serviceUrl);
    targetUrl = buildTargetUrl(
      serviceUrl,
      options.pathSegments,
      options.search ?? new URL(options.request.url).search,
    );

    const outboundHeaders = filterRequestHeaders(options.request.headers);
    const idToken = await getCloudRunIdToken(targetAudience);
    ensureCloudRunAuthHeader(outboundHeaders, idToken);

    if (options.user) {
      attachTrustedUserHeaders(outboundHeaders, options.user);
    }

    if (options.headers) {
      const extraHeaders = new Headers(options.headers);
      for (const [key, value] of extraHeaders.entries()) {
        outboundHeaders.set(key, value);
      }
    }

    const upstreamResponse = await fetch(targetUrl, {
      method: options.request.method,
      headers: outboundHeaders,
      body: options.body,
      cache: "no-store",
      redirect: "manual",
    });

    return upstreamResponse;
  } catch (error) {
    const normalized = normalizeProxyError(error);
    console.error("Cloud Run proxy request failed.", {
      method: options.request.method,
      targetUrl: targetUrl?.toString() ?? "unresolved",
      error: error instanceof Error ? error.message : "Unknown error",
    });
    throw normalized;
  }
}

export async function buildJsonResponse(upstreamResponse: Response) {
  const contentType = upstreamResponse.headers.get("content-type") ?? "";
  const headers = filterResponseHeaders(upstreamResponse.headers);

  if (!contentType.includes("application/json")) {
    const text = await upstreamResponse.text();
    return Response.json(
      {
        error:
          text.trim() ||
          `Upstream request failed with status ${upstreamResponse.status}.`,
      },
      { status: upstreamResponse.status, headers },
    );
  }

  const payload = await upstreamResponse.json();
  return Response.json(payload, {
    status: upstreamResponse.status,
    headers,
  });
}

export async function buildBinaryResponse(upstreamResponse: Response) {
  const headers = filterResponseHeaders(upstreamResponse.headers);
  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers,
  });
}

export function jsonErrorResponse(error: unknown) {
  if (error instanceof ApiRouteError) {
    return Response.json({ error: error.message }, { status: error.status });
  }

  console.error("Unhandled API route error.", error);
  return Response.json(
    { error: "Internal server error." },
    { status: 500 },
  );
}
