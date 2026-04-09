import "server-only";

import { randomBytes } from "node:crypto";

import { CSRF_COOKIE_NAME, CSRF_HEADER_NAME } from "@/lib/auth/constants";

function parseCookieValue(cookieHeader: string | null, name: string) {
  if (!cookieHeader) {
    return null;
  }

  const pairs = cookieHeader.split(/;\s*/);
  for (const pair of pairs) {
    const separatorIndex = pair.indexOf("=");
    if (separatorIndex <= 0) {
      continue;
    }

    const key = decodeURIComponent(pair.slice(0, separatorIndex));
    if (key !== name) {
      continue;
    }

    return decodeURIComponent(pair.slice(separatorIndex + 1));
  }

  return null;
}

export function createCsrfToken() {
  return randomBytes(32).toString("hex");
}

export function getCsrfTokenFromRequest(request: Request) {
  return parseCookieValue(request.headers.get("cookie"), CSRF_COOKIE_NAME);
}

export function getCsrfHeaderValue(request: Request) {
  return request.headers.get(CSRF_HEADER_NAME);
}

export function assertSameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) {
    return;
  }

  const originUrl = new URL(origin);
  const host =
    request.headers.get("x-forwarded-host") ?? request.headers.get("host");

  if (!host || originUrl.host !== host) {
    throw new Error("Cross-site requests are not allowed.");
  }
}

export function assertValidCsrf(request: Request) {
  assertSameOrigin(request);

  const cookieToken = getCsrfTokenFromRequest(request);
  const headerToken = getCsrfHeaderValue(request);

  if (!cookieToken || !headerToken || cookieToken !== headerToken) {
    throw new Error("The request is missing a valid CSRF token.");
  }
}

export function getCsrfCookieOptions() {
  return {
    httpOnly: false,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: 60 * 60 * 24,
  };
}
