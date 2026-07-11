// Shared API client. Same-origin fetch (Next rewrites /api/* -> FastAPI), so
// the session cookie flows automatically. Throws Error(message) on failure;
// 401 rejects with code "unauthorized" so callers can redirect to /signin.

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

type Options = Omit<RequestInit, "body"> & { body?: unknown };

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const { body, headers, ...rest } = opts;
  const init: RequestInit = { credentials: "same-origin", ...rest, headers: { ...headers } };
  if (body !== undefined && !(body instanceof FormData)) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  } else if (body instanceof FormData) {
    init.body = body;
  }
  const res = await fetch(`/api${path}`, init);
  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const msg =
      (data && typeof data === "object" && "error" in data && (data as { error: string }).error) ||
      (res.status === 401 ? "unauthorized" : `Request failed (${res.status})`);
    throw new ApiError(String(msg), res.status);
  }
  return data as T;
}

// Raw fetch for polling / streaming where the caller wants the Response.
export function apiFetch(path: string, opts: RequestInit = {}) {
  return fetch(`/api${path}`, { credentials: "same-origin", ...opts });
}

// Poll a background job (/api/jobs/{id}) until done|error.
export async function pollJob<T = unknown>(
  jobId: string,
  onStage?: (stage: string, label?: string) => void,
  intervalMs = 1200,
): Promise<T> {
  for (;;) {
    const res = await apiFetch(`/jobs/${jobId}`);
    if (!res.ok) {
      if (res.status === 401) throw new ApiError("unauthorized", 401);
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.error || `Job lookup failed (${res.status})`, res.status);
    }
    const job = await res.json();
    if (onStage) onStage(job.stage, job.stage_label);
    if (job.status === "done") return job.result as T;
    if (job.status === "error") throw new Error(job.error || "Job failed");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
