import "server-only";

/**
 * Return whether the public, synthetic Customer Portal demonstration is enabled.
 *
 * This is deliberately a zero-argument, server-only decision. Request headers, query
 * parameters, cookies, forms, and request bodies have no path into the decision. Missing,
 * malformed, or differently-cased values fail closed.
 */
export function isDemoPortalEnabled(): boolean {
  return process.env.DEMO_PORTAL_ENABLED === "true";
}
