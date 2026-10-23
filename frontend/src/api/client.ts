// Thin fetch wrapper for the backend API. In development Vite proxies /api to
// the FastAPI server (see vite.config.ts); set VITE_API_BASE_URL to call a
// backend on another origin instead.

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

let authToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

/** Called when an admin request is rejected because the session expired. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("Can't reach the college assistant server. Check your connection and try again.", 0);
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Non-JSON error body; keep the generic message.
    }
    if (response.status === 401 && authToken) onUnauthorized?.();
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}
