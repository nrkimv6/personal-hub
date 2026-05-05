import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

test("loadRecent appends a new log session instead of replacing previous lines", () => {
  assert.match(source, /let loadedRecentLogIdentity = \$state<string \| null>\(null\)/);
  assert.match(source, /function extractLogIdentity\(parsed: ParsedLine\[\]\): string \| null/);
  assert.match(source, /log_path=\(\[\^\\s\]\+\)/);
  assert.match(source, /const shouldAppendSession =/);
  assert.match(source, /lines = \[\.\.\.staleExisting, buildSessionSeparator\(nextIdentity\), \.\.\.currentParsed\]\.slice\(-MAX_LINES\)/);
  assert.doesNotMatch(source, /lines = parsed;\s*expandedLongLines = new Set\(\);/);
});
