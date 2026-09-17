import type { Filters } from "./types";
const API = import.meta.env.VITE_API_URL || "";
const API_KEY = (import.meta.env.VITE_API_KEY as string | undefined) || "";

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

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
  const headers = new Headers(init?.headers);
  if (API_KEY && !headers.has("X-API-Key")) {
    headers.set("X-API-Key", API_KEY);
  }

  const response = await fetch(`${API}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    let code: string | undefined;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.detail && typeof data.detail === "object") {
        code = data.detail.code;
        message = data.detail.message || data.detail.code || message;
      } else if (data.message && typeof data.message === "string") {
        message = data.message;
      }
    } catch {
      // Body not JSON
    }

    if (response.status === 401) {
      code = code || "unauthorized";
      message = "Authentication required (401). Operator API key configuration required.";
    } else if (response.status === 503 && code === "auth_unconfigured") {
      message = "Investigation authentication is not configured on the server (503).";
    } else if (response.status === 503 && code === "provider_unconfigured") {
      message = "LLM investigation provider is not configured on the server (503).";
    } else if (response.status === 404 && path.startsWith("/api/v1/investigations")) {
      code = code || "not_found";
      message = "LLM investigation feature is disabled or not found (404).";
    }

    throw new ApiError(message, response.status, code);
  }
  return response.json();
}
