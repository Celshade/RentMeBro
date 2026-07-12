const API_BASE_URL = import.meta.env.VITE_API_BASE_URL as string;

const ACCESS_TOKEN_KEY = 'rentmebro_access_token';
const REFRESH_TOKEN_KEY = 'rentmebro_refresh_token';

/** Reads/writes the JWT pair used to authenticate API requests. */
export const tokenStorage = {
  getAccess: () => localStorage.getItem(ACCESS_TOKEN_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_TOKEN_KEY),
  set: (access: string, refresh: string) => {
    localStorage.setItem(ACCESS_TOKEN_KEY, access);
    localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
  },
  clear: () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  },
};


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
  options: Omit<RequestInit, 'body'> & { body?: unknown } = {}
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

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed: ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json();
}
