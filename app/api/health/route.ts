import {
  buildJsonResponse,
  forwardCloudRunRequest,
  jsonErrorResponse,
} from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["health"],
    });

    return buildJsonResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
