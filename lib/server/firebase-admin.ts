import "server-only";

import { getApp, getApps, initializeApp, cert } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import type { Credential, GoogleOAuthAccessToken, ServiceAccount } from "firebase-admin/app";

import { getGoogleAccessClient, getGoogleProjectId } from "@/lib/server/gcp-auth";

class DelegatedGoogleCredential implements Credential {
  async getAccessToken(): Promise<GoogleOAuthAccessToken> {
    const client = await getGoogleAccessClient();
    const tokenResult = await client.getAccessToken();
    const accessToken =
      typeof tokenResult === "string" ? tokenResult : tokenResult?.token;

    if (!accessToken) {
      throw new Error("Google authentication did not return an access token.");
    }

    const expiryDate =
      "credentials" in client && client.credentials?.expiry_date
        ? client.credentials.expiry_date
        : undefined;
    const expiresIn = expiryDate
      ? Math.max(0, Math.floor((expiryDate - Date.now()) / 1000))
      : 3600;

    return {
      access_token: accessToken,
      expires_in: expiresIn,
    };
  }
}

function getServiceAccountFromEnv(): ServiceAccount | null {
  const projectId =
    process.env.FIREBASE_PROJECT_ID?.trim() ||
    process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID?.trim() ||
    "";
  const clientEmail = process.env.FIREBASE_ADMIN_CLIENT_EMAIL?.trim() ?? "";
  const privateKey =
    process.env.FIREBASE_ADMIN_PRIVATE_KEY?.replace(/\\n/g, "\n") ?? "";

  if (!projectId || !clientEmail || !privateKey) {
    return null;
  }

  return {
    projectId,
    clientEmail,
    privateKey,
  };
}

async function getFirebaseProjectId() {
  return (
    process.env.FIREBASE_PROJECT_ID?.trim() ||
    process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID?.trim() ||
    (await getGoogleProjectId()) ||
    ""
  );
}

export async function getFirebaseAdminApp() {
  if (getApps().length > 0) {
    return getApp();
  }

  const projectId = await getFirebaseProjectId();
  if (!projectId) {
    throw new Error(
      "Missing Firebase project configuration. Set FIREBASE_PROJECT_ID or NEXT_PUBLIC_FIREBASE_PROJECT_ID.",
    );
  }

  const serviceAccount = getServiceAccountFromEnv();
  const credential = serviceAccount
    ? cert(serviceAccount)
    : new DelegatedGoogleCredential();

  return initializeApp({
    credential,
    projectId,
  });
}

export async function getFirebaseAdminAuth() {
  const app = await getFirebaseAdminApp();
  return getAuth(app);
}
