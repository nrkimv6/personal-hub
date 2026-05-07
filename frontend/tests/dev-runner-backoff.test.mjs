import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/dev-runner/backoff.ts", import.meta.url),
  "utf8",
);
const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

test("createBackoff exposes exponential delay, cap, exhaustion, and reset contracts", () => {
  assert.match(source, /export function createBackoff/);
  assert.match(source, /Math\.min\(baseMs \* Math\.pow\(2, attempts\), maxMs\)/);
  assert.match(source, /maxAttempts !== undefined && attempts >= maxAttempts/);
  assert.match(source, /return null/);
  assert.match(source, /reset\(\) \{\s*attempts = 0/);
});

test("LogViewer uses shared backoff for SSE and managed catch-up retry", () => {
  assert.match(logViewer, /const sseReconnectBackoff = createBackoff\(\{ baseMs: 3000, maxMs: 60000 \}\)/);
  assert.match(logViewer, /const recentRetryBackoff = createBackoff\(\{ baseMs: 600, maxMs: 60000, maxAttempts: 4 \}\)/);
  assert.match(logViewer, /return sseReconnectBackoff\.nextDelay\(\) \?\? 60000/);
  assert.match(logViewer, /const delay = recentRetryBackoff\.nextDelay\(\)/);
});
