import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const pageFile = resolve(__dirname, '../src/routes/list-board/+page.svelte');
const src = readFileSync(pageFile, 'utf-8');

let passed = 0;
let failed = 0;
function assert(condition, msg) {
  if (condition) { console.log(`  ✓ ${msg}`); passed++; }
  else { console.error(`  ✗ ${msg}`); failed++; }
}

console.log('list-board page source contract');

assert(src.includes("listBoardApi"), "uses listBoardApi");
assert(!src.includes("fetch("), "no raw fetch()");
assert(src.includes("createPagePagination"), "uses pagination utility");
assert(src.includes("markdownText"), "has markdownText state");
assert(src.includes("handleImport"), "has handleImport function");
assert(src.includes("textarea"), "has textarea for markdown input");
assert(src.includes("target=\"_blank\""), "links open in new tab");
assert(src.includes("rounded-lg border border-border bg-card"), "uses shared card panel token surface");
assert(src.includes("overflow-hidden rounded-lg border border-border bg-card"), "uses events-style table shell");
assert(src.includes("border-b border-border bg-muted"), "uses events-style muted table header");
assert(src.includes("divide-y divide-border"), "uses events-style row dividers");
assert(src.includes("hover:bg-muted"), "uses shared muted hover rows/buttons");
assert(src.includes("text-primary hover:underline"), "uses shared primary link token");
assert(src.includes("text-success"), "uses success token for created import count");
assert(src.includes("text-warning"), "uses warning token for updated import count");
assert(src.includes("text-destructive"), "uses destructive token for errors");
assert(src.includes("overflow-x-auto"), "keeps horizontal table scroll for narrow screens");
assert(!/zinc-|bg-blue-600|text-blue-400|text-green-400|text-yellow-400|text-red-400/.test(src), "no legacy local color classes on page");

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
