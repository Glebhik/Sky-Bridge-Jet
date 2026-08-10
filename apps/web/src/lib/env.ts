const configuredApiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function getApiBaseUrl(): string {
  try {
    return new URL(configuredApiBaseUrl).toString().replace(/\/$/, "");
  } catch {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must be an absolute URL.");
  }
}
