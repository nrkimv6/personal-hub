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

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
