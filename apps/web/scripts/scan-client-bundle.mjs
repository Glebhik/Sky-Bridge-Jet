import { readdir, readFile } from "node:fs/promises";
import { extname, join, resolve } from "node:path";

const clientRoot = resolve(".next/static");
const scannedExtensions = new Set([".css", ".js", ".json", ".map", ".txt"]);
const forbiddenLiterals = [
  "API_UPSTREAM_ORIGIN",
  "DEMO_PORTAL_ENABLED",
  "NEXT_PUBLIC_DEMO_PORTAL_ENABLED",
  process.env.API_UPSTREAM_ORIGIN,
  process.env.CLIENT_BUNDLE_SECRET_SENTINEL,
].filter((value) => typeof value === "string" && value.length > 0);
const forbiddenPatterns = [
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /\bsk_(?:live|test)_[A-Za-z0-9]{12,}\b/,
  /\brk_(?:live|test)_[A-Za-z0-9]{12,}\b/,
  /\bAKIA[0-9A-Z]{16}\b/,
];

async function listFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await listFiles(path)));
    else if (scannedExtensions.has(extname(entry.name))) files.push(path);
  }
  return files;
}

const files = await listFiles(clientRoot);
if (files.length === 0)
  throw new Error(`No client assets found under ${clientRoot}`);

for (const file of files) {
  const content = await readFile(file, "utf8");
  for (const literal of forbiddenLiterals) {
    if (content.includes(literal)) {
      throw new Error(
        `Forbidden server-only literal found in client asset ${file}`,
      );
    }
  }
  for (const pattern of forbiddenPatterns) {
    if (pattern.test(content)) {
      throw new Error(`Secret-like value found in client asset ${file}`);
    }
  }
}

console.log(`Client-bundle scan passed (${files.length} assets).`);
