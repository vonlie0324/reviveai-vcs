const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").trim();

export const API_BASE_URL = configuredApiBaseUrl
  ? configuredApiBaseUrl.replace(/\/$/, "")
  : import.meta.env.PROD
    ? ""
    : "http://localhost:8080";

const CSRF_COOKIE_NAME =
  import.meta.env.VITE_CSRF_COOKIE_NAME || "reviveai_csrf";

function readCookie(name: string): string | null {
  const encoded = `${encodeURIComponent(name)}=`;

  for (const part of document.cookie.split(";")) {
    const item = part.trim();

    if (item.startsWith(encoded)) {
      return decodeURIComponent(item.slice(encoded.length));
    }
  }

  return null;
}

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers || {});

  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = readCookie(CSRF_COOKIE_NAME);

    if (csrf) {
      headers.set("X-CSRF-Token", csrf);
    }
  }

  const response = await fetch(input, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 401) {
    window.dispatchEvent(
      new CustomEvent("reviveai:session-expired"),
    );
  }

  return response;
}
