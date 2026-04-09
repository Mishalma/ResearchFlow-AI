export const SESSION_COOKIE_NAME = "__session";
export const CSRF_COOKIE_NAME = "paper_csrf";
export const CSRF_HEADER_NAME = "x-csrf-token";

export const USER_ID_HEADER = "X-PaperEasy-User-Id";
export const USER_EMAIL_HEADER = "X-PaperEasy-User-Email";
export const USER_NAME_HEADER = "X-PaperEasy-User-Name";

export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 5;
export const SESSION_MAX_AGE_MS = SESSION_MAX_AGE_SECONDS * 1000;
export const RECENT_SIGN_IN_WINDOW_SECONDS = 60 * 5;

export const PROTECTED_PATH_PREFIXES = [
  "/new",
  "/processing",
  "/editor",
  "/templates",
  "/plagiarism",
] as const;
