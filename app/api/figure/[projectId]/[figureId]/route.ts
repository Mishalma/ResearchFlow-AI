import {
  buildBinaryResponse,
  forwardCloudRunRequest,
  jsonErrorResponse,
  requireAuthenticatedUser,
} from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{
    projectId: string;
    figureId: string;
  }>;
};

export async function GET(request: Request, context: RouteContext) {
  try {
    const user = await requireAuthenticatedUser(request);
    const { projectId, figureId } = await context.params;
    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["figure", projectId, figureId],
      user,
    });

    return buildBinaryResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
