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
    id: string;
  }>;
};

export async function GET(request: Request, context: RouteContext) {
  try {
    const user = await requireAuthenticatedUser(request);
    const { id } = await context.params;
    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["project", id],
      user,
    });

    return buildJsonResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
