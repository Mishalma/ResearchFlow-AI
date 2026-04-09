import { z } from "zod";

import {
  buildBinaryResponse,
  enforceNamedRateLimit,
  forwardCloudRunRequest,
  getRateLimitIdentity,
  jsonErrorResponse,
  parseJsonBody,
  requireAuthenticatedUser,
  requireCsrfProtection,
} from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ExportRequestSchema = z.object({
  project_id: z.string().min(1, "Project ID is required."),
});

export async function POST(request: Request) {
  try {
    requireCsrfProtection(request);
    const user = await requireAuthenticatedUser(request);
    const { userKey } = getRateLimitIdentity(request, user);
    await enforceNamedRateLimit(`rate:export:${userKey}`, 20, 60 * 60);

    const payload = await parseJsonBody(request, ExportRequestSchema);
    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["export", "latex"],
      user,
      body: JSON.stringify(payload),
      headers: {
        Accept: "application/octet-stream, application/x-tex, application/json",
        "Content-Type": "application/json",
      },
    });

    return buildBinaryResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
