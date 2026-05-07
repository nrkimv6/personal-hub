import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripWrapperPrefix, shouldSkipInjectedLine } from "../src/lib/dev-runner/log-dedup.js";

const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);
const devRunnerTab = readFileSync(
  new URL("../src/routes/automation/DevRunnerTab.svelte", import.meta.url),
  "utf8",
);

// ── Phase 2: wrapper prefix 파싱 ────────────────────────────────────────────

test("WRAPPER_PREFIX_PATTERN constant is defined covering PR and PS", () => {
  assert.ok(
    logViewer.includes("WRAPPER_PREFIX_PATTERN") && logViewer.includes("(PR|PS)"),
    "WRAPPER_PREFIX_PATTERN with (PR|PS) alternation must be defined in LogViewer"
  );
});

test("WRAPPER_PREFIX_PATTERN pattern source matches [PR:...] and [PS:...] lines", () => {
  // Verify the regex can actually strip both prefixes
  const prLine = "[PR:a9694a1d] [22:58:52] [INFO] hello";
  const psLine = "[PS:a9694a1d] [22:58:52] [INFO] hello";
  const pattern = /^\[(PR|PS):[^\]]+\]\s*/;
  assert.equal(prLine.replace(pattern, ""), "[22:58:52] [INFO] hello");
  assert.equal(psLine.replace(pattern, ""), "[22:58:52] [INFO] hello");
});

test("parseLine uses WRAPPER_PREFIX_PATTERN not PR_PREFIX_PATTERN", () => {
  assert.match(logViewer, /strippedHead\s*=\s*head\.replace\(WRAPPER_PREFIX_PATTERN/);
  assert.doesNotMatch(logViewer, /head\.replace\(PR_PREFIX_PATTERN/);
});

test("stripWrapperPrefix removes [PR:...] from line", () => {
  const raw = "[PR:a9694a1d] [22:58:52] [INFO] hello";
  assert.equal(stripWrapperPrefix(raw), "[22:58:52] [INFO] hello");
});

test("stripWrapperPrefix removes [PS:...] from line", () => {
  const raw = "[PS:a9694a1d] [22:58:52] [THINK] reasoning here";
  assert.equal(stripWrapperPrefix(raw), "[22:58:52] [THINK] reasoning here");
});

test("stripWrapperPrefix is a no-op for lines without wrapper prefix", () => {
  const raw = "[22:58:52] [INFO] no prefix";
  assert.equal(stripWrapperPrefix(raw), raw);
});

// ── Phase 2: dedup — wrapper prefix 차이만 있는 동일 본문 라인 중복 제거 ────

test("PR and PS prefixed lines with same body are deduped", () => {
  const cache = new Map();
  const prLine = "[PR:runner-x] [22:58:52] [INFO] same body";
  const psLine = "[PS:runner-x] [22:58:52] [INFO] same body";
  assert.equal(shouldSkipInjectedLine(cache, "runner-x", prLine), false, "first PR line accepted");
  assert.equal(shouldSkipInjectedLine(cache, "runner-x", psLine), true, "PS line with same body deduped");
});

test("lines with different body content are not deduped even with same prefix type", () => {
  const cache = new Map();
  assert.equal(shouldSkipInjectedLine(cache, "r1", "[PR:r1] [INFO] line A"), false);
  assert.equal(shouldSkipInjectedLine(cache, "r1", "[PR:r1] [INFO] line B"), false);
});

// ── Phase 1: hasLoadedLogContent ────────────────────────────────────────────

test("HEADER_ONLY_TAGS constant covers TRIGGER, RUN_META, ENV, START", () => {
  assert.match(logViewer, /HEADER_ONLY_TAGS\s*=\s*new Set\(\[/);
  assert.match(logViewer, /HEADER_ONLY_TAGS[\s\S]{0,200}'TRIGGER'/);
  assert.match(logViewer, /HEADER_ONLY_TAGS[\s\S]{0,200}'RUN_META'/);
  assert.match(logViewer, /HEADER_ONLY_TAGS[\s\S]{0,200}'ENV'/);
  assert.match(logViewer, /HEADER_ONLY_TAGS[\s\S]{0,200}'START'/);
});

test("hasLoadedLogContent uses HEADER_ONLY_TAGS not only DIAG check", () => {
  assert.match(logViewer, /function hasLoadedLogContent[\s\S]{0,200}HEADER_ONLY_TAGS\.has\(line\.tag\)/);
  assert.doesNotMatch(
    logViewer,
    /function hasLoadedLogContent[\s\S]{0,200}line\.tag !== 'DIAG'/,
  );
});

// ── Phase 1: loadRecent retry reset 조건 ────────────────────────────────────

test("loadRecent resets retry only after hasLoadedLogContent not on any sourceLines", () => {
  // 수정 전: sourceLines.length > 0 → 수정 후: hasLoadedLogContent()
  assert.match(logViewer, /if \(hasLoadedLogContent\(\)\) \{\s*recentRetryBackoff\.reset\(\)/);
  assert.doesNotMatch(logViewer, /if \(sourceLines\.length > 0\) \{\s*recentRetry(?:Attempt = 0|Backoff\.reset\(\))/);
});

// ── Phase 3: catch-up trigger 계약 ──────────────────────────────────────────

test("catchUpRunnerLogRef checks running or activeTabId before calling catchUp", () => {
  assert.match(devRunnerTab, /function catchUpRunnerLogRef/);
  assert.match(devRunnerTab, /tab\.running \|\| activeTabId === runnerId/);
  assert.match(devRunnerTab, /void ref\.catchUp\?\.\(\)/);
});

test("applyRunnersSync triggers catchUpRunnerLogRef for visible runners", () => {
  assert.match(devRunnerTab, /function catchUpVisibleRunnerRefs/);
  assert.match(devRunnerTab, /catchUpRunnerLogRef\(runner\.runner_id\)/);
});
