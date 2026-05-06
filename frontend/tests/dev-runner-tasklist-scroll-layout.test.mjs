import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/components/dev-runner/TaskList.svelte", import.meta.url),
  "utf8",
);

test("task list scroll body is separate from the card list flex layout", () => {
  assert.match(
    source,
    /<div class="flex-1 min-h-0 overflow-y-auto dr-scrollbar-thin">/,
  );
  assert.doesNotMatch(
    source,
    /<div class="flex-1 min-h-0 flex flex-col gap-2 overflow-y-auto dr-scrollbar-thin">/,
  );
  assert.match(source, /<div class="flex flex-col gap-2 pb-1 pr-1">/);
});

test("task phase cards cannot shrink and clip their checklist content", () => {
  assert.match(
    source,
    /<div class="border border-border rounded-lg overflow-hidden bg-card text-card-foreground shadow-sm shrink-0">/,
  );
});

test("child checkbox labels can wrap within the remaining row width", () => {
  assert.match(source, /<div class="flex items-start gap-2">/);
  assert.match(
    source,
    /<span class="min-w-0 flex-1 text-\[11px\] leading-relaxed break-words whitespace-pre-wrap \{child\.checked \? 'text-muted-foreground\/80 line-through' : 'text-muted-foreground'\}">\{child\.text\}<\/span>/,
  );
});
