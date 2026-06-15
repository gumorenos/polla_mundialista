const API_BASE = import.meta.env.VITE_API_URL ?? ''
const ADMIN_TOKEN = import.meta.env.VITE_ADMIN_TOKEN ?? ''

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  requireAdmin = false,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> ?? {}),
  }

  if (requireAdmin && ADMIN_TOKEN) {
    headers['X-Admin-Token'] = ADMIN_TOKEN
  }

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}))
    throw new ApiError(
      response.status,
      (errorBody as { detail?: string })?.detail ?? `${response.status} ${response.statusText}`,
    )
  }

  return response.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body: unknown, requireAdmin = false) =>
    apiFetch<T>(path, { method: 'POST', body: JSON.stringify(body) }, requireAdmin),
  delete: <T>(path: string, requireAdmin = false) =>
    apiFetch<T>(path, { method: 'DELETE' }, requireAdmin),
}

export { ApiError }

/** True when the admin token env var is configured at build time. */
export const hasAdminToken = Boolean(ADMIN_TOKEN)
