// The only way the GUI talks to FB12: same-origin calls to /api and /admin, which the
// Pages Function forwards with the Cloudflare Access token. Every failure arrives as the
// contract's error envelope and is shown to Charles as is.

export interface ApiErrorBody {
  error: { code: string; message: string; upstream_status?: number };
}

export class ApiError extends Error {
  code: string;
  status: number;
  upstreamStatus?: number;
  constructor(status: number, code: string, message: string, upstreamStatus?: number) {
    super(message);
    this.status = status;
    this.code = code;
    this.upstreamStatus = upstreamStatus;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...(init?.headers ?? {}) },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ApiError(0, "NETWORK", `The call to ${path} did not reach the Pages Function: ${message}`);
  }
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!response.ok) {
    const envelope = body as ApiErrorBody | null;
    if (envelope && envelope.error) {
      throw new ApiError(response.status, envelope.error.code, envelope.error.message, envelope.error.upstream_status);
    }
    throw new ApiError(response.status, "HTTP_" + response.status, text ? text.slice(0, 300) : `HTTP ${response.status} from ${path} with no body.`);
  }
  return body as T;
}

export function describeError(error: unknown): { code: string; message: string } {
  if (error instanceof ApiError) {
    return { code: error.code + (error.upstreamStatus ? ` (upstream ${error.upstreamStatus})` : ""), message: error.message };
  }
  if (error instanceof Error) return { code: "ERROR", message: error.message };
  return { code: "ERROR", message: String(error) };
}
