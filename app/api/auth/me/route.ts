import { NextResponse } from "next/server";

import { CSRF_COOKIE_NAME } from "@/lib/auth/constants";
import { createCsrfToken, getCsrfCookieOptions } from "@/lib/server/auth/csrf";
import { getServerSessionUser } from "@/lib/server/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const user = await getServerSessionUser();
  const csrfToken = createCsrfToken();

  const response = NextResponse.json({ user, csrfToken });
  response.headers.set("Cache-Control", "no-store");
  response.headers.set("Vary", "Cookie");
  response.cookies.set(CSRF_COOKIE_NAME, csrfToken, getCsrfCookieOptions());
  return response;
}
