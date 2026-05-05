import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

test("long single-line Claude RESULT output collapses by character threshold", () => {
  assert.match(source, /const PREVIEW_LINE_LIMIT = 3/);
  assert.match(source, /const PREVIEW_CHAR_LIMIT = 600/);
  assert.match(source, /linePreview\.length > PREVIEW_CHAR_LIMIT/);
  assert.match(source, /function shouldCollapseMessage\(message: string\): boolean/);
  assert.match(source, /getHiddenLineCount\(message\) > 0 \|\| getHiddenCharCount\(message\) > 0/);
});

test("ERROR and STDERR filters persist and report hidden count", () => {
  assert.match(source, /const TAG_FILTER_STORAGE_KEY = 'devRunnerHiddenLogTags'/);
  assert.match(source, /const FILTERABLE_TAGS = \['ERROR', 'STDERR'\]/);
  assert.match(source, /let hiddenTags = \$state<Set<string>>\(new Set\(\)\)/);
  assert.match(source, /window\.localStorage\.setItem\(TAG_FILTER_STORAGE_KEY/);
  assert.match(source, /hidden \{hiddenLogCount\}/);
});
