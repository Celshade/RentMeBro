const API_BASE_URL = import.meta.env.VITE_API_BASE_URL as string;

const ACCESS_TOKEN_KEY = 'rentmebro_access_token';
const REFRESH_TOKEN_KEY = 'rentmebro_refresh_token';

/**
 * Fired on `window` when the refresh token is missing or rejected, so
 * AuthContext can clear the signed-in user and bounce to /login.
 */
export const AUTH_LOGOUT_EVENT = 'rentmebro:auth-logout';


/**
 * An API request that came back with a non-OK status.
 *
 * Carries the HTTP status alongside the server's `detail` message, so
 * callers can branch on the status instead of matching message text.
 * Extends `Error` with the same message, so existing handlers that
 * only read `.message` are unaffected.
 * @param message - The server's `detail`, or a generic fallback.
 * @param status - The HTTP status code the response carried.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}


/** Reads/writes the JWT pair used to authenticate API requests. */
export const tokenStorage = {
  getAccess: () => localStorage.getItem(ACCESS_TOKEN_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_TOKEN_KEY),
  setAccess: (access: string) => {
    localStorage.setItem(ACCESS_TOKEN_KEY, access);
  },
  set: (access: string, refresh: string) => {
    localStorage.setItem(ACCESS_TOKEN_KEY, access);
    localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
  },
  clear: () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  },
};

let refreshPromise: Promise<string | null> | null = null;

/**
 * Exchanges the stored refresh token for a new access token, storing
 * it on success. Concurrent callers share one in-flight request.
 *
 * The backend rotates refresh tokens on every use and blacklists the
 * one just spent, so the rotated refresh token must be stored too —
 * the old one won't work a second time.
 * @returns The new access token, or null if refresh isn't possible.
 */
function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;

  const refresh = tokenStorage.getRefresh();
  if (!refresh) return Promise.resolve(null);

  refreshPromise = fetch(`${API_BASE_URL}/api/auth/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  })
    .then(async (response) => {
      if (!response.ok) return null;
      const data = (await response.json()) as {
        access: string;
        refresh: string;
      };
      tokenStorage.set(data.access, data.refresh);
      return data.access;
    })
    .catch(() => null)
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

/**
 * Revokes the stored refresh token server-side, then clears storage.
 * Best-effort: storage is cleared even if the request fails, since
 * the client-side session is ending either way.
 */
export async function logoutRequest(): Promise<void> {
  const refresh = tokenStorage.getRefresh();
  if (refresh) {
    try {
      await fetch(`${API_BASE_URL}/api/auth/logout/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh }),
      });
    } catch {
      // Best-effort — storage is cleared regardless below.
    }
  }
  tokenStorage.clear();
}


/**
 * Thin fetch wrapper that attaches the JWT access token and parses
 * JSON, throwing on non-2xx responses.
 * @param path - API path relative to VITE_API_BASE_URL (e.g. '/api/leases/').
 * @param options - Standard fetch options; body is JSON-stringified if
 *   given a plain object, or sent as-is if given a FormData instance
 *   (e.g. for file uploads), letting the browser set the multipart
 *   Content-Type/boundary itself.
 * @returns Parsed JSON response body.
 */
export async function apiFetch<T>(
  path: string,
  options: Omit<RequestInit, 'body'> & { body?: unknown } = {},
  isRetry = false
): Promise<T> {
  const access = tokenStorage.getAccess();
  const isFormData = options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers as Record<string, string>),
  };
  if (access) {
    headers.Authorization = `Bearer ${access}`;
  }

  const body = isFormData
    ? (options.body as FormData)
    : options.body !== undefined
      ? JSON.stringify(options.body)
      : undefined;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    body,
  });

  if (response.status === 401 && !isRetry) {
    const newAccess = await refreshAccessToken();
    if (newAccess) {
      return apiFetch<T>(path, options, true);
    }
    tokenStorage.clear();
    window.dispatchEvent(new Event(AUTH_LOGOUT_EVENT));
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new ApiError(
      detail.detail || `Request failed: ${response.status}`,
      response.status
    );
  }

  const text = await response.text();
  return text ? JSON.parse(text) : (undefined as T);
}
