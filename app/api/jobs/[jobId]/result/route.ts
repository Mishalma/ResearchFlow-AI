import {
  buildJsonResponse,
  forwardCloudRunRequest,
  jsonErrorResponse,
  requireAuthenticatedUser,
} from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{
    jobId: string;
  }>;
};

export async function GET(request: Request, context: RouteContext) {
  try {
    const user = await requireAuthenticatedUser(request);
    const { jobId } = await context.params;
    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["jobs", jobId, "result"],
      user,
    });

    return buildJsonResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
