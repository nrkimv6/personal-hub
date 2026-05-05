import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/components/dev-runner/RunStatusBar.svelte", import.meta.url),
  "utf8",
);

test("runner tab label prefers plan filename and keeps Runner N as fallback only", () => {
  assert.match(source, /function resolveRunnerLabel\(runner: RunnerTab, index: number\): string/);
  assert.match(source, /resolveFullLabel\(runner\)/);
  assert.match(source, /return `Runner \$\{index \+ 1\}`/);
  assert.doesNotMatch(source, /function resolveVisibleLabel\(index: number\): string/);
});

test("runner state dot title is derived from runner lifecycle, not DONE log text", () => {
  assert.match(source, /function resolveRunnerStateTitle\(runner: RunnerTab\): string/);
  assert.match(source, /title=\{resolveRunnerStateTitle\(runner\)\}/);
  assert.doesNotMatch(source, /\[DONE\].*resolveRunnerStateTitle/s);
});
