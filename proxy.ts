import { NextResponse, type NextRequest } from "next/server";

import { CSRF_COOKIE_NAME, PROTECTED_PATH_PREFIXES, SESSION_COOKIE_NAME } from "@/lib/auth/constants";
import { createCsrfToken, getCsrfCookieOptions } from "@/lib/server/auth/csrf";

function isProtectedPath(pathname: string) {
  return PROTECTED_PATH_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function isPublicAsset(pathname: string) {
  return (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/images") ||
    pathname.startsWith("/icons") ||
    pathname === "/robots.txt" ||
    pathname === "/sitemap.xml"
  );
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  if (isPublicAsset(pathname)) {
    return NextResponse.next();
  }

  const hasSession = Boolean(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  const hasCsrf = Boolean(request.cookies.get(CSRF_COOKIE_NAME)?.value);

  if (!hasSession && isProtectedPath(pathname)) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", `${pathname}${search}`);
    const response = NextResponse.redirect(loginUrl);
    if (!hasCsrf) {
      response.cookies.set(CSRF_COOKIE_NAME, createCsrfToken(), getCsrfCookieOptions());
    }
    return response;
  }

  if (hasSession && pathname === "/login") {
    return NextResponse.redirect(new URL("/new", request.url));
  }

  const response = NextResponse.next();
  if (!hasCsrf && request.method === "GET") {
    response.cookies.set(CSRF_COOKIE_NAME, createCsrfToken(), getCsrfCookieOptions());
  }

  return response;
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
  ],
};
