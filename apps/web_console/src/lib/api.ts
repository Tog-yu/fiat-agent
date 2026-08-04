// Thin client for the fiat-agent backend API.
//
// In dev the Next server rewrites "/api/*" to the backend (see next.config.mjs),
// so we use relative paths. Set NEXT_PUBLIC_API_BASE to target an external
// origin explicitly if needed.

export interface CurrentUser {
  actor_id: string;
  roles: string[];
  environment: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export async function getCurrentUser(): Promise<CurrentUser> {
  const res = await fetch(`${API_BASE}/api/users/me`, { credentials: "include" });
  if (!res.ok) {
    throw new Error(`failed to load /api/users/me: ${res.status}`);
  }
  return (await res.json()) as CurrentUser;
}
