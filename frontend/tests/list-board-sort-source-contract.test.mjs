// list-board sort — header sort state + API query source contract
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const apiFile = resolve(__dirname, '../src/lib/api/list-board.ts');
const pageFile = resolve(__dirname, '../src/routes/list-board/+page.svelte');
const apiSrc = readFileSync(apiFile, 'utf-8');
const pageSrc = readFileSync(pageFile, 'utf-8');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) { console.log(`  ✓ ${msg}`); passed++; }
  else { console.error(`  ✗ ${msg}`); failed++; }
}

console.log('list-board sort source contract');

// API layer
assert(apiSrc.includes('sort_by'), 'API listItems accepts sort_by param');
assert(apiSrc.includes('sort_order'), 'API listItems accepts sort_order param');
assert(apiSrc.includes("'asc' | 'desc'"), 'sort_order typed as asc | desc');

// page: sort state
assert(pageSrc.includes('sortKey'), 'page tracks sortKey state');
assert(pageSrc.includes('sortDir'), 'page tracks sortDir state');
assert(pageSrc.includes('toggleSort'), 'page has toggleSort handler');

// page: sort icons (lucide)
assert(pageSrc.includes('ChevronUp') || pageSrc.includes('ChevronsUpDown'), 'sort icons used');

// page: sort passed to API
assert(pageSrc.includes('sort_by: sortKey'), 'page passes sortKey to API');
assert(pageSrc.includes('sort_order: sortDir'), 'page passes sortDir to API');

// page: asc/desc/none cycle
assert(pageSrc.includes("'asc'") && pageSrc.includes("'desc'"), 'asc and desc cycle present');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
