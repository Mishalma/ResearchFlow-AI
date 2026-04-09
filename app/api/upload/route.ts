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

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const allowedTypes = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);
const allowedExtensions = new Set(["pdf", "docx"]);

export async function POST(request: Request) {
  try {
    requireCsrfProtection(request);
    const user = await requireAuthenticatedUser(request);
    const { userKey, ipKey } = getRateLimitIdentity(request, user);
    await enforceNamedRateLimit(`rate:upload:${userKey}`, 20, 60 * 60);
    await enforceNamedRateLimit(`rate:upload-ip:${ipKey}`, 60, 60 * 60);

    const formData = await request.formData();
    const file = formData.get("file");

    if (!(file instanceof File)) {
      throw new ApiRouteError(400, "A PDF or DOCX file is required.");
    }

    const extension = file.name.split(".").pop()?.trim().toLowerCase() ?? "";

    if (!allowedTypes.has(file.type) && !allowedExtensions.has(extension)) {
      throw new ApiRouteError(
        415,
        "Unsupported file type. Only PDF and DOCX files are allowed.",
      );
    }

    if (file.size <= 0) {
      throw new ApiRouteError(400, "Uploaded file is empty.");
    }

    if (file.size > MAX_UPLOAD_BYTES) {
      throw new ApiRouteError(413, "File is too large. Maximum allowed size is 10MB.");
    }

    const upstreamFormData = new FormData();
    upstreamFormData.append("file", file);

    const upstreamResponse = await forwardCloudRunRequest({
      request,
      pathSegments: ["upload"],
      user,
      body: upstreamFormData,
    });

    return buildJsonResponse(upstreamResponse);
  } catch (error) {
    return jsonErrorResponse(error);
  }
}
