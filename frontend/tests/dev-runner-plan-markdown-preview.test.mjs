import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const previewSource = readFileSync(
  new URL("../src/lib/components/dev-runner/PlanMarkdownPreview.svelte", import.meta.url),
  "utf8",
);

const variantsSource = readFileSync(
  new URL("../src/lib/components/markdown/markdownVariants.ts", import.meta.url),
  "utf8",
);

test("automation plan markdown preview reuses the plan content API and renderer", () => {
  assert.match(previewSource, /devRunnerPlanApi\.content\(encoded\)/);
  assert.match(previewSource, /encodePathToBase64\(path\)/);
  assert.match(previewSource, /<MarkdownContent content=\{content\} variant="plan"/);
});

test("automation plan markdown preview has full-height reader layout states", () => {
  assert.match(previewSource, /flex h-full min-h-0 flex-col overflow-hidden/);
  assert.match(previewSource, /sticky top-0/);
  assert.match(previewSource, /flex-1 min-h-0 overflow-y-auto overflow-x-hidden/);
  assert.match(previewSource, /aria-label="계획서 전문 닫기"/);
  assert.match(previewSource, /내용을 불러오지 못했습니다/);
  assert.match(previewSource, /표시할 Markdown 내용이 없습니다/);
});

test("plan markdown variant keeps code blocks and tables inside the reader width", () => {
  assert.match(variantsSource, /prose-pre:max-w-full prose-pre:overflow-x-auto/);
  assert.match(variantsSource, /prose-table:block prose-table:max-w-full prose-table:overflow-x-auto/);
  assert.match(variantsSource, /\[&_table\]:block \[&_table\]:max-w-full \[&_table\]:overflow-x-auto/);
});
