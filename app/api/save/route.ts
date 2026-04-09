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
} from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SaveRequestSchema = z.object({
  project_id: z.string().min(1).optional(),
  title: z.string().min(1, "Project title is required.").max(300),
  authors: z.array(z.string().trim()).optional(),
  keywords: z.array(z.string().trim()).optional(),
  content: z.string().trim().optional(),
  paper: z
    .object({
      title: z.string(),
      abstract: z.string(),
      keywords: z.array(z.string()),
      sections: z.object({
        introduction: z.string(),
        related_work: z.string(),
        methodology: z.string(),
        results: z.string(),
        discussion: z.string(),
        conclusion: z.string(),
      }),
      references: z.array(z.string()),
    })
    .optional(),
}).refine((payload) => Boolean(payload.content || payload.paper), {
  message: "Project content is required.",
});

export async function POST(request: Request) {
  try {
    requireCsrfProtection(request);
    const user = await requireAuthenticatedUser(request);
    const { userKey } = getRateLimitIdentity(request, user);
    await enforceNamedRateLimit(`rate:save:${userKey}`, 120, 60);

    const payload = await parseJsonBody(request, SaveRequestSchema);
    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["save"],
      user,
      body: JSON.stringify(payload),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
    });

    return buildJsonResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
