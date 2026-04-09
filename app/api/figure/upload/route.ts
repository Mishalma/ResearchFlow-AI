import {
  ApiRouteError,
  buildJsonResponse,
  enforceNamedRateLimit,
  forwardCloudRunRequest,
  getRateLimitIdentity,
  jsonErrorResponse,
  requireAuthenticatedUser,
  requireCsrfProtection,
} from "@/lib/server/bff";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_FIGURE_BYTES = 10 * 1024 * 1024;
const allowedImageTypes = new Set(["image/png", "image/jpeg"]);

export async function POST(request: Request) {
  try {
    requireCsrfProtection(request);
    const user = await requireAuthenticatedUser(request);
    const { userKey } = getRateLimitIdentity(request, user);
    await enforceNamedRateLimit(`rate:figure-upload:${userKey}`, 30, 60 * 60);

    const formData = await request.formData();
    const projectId = formData.get("project_id");
    const caption = formData.get("caption");
    const section = formData.get("section");
    const file = formData.get("file");

    if (typeof projectId !== "string" || !projectId.trim()) {
      throw new ApiRouteError(400, "Project ID is required.");
    }

    if (typeof caption !== "string" || !caption.trim()) {
      throw new ApiRouteError(400, "Figure caption is required.");
    }

    if (typeof section !== "string" || !section.trim()) {
      throw new ApiRouteError(400, "Figure section is required.");
    }

    if (!(file instanceof File)) {
      throw new ApiRouteError(400, "A PNG or JPG image is required.");
    }

    if (!allowedImageTypes.has(file.type)) {
      throw new ApiRouteError(415, "Unsupported image type. Only PNG and JPG files are allowed.");
    }

    if (file.size <= 0) {
      throw new ApiRouteError(400, "Uploaded figure is empty.");
    }

    if (file.size > MAX_FIGURE_BYTES) {
      throw new ApiRouteError(413, "Figure is too large. Maximum allowed size is 10MB.");
    }

    const upstreamFormData = new FormData();
    upstreamFormData.append("project_id", projectId);
    upstreamFormData.append("caption", caption);
    upstreamFormData.append("section", section);
    upstreamFormData.append("file", file);

    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["figure", "upload"],
      user,
      body: upstreamFormData,
    });

    return buildJsonResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
