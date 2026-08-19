import {
  forwardToUpstream,
  proxyRejectionResponse,
  validateProxyRequest,
} from "@/lib/server/proxy";

/**
 * The single same-origin API proxy endpoint: `/api/proxy/<allow-listed path>`.
 *
 * The browser only ever calls this route on the web origin; it validates the path/method
 * against the closed allow-list and forwards the rest to the trusted upstream API. This
 * runs on the Node.js runtime (it needs `getSetCookie()` and streaming) and is never
 * statically cached.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Context = { params: Promise<{ path: string[] }> };

async function handle(request: Request, context: Context): Promise<Response> {
  const { path } = await context.params;
  const validation = validateProxyRequest(path ?? [], request.method);
  if (!validation.ok) {
    return proxyRejectionResponse(validation.status, validation.code);
  }
  return forwardToUpstream(request, validation.path);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
