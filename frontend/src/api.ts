import type { Filters } from "./types";
const API = import.meta.env.VITE_API_URL || "";
export function queryString(
  filters: Filters,
  extra: Record<string, string | undefined> = {},
) {
  const p = new URLSearchParams();
  Object.entries({ ...filters, ...extra }).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") {
      if (k === "start" || k === "from") {
        const val = typeof v === "string" && isNaN(Number(v)) ? String(Date.parse(v)) : String(v);
        p.set("start", val);
        p.set("from", val);
      } else if (k === "end" || k === "to") {
        const val = typeof v === "string" && isNaN(Number(v)) ? String(Date.parse(v)) : String(v);
        p.set("end", val);
        p.set("to", val);
      } else {
        p.set(k, String(v));
      }
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
