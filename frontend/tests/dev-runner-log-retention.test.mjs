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

test("copyLog uses full log API with limit 5000, not lines state", () => {
  // full fetch with limit 5000 — not relying on lines state (MAX_LINES=500)
  assert.match(source, /devRunnerLogApi\.full\(runnerId,\s*0,\s*5000\)/);
});

test("copyLog has no isStale filter — stopped runner lines are included", () => {
  // isStale 필터 제거 확인: copy 경로에 !l.isStale 조건이 없어야 함
  const copyLogBlock = source.slice(source.indexOf('async function copyLog()'), source.indexOf('function addLine('));
  assert.doesNotMatch(copyLogBlock, /!l\.isStale/);
  assert.doesNotMatch(copyLogBlock, /filter\(l => !l\.isStale/);
});

test("copyLog has no 200-char truncation", () => {
  const copyLogBlock = source.slice(source.indexOf('async function copyLog()'), source.indexOf('function addLine('));
  assert.doesNotMatch(copyLogBlock, /raw\.length > 200/);
  assert.doesNotMatch(copyLogBlock, /slice\(0, 200\)/);
});

test("copyLog includes mergeStatus, mergeReason, mergeMessage in header", () => {
  assert.match(source, /\[MergeStatus\]/);
  assert.match(source, /\[MergeReason\]/);
  assert.match(source, /\[MergeMessage\]/);
  // Props interface includes mergeReason and mergeMessage
  assert.match(source, /mergeReason\?:\s*string \| null/);
  assert.match(source, /mergeMessage\?:\s*string \| null/);
});

test("copyLog uses fallback marker when full fetch fails", () => {
  assert.match(source, /\[Fallback\] full log fetch failed/);
  assert.match(source, /usedFallback/);
});

test("copy button is disabled while loading to prevent duplicate clicks", () => {
  assert.match(source, /disabled=\{copyState === 'loading'\}/);
  assert.match(source, /copyState === 'loading'\) return/);
});

test("copyState has idle/loading/copied/error states, not old copied boolean", () => {
  assert.match(source, /copyState = \$state<'idle' \| 'loading' \| 'copied' \| 'error'>/);
  assert.doesNotMatch(source, /let copied = \$state\(false\)/);
});

test("#3→#4 regression guard: all three root causes of header-only copy are closed", () => {
  const copyLogBlock = source.slice(
    source.indexOf('async function copyLog()'),
    source.indexOf('function addLine(')
  );
  // Root cause 1: isStale filter removed — stopped-runner lines no longer silently dropped
  // (old: filter(l => !l.isStale && l.tag !== 'NOISE') produced header-only for approval_required)
  assert.doesNotMatch(copyLogBlock, /!l\.isStale/);
  // Root cause 2: 200-char truncation removed — long BRANCH_PREFLIGHT/rebase messages preserved
  // (old: raw.length > 200 ? raw.slice(0, 200) + '…' : raw silently cut content)
  assert.doesNotMatch(copyLogBlock, /slice\(0, 200\)/);
  // Root cause 3: lines state (MAX_LINES=500) replaced by full API — stream switch no longer drops lines
  assert.match(source, /devRunnerLogApi\.full\(runnerId,\s*0,\s*5000\)/);
});
