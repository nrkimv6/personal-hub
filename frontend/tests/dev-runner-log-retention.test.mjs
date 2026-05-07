import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);
const logParse = readFileSync(
  new URL("../src/lib/dev-runner/log-parse.ts", import.meta.url),
  "utf8",
);

test("loadRecent appends a new log session instead of replacing previous lines", () => {
  assert.match(source, /let loadedRecentLogIdentity = \$state<string \| null>\(null\)/);
  assert.match(logParse, /function extractLogIdentity\(parsed: ParsedLine\[\]\): string \| null/);
  assert.match(logParse, /log_path=\(\[\^\\s\]\+\)/);
  assert.match(source, /const shouldAppendSession =/);
  assert.match(source, /lines = \[\.\.\.staleExisting, buildSessionSeparator\(nextIdentity\), \.\.\.currentParsed\]\.slice\(-MAX_LINES\)/);
  assert.doesNotMatch(source, /lines = parsed;\s*expandedLongLines = new Set\(\);/);
});
