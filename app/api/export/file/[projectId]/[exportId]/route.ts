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
    exportId: string;
  }>;
};

export async function GET(request: Request, context: RouteContext) {
  try {
    const user = await requireAuthenticatedUser(request);
    const { projectId, exportId } = await context.params;
    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["export", projectId, exportId],
      user,
    });

    return buildBinaryResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
