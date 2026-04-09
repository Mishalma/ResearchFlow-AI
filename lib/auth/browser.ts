export function getBrowserCsrfToken() {
  if (typeof document === "undefined") {
    return "";
  }

  const match = document.cookie.match(/(?:^|; )paper_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}
