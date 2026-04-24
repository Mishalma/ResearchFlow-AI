import { z } from "zod";

import {
  buildJsonResponse,
  enforceNamedRateLimit,
  forwardCloudRunRequest,
  getRateLimitIdentity,
  jsonErrorResponse,
  parseJsonBody,
  requireAuthenticatedUser,
  requireCsrfProtection,
  withGenerationLock,
} from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const CreateJobRequestSchema = z.object({
  project_id: z.string().min(1, "Project ID is required."),
  config: z
    .object({
      validation_depth: z.literal("standard").optional(),
      enable_fix_loop: z.boolean().optional(),
      max_iterations: z.number().int().min(1).max(5).optional(),
    })
    .optional(),
});

export async function POST(request: Request) {
  try {
    requireCsrfProtection(request);
    const user = await requireAuthenticatedUser(request);
    const { userKey, ipKey } = getRateLimitIdentity(request, user);
    await enforceNamedRateLimit(`rate:jobs:${userKey}`, 10, 60 * 60);
    await enforceNamedRateLimit(`rate:jobs-ip:${ipKey}`, 30, 60 * 60);

    const payload = await parseJsonBody(request, CreateJobRequestSchema);
    return withGenerationLock(user.uid, async () => {
      const upstreamResponse = await forwardCloudRunRequest({
        request,
        pathSegments: ["jobs"],
        user,
        body: JSON.stringify(payload),
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
      });

      return buildJsonResponse(upstreamResponse);
    });
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
