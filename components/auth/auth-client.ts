"use client";

import { signOut } from "firebase/auth";

import { getBrowserCsrfToken } from "@/lib/auth/browser";
import { getFirebaseClientAuth } from "@/lib/firebase/client";

type RouterLike = {
  push: (href: string) => void;
  refresh: () => void;
};

async function exchangeSession(idToken: string) {
  const csrfToken = getBrowserCsrfToken();
  const response = await fetch("/api/auth/session", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "x-csrf-token": csrfToken,
    },
    body: JSON.stringify({ idToken }),
  });

  if (!response.ok) {
    let message = "Unable to create the authenticated session.";
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload.error) {
        message = payload.error;
      }
    } catch {
      // Ignore parsing errors.
    }

    throw new Error(message);
  }
}

export async function finalizeBrowserSignIn({
  nextPath,
  router,
}: {
  nextPath: string;
  router: RouterLike;
}) {
  const auth = getFirebaseClientAuth();
  const user = auth.currentUser;

  if (!user) {
    throw new Error("We couldn't finish the sign-in flow. Please try again.");
  }

  const idToken = await user.getIdToken(true);
  await exchangeSession(idToken);
  await signOut(auth);
  router.push(nextPath);
  router.refresh();
}

function getFirebaseErrorCode(error: unknown) {
  const code =
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof error.code === "string"
      ? error.code
      : null;

  return code?.trim() ?? null;
}

type AuthErrorContext = "signin" | "signup" | "reset" | "google";

export function getFirebaseAuthErrorMessage(
  error: unknown,
  context: AuthErrorContext,
) {
  const code = getFirebaseErrorCode(error);

  switch (code) {
    case "auth/account-exists-with-different-credential":
      return "This email is already linked to a different sign-in method.";
    case "auth/email-already-in-use":
      return "An account with this email already exists. Sign in instead.";
    case "auth/invalid-credential":
    case "auth/user-not-found":
    case "auth/wrong-password":
      return "That email and password combination didn't match our records.";
    case "auth/invalid-email":
      return "Enter a valid email address.";
    case "auth/weak-password":
      return "Choose a password with at least 8 characters.";
    case "auth/missing-password":
      return "Enter your password to continue.";
    case "auth/missing-email":
      return "Enter your email address to continue.";
    case "auth/network-request-failed":
      return "Network error. Check your connection and try again.";
    case "auth/popup-blocked":
      return "Allow popups in your browser, then try Google sign-in again.";
    case "auth/popup-closed-by-user":
      return "Google sign-in was canceled before it finished.";
    case "auth/too-many-requests":
      return "Too many attempts. Please wait a moment and try again.";
    case "auth/user-disabled":
      return "This account has been disabled. Contact support if you need help.";
    default:
      break;
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  switch (context) {
    case "signup":
      return "We couldn't create your account right now. Please try again.";
    case "reset":
      return "We couldn't send the reset link right now. Please try again.";
    case "google":
      return "We couldn't start Google sign-in right now. Please try again.";
    default:
      return "We couldn't sign you in right now. Please try again.";
  }
}
