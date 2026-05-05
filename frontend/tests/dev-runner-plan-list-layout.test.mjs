import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/components/dev-runner/PlanList.svelte", import.meta.url),
  "utf8",
);

test("plan rows are two-line layouts with filename on the first row", () => {
  assert.match(source, /flex min-h-\[4rem\] flex-col/);
  assert.match(source, /<div class="flex w-full min-w-0 items-center gap-2">/);
  assert.match(source, /<div class="flex w-full min-w-0 items-center gap-1\.5 pl-5/);
  assert.match(source, /`\$\{plan\.progress\.done\}\/\$\{plan\.progress\.total\} \(\$\{Math\.round/);
});

test("hide and remove actions require plan edit mode", () => {
  assert.match(source, /let editingPlans = \$state\(false\)/);
  assert.match(source, /aria-pressed=\{editingPlans\}/);
  assert.match(source, /\{#if editingPlans\}/);
  assert.match(source, /handleIgnore\(e, plan\.path\)/);
  assert.match(source, /handleRemovePath\(e, plan\.path\)/);
});
