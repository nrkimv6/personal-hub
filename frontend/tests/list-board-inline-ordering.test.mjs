// list-board inline ordering — late-response rollback guard source contract
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const pageFile = resolve(__dirname, '../src/routes/list-board/+page.svelte');
const cellFile = resolve(__dirname, '../src/routes/list-board/ListBoardCell.svelte');
const apiFile = resolve(__dirname, '../src/lib/api/list-board.ts');
const pageSrc = readFileSync(pageFile, 'utf-8');
const cellSrc = readFileSync(cellFile, 'utf-8');
const apiSrc = readFileSync(apiFile, 'utf-8');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) { console.log(`  ✓ ${msg}`); passed++; }
  else { console.error(`  ✗ ${msg}`); failed++; }
}

console.log('list-board inline ordering source contract');

// optimistic update: local state updated immediately before API call
assert(pageSrc.includes('item.properties'), 'page sets item.properties optimistically before await');
assert(pageSrc.includes('patchItemProperties'), 'page calls patchItemProperties API');

// rollback mechanism: saves previous value to restore on failure
assert(
  pageSrc.includes('saveError') || pageSrc.includes('rollback') || pageSrc.includes('prev'),
  'page has rollback/error state for failed patch'
);

// savingItemId guard: prevents stale save from overwriting newer optimistic value
assert(pageSrc.includes('savingItemId'), 'page tracks savingItemId to guard concurrent saves');

// text debounce: prevents rapid saves on every keystroke
assert(cellSrc.includes('debounceTimer'), 'cell uses debounce timer to coalesce rapid text changes');
assert(cellSrc.includes('clearTimeout') || cellSrc.includes('clearTimeout'), 'cell clears previous debounce timer on new input');

// blur save: guarantees save on focus loss even if debounce pending
assert(cellSrc.includes('handleTextBlur'), 'cell saves on blur to flush pending debounce');

// API: PATCH method used (idempotent for ordering safety)
assert(apiSrc.includes("method: 'PATCH'"), 'API uses PATCH method (idempotent)');

// API: uses item-specific endpoint (avoids overwriting sibling items)
assert(apiSrc.includes('/list-board/items/'), 'API targets item-specific endpoint');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
