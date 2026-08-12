import { useAuthStore } from "../stores/auth";
import type { AuthResponse } from "./types";

const API_ROOT = "/api/v1";
let refreshPromise: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_ROOT}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then(async (response) => {
        if (!response.ok) return false;
        const data = (await response.json()) as AuthResponse;
        useAuthStore.getState().setSession(data.access_token, data.user);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export async function bootstrapSession() {
  const refreshed = await refreshSession();
  if (!refreshed) useAuthStore.getState().markReady();
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const response = await authenticatedFetch(path, init, retry);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string; error?: { message?: string } }
      | null;
    throw new Error(
      payload?.detail ?? payload?.error?.message ?? `请求失败（${response.status}）`,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function authenticatedFetch(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<Response> {
  const token = useAuthStore.getState().accessToken;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (response.status === 401 && retry && (await refreshSession())) {
    return authenticatedFetch(path, init, false);
  }
  return response;
}

export async function download(path: string, filename: string): Promise<void> {
  const response = await authenticatedFetch(path);
  if (!response.ok) throw new Error(`下载失败（${response.status}）`);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
