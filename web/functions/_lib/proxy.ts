import { API_URL } from "../_config";

// Forwards method, path, query and body to FB12's API with the Cloudflare Access token
// Cloudflare adds to requests that passed Access. Any Authorization header or cookie the
// browser sends is dropped. Status and body come back unchanged; streams stay streams.
const FORWARD_REQUEST_HEADERS = ["content-type", "accept", "cf-access-jwt-assertion", "last-event-id"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "cache-control", "www-authenticate", "x-accel-buffering"];

export async function proxy(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  const target = API_URL + incoming.pathname + incoming.search;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const init: RequestInit = { method: request.method, headers, redirect: "manual" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }
  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return new Response(
      JSON.stringify({ error: { code: "UPSTREAM_ERROR", message: `The Pages Function could not reach FB12's API: ${message}` } }),
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }
  const out = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}
