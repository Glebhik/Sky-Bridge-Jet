// Test-only stub for the `server-only` package. In production the real package makes it a
// build error to import a server module from a client bundle; under vitest we alias it to
// this no-op so the server-side proxy/session logic can be unit-tested directly.
export {};
