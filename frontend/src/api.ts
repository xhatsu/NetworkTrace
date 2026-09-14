import type { Filters } from "./types";
const API = import.meta.env.VITE_API_URL || "";
export function queryString(
  filters: Filters,
  extra: Record<string, string | undefined> = {},
) {
  const p = new URLSearchParams();
  Object.entries({ ...filters, ...extra }).forEach(([k, v]) => {
    const key = k === "start" ? "from" : k === "end" ? "to" : k;
    if (v) {
      const value = (k === "start" || k === "end") ? String(Date.parse(v)) : v;
      p.set(key, value);
    }
  });
  return p.toString();
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init);
  if (!response.ok) {
    let message = "Unable to load telemetry";
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.json();
}
