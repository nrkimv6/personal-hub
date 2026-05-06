import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../src/routes/crawl/schedules/[id]/runs/+page.svelte", import.meta.url),
  "utf8",
);

const requiredStateNames = [
  "schedule",
  "runs",
  "stats",
  "loading",
  "error",
  "currentPage",
  "limit",
  "total",
  "status",
  "showPostsModal",
  "selectedRun",
  "runPosts",
  "loadingPosts",
  "postsPage",
  "postsLimit",
  "postsTotal",
];

function declarationPattern(name) {
  return new RegExp(`let\\s+${name}\\b[\\s\\S]*?=\\s*\\$state(?:<[^>]+>)?\\(`);
}

test("crawl schedule runs mutable UI state uses Svelte runes state", () => {
  assert.match(source, /\$derived\.by\(\(\) => parseInt\(\$page\.params\.id/);
  assert.match(source, /\$derived\.by\(\(\) => Math\.ceil\(total \/ limit\)\)/);
  assert.match(source, /\$derived\.by\(\(\) => Math\.ceil\(postsTotal \/ postsLimit\)\)/);

  for (const name of requiredStateNames) {
    assert.match(source, declarationPattern(name), `${name} must be declared with $state(...)`);
  }
});

test("crawl schedule runs loading and error states have explicit terminal UI paths", () => {
  assert.match(source, /finally\s*\{\s*loading = false;\s*\}/);
  assert.match(source, /\{:else if error\}/);
  assert.match(source, /\{:else if !runs \|\| runs\.length === 0\}/);
  assert.match(source, /실행 기록이 없습니다/);
});
