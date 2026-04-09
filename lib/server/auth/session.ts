import "server-only";

import { cookies } from "next/headers";
import type { DecodedIdToken } from "firebase-admin/auth";

import {
  RECENT_SIGN_IN_WINDOW_SECONDS,
  SESSION_COOKIE_NAME,
  SESSION_MAX_AGE_MS,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/auth/constants";
import { getFirebaseAdminAuth } from "@/lib/server/firebase-admin";

export type AuthenticatedUser = {
  uid: string;
  email: string;
  name: string;
  imageUrl: string | null;
  emailVerified: boolean;
};

function getSignInProvider(token: DecodedIdToken) {
  return token.firebase?.sign_in_provider ?? "unknown";
}

function mapDecodedTokenToUser(token: DecodedIdToken): AuthenticatedUser {
  return {
    uid: token.uid,
    email: token.email ?? "",
    name: token.name ?? token.email ?? "PaperEasy User",
    imageUrl: token.picture ?? null,
    emailVerified: token.email_verified ?? false,
  };
}

function assertRecentSignIn(token: DecodedIdToken) {
  if (!token.auth_time) {
    throw new Error("Recent sign-in is required to start a session.");
  }

  const ageSeconds = Math.floor(Date.now() / 1000) - token.auth_time;
  if (ageSeconds > RECENT_SIGN_IN_WINDOW_SECONDS) {
    throw new Error("Please sign in again before continuing.");
  }
}

function assertVerifiedEmailWhenRequired(token: DecodedIdToken) {
  const provider = getSignInProvider(token);
  if (provider === "password" && !token.email_verified) {
    throw new Error("Verify your email address before accessing PaperEasy.");
  }
}

export async function createSessionFromIdToken(idToken: string) {
  const auth = await getFirebaseAdminAuth();
  const decodedToken = await auth.verifyIdToken(idToken, true);

  assertRecentSignIn(decodedToken);
  assertVerifiedEmailWhenRequired(decodedToken);

  const sessionCookie = await auth.createSessionCookie(idToken, {
    expiresIn: SESSION_MAX_AGE_MS,
  });

  return {
    sessionCookie,
    user: mapDecodedTokenToUser(decodedToken),
  };
}

export async function verifySessionCookie(sessionCookie: string | null | undefined) {
  if (!sessionCookie) {
    return null;
  }

  try {
    const auth = await getFirebaseAdminAuth();
    const decodedToken = await auth.verifySessionCookie(sessionCookie, true);
    return mapDecodedTokenToUser(decodedToken);
  } catch {
    return null;
  }
}

export async function getServerSessionUser() {
  const cookieStore = await cookies();
  return verifySessionCookie(cookieStore.get(SESSION_COOKIE_NAME)?.value);
}

export function getSessionCookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  };
}

export function clearSessionCookieOptions() {
  return {
    ...getSessionCookieOptions(),
    maxAge: 0,
  };
}
