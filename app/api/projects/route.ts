import {
  buildJsonResponse,
  forwardCloudRunRequest,
  jsonErrorResponse,
  requireAuthenticatedUser,
} from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const user = await requireAuthenticatedUser(request);
    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["projects"],
      user,
    });

    return buildJsonResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
