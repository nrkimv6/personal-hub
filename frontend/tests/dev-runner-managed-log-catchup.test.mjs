import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);
const backoff = readFileSync(
  new URL("../src/lib/dev-runner/backoff.ts", import.meta.url),
  "utf8",
);
const runnerInstance = readFileSync(
  new URL("../src/lib/components/dev-runner/RunnerInstanceTab.svelte", import.meta.url),
  "utf8",
);
const devRunnerTab = readFileSync(
  new URL("../src/routes/automation/DevRunnerTab.svelte", import.meta.url),
  "utf8",
);

function functionBody(source, name) {
  const start = source.indexOf(`function ${name}`);
  assert.notEqual(start, -1, `${name} not found`);
  const nextFunction = source.indexOf("\n\tasync function ", start + 1);
  const nextPlainFunction = source.indexOf("\n\tfunction ", start + 1);
  const candidates = [nextFunction, nextPlainFunction].filter((idx) => idx > start);
  const end = candidates.length > 0 ? Math.min(...candidates) : source.length;
  return source.slice(start, end);
}

test("managed LogViewer records recent/full load failures instead of silent catch", () => {
  const loadRecent = functionBody(logViewer, "loadRecent");
  const loadFull = functionBody(logViewer, "loadFull");

  assert.match(logViewer, /let lastLogLoadError = \$state<string \| null>\(null\)/);
  assert.match(logViewer, /function recordLogLoadError/);
  assert.match(loadRecent, /catch \(error\)/);
  assert.match(loadRecent, /recordLogLoadError\('recent 로그 로드', error\)/);
  assert.doesNotMatch(loadRecent, /catch\s*\{\s*(?:\/\/[^\n]*\n\s*)?\}/);
  assert.match(loadFull, /catch \(error\)/);
  assert.match(loadFull, /recordLogLoadError\('full 로그 로드', error\)/);
});

test("diagnostics cannot block initial recent catch-up", () => {
  const mountBlock = logViewer.slice(
    logViewer.indexOf("onMount(async () =>"),
    logViewer.indexOf("onDestroy(() =>"),
  );

  assert.match(mountBlock, /void runDiagnostics\(\);/);
  assert.match(mountBlock, /await loadRecent\(\);/);
  assert.doesNotMatch(mountBlock, /await runDiagnostics\(\);\s*await loadRecent\(\);/);
});

test("managed catch-up is retried and coalesced", () => {
  assert.match(logViewer, /createBackoff\(\{ baseMs: 600, maxMs: 60000, maxAttempts: 4 \}\)/);
  assert.match(backoff, /nextDelay\(\): number \| null/);
  assert.match(logViewer, /function scheduleManagedRecentRetry/);
  assert.match(logViewer, /let _catchUpPromise: Promise<void> \| null = null/);
  assert.match(logViewer, /if \(_catchUpPromise\) return _catchUpPromise/);
  assert.match(logViewer, /_catchUpInProgress = true/);
});

test("ref registration triggers managed catch-up after onOpen races", () => {
  assert.match(runnerInstance, /logRef\(\{ injectLine: logViewer\.injectLine[\s\S]*catchUp: logViewer\.catchUp \}\);/);
  assert.match(runnerInstance, /void logViewer\.catchUp\?\.\(\);/);

  assert.match(devRunnerTab, /function catchUpRunnerLogRef/);
  assert.match(devRunnerTab, /logRefs\.set\(tab\.id, ref\);\s*catchUpRunnerLogRef\(tab\.id, ref\);/);
  assert.match(devRunnerTab, /onOpen: \(\) => \{[\s\S]*catchUpRunnerLogRef\(id, ref\);/);
  assert.match(devRunnerTab, /function catchUpVisibleRunnerRefs/);
});
