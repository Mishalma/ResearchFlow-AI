import "server-only";

import { GoogleAuth, ExternalAccountClient, Impersonated, type AuthClient } from "google-auth-library";
import { getVercelOidcToken } from "@vercel/oidc";

const CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform";
const googleAuth = new GoogleAuth({ scopes: [CLOUD_PLATFORM_SCOPE] });

type IdentityClientBundle = {
  accessClient: AuthClient;
  idTokenProvider: { fetchIdToken(targetAudience: string): Promise<string> };
};

let cachedIdentityBundlePromise: Promise<IdentityClientBundle> | null = null;

function hasVercelWifConfig() {
  return Boolean(
    process.env.GCP_PROJECT_NUMBER?.trim() &&
      process.env.GCP_WORKLOAD_IDENTITY_POOL_ID?.trim() &&
      process.env.GCP_WORKLOAD_IDENTITY_POOL_PROVIDER_ID?.trim() &&
      process.env.GCP_SERVICE_ACCOUNT_EMAIL?.trim(),
  );
}

async function createVercelIdentityBundle(): Promise<IdentityClientBundle> {
  const projectNumber = process.env.GCP_PROJECT_NUMBER?.trim();
  const poolId = process.env.GCP_WORKLOAD_IDENTITY_POOL_ID?.trim();
  const providerId = process.env.GCP_WORKLOAD_IDENTITY_POOL_PROVIDER_ID?.trim();
  const serviceAccountEmail = process.env.GCP_SERVICE_ACCOUNT_EMAIL?.trim();

  if (!projectNumber || !poolId || !providerId || !serviceAccountEmail) {
    throw new Error(
      "Missing GCP workload identity configuration for the server proxy.",
    );
  }

  const sourceClient = ExternalAccountClient.fromJSON({
    type: "external_account",
    audience: `//iam.googleapis.com/projects/${projectNumber}/locations/global/workloadIdentityPools/${poolId}/providers/${providerId}`,
    subject_token_type: "urn:ietf:params:oauth:token-type:jwt",
    token_url: "https://sts.googleapis.com/v1/token",
    subject_token_supplier: {
      getSubjectToken: async () => getVercelOidcToken(),
    },
  });

  if (!sourceClient) {
    throw new Error("Unable to create the Vercel workload identity client.");
  }

  const impersonatedClient = new Impersonated({
    sourceClient,
    targetPrincipal: serviceAccountEmail,
    targetScopes: [CLOUD_PLATFORM_SCOPE],
    lifetime: 3600,
  });

  return {
    accessClient: impersonatedClient,
    idTokenProvider: impersonatedClient,
  };
}

async function createLocalIdentityBundle(): Promise<IdentityClientBundle> {
  const accessClient = await googleAuth.getClient();

  if (!("fetchIdToken" in accessClient) || typeof accessClient.fetchIdToken !== "function") {
    throw new Error(
      "The current Google credentials cannot mint ID tokens for private Cloud Run.",
    );
  }

  return {
    accessClient,
    idTokenProvider: accessClient,
  };
}

async function createIdentityBundle(): Promise<IdentityClientBundle> {
  if (hasVercelWifConfig()) {
    return createVercelIdentityBundle();
  }

  return createLocalIdentityBundle();
}

async function getIdentityBundle() {
  if (!cachedIdentityBundlePromise) {
    cachedIdentityBundlePromise = createIdentityBundle();
  }

  return cachedIdentityBundlePromise;
}

export async function getGoogleAccessClient() {
  const bundle = await getIdentityBundle();
  return bundle.accessClient;
}

export async function getCloudRunIdToken(targetAudience: string) {
  const bundle = await getIdentityBundle();
  return bundle.idTokenProvider.fetchIdToken(targetAudience);
}

export async function getGoogleProjectId() {
  return (
    process.env.GCP_PROJECT_ID?.trim() ||
    process.env.GOOGLE_CLOUD_PROJECT?.trim() ||
    (await googleAuth.getProjectId()) ||
    process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID?.trim() ||
    ""
  );
}
