export const DEFAULT_AUTH_REDIRECT_PATH = "/new";

export type AuthPageSearchParams = Promise<{
  next?: string | string[];
}>;

export function getSingleSearchParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }

  return value ?? null;
}

export function sanitizeNextPath(
  value: string | null | undefined,
  fallback = DEFAULT_AUTH_REDIRECT_PATH,
) {
  const nextPath = value?.trim();
  return nextPath && nextPath.startsWith("/") ? nextPath : fallback;
}

export function resolveNextPath(
  value: string | string[] | undefined,
  fallback = DEFAULT_AUTH_REDIRECT_PATH,
) {
  return sanitizeNextPath(getSingleSearchParam(value), fallback);
}

export function buildAuthHref(path: string, nextPath: string | null | undefined) {
  const safeNextPath = sanitizeNextPath(nextPath);
  if (safeNextPath === DEFAULT_AUTH_REDIRECT_PATH) {
    return path;
  }

  return `${path}?next=${encodeURIComponent(safeNextPath)}`;
}
