import { NextResponse } from "next/server";

import { CSRF_COOKIE_NAME, SESSION_COOKIE_NAME } from "@/lib/auth/constants";
import { createCsrfToken, getCsrfCookieOptions } from "@/lib/server/auth/csrf";
import { clearSessionCookieOptions } from "@/lib/server/auth/session";
import { jsonErrorResponse, requireCsrfProtection } from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    requireCsrfProtection(request);

    const response = NextResponse.json({ success: true });
    response.cookies.set(SESSION_COOKIE_NAME, "", clearSessionCookieOptions());
    response.cookies.set(CSRF_COOKIE_NAME, createCsrfToken(), getCsrfCookieOptions());
    response.headers.set("Cache-Control", "no-store");
    return response;
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
