import { NextResponse } from "next/server";
import { z } from "zod";

import { SESSION_COOKIE_NAME } from "@/lib/auth/constants";
import { createSessionFromIdToken, getSessionCookieOptions } from "@/lib/server/auth/session";
import {
  enforceNamedRateLimit,
  getRateLimitIdentity,
  jsonErrorResponse,
  parseJsonBody,
  requireCsrfProtection,
} from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SessionRequestSchema = z.object({
  idToken: z.string().min(1, "Firebase ID token is required."),
});

export async function POST(request: Request) {
  try {
    requireCsrfProtection(request);

    const { ipKey } = getRateLimitIdentity(request, null);
    await enforceNamedRateLimit(`rate:auth-session:${ipKey}`, 10, 60);

    const payload = await parseJsonBody(request, SessionRequestSchema);
    const session = await createSessionFromIdToken(payload.idToken);

    const response = NextResponse.json({ user: session.user });
    response.headers.set("Cache-Control", "no-store");
    response.headers.set("Vary", "Cookie");
    response.cookies.set(
      SESSION_COOKIE_NAME,
      session.sessionCookie,
      getSessionCookieOptions(),
    );
    return response;
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
