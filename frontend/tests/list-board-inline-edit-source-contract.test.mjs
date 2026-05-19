// list-board inline edit — optimistic update + rollback source contract
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const apiFile = resolve(__dirname, '../src/lib/api/list-board.ts');
const pageFile = resolve(__dirname, '../src/routes/list-board/+page.svelte');
const cellFile = resolve(__dirname, '../src/routes/list-board/ListBoardCell.svelte');
const apiSrc = readFileSync(apiFile, 'utf-8');
const pageSrc = readFileSync(pageFile, 'utf-8');
const cellSrc = readFileSync(cellFile, 'utf-8');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) { console.log(`  ✓ ${msg}`); passed++; }
  else { console.error(`  ✗ ${msg}`); failed++; }
}

console.log('list-board inline edit source contract');

// API layer
assert(apiSrc.includes('patchItemProperties'), 'API has patchItemProperties helper');
assert(apiSrc.includes('/list-board/items/'), 'patch endpoint uses items/{id} path');
assert(apiSrc.includes("method: 'PATCH'"), 'patch uses PATCH method');
assert(!apiSrc.includes("fetch("), 'no raw fetch in API');

// page: optimistic update pattern
assert(pageSrc.includes('savingItemId'), 'page tracks savingItemId for loading state');
assert(pageSrc.includes('item.properties'), 'page writes to item.properties for optimistic update');
assert(pageSrc.includes('patchItemProperties'), 'page calls patchItemProperties');
assert(pageSrc.includes('handleCellChange'), 'page has handleCellChange handler');
assert(pageSrc.includes('saveError'), 'page tracks saveError for rollback display');

// cell: types
assert(cellSrc.includes("column_type === 'checkbox'"), 'cell handles checkbox type');
assert(cellSrc.includes("column_type === 'text'"), 'cell handles text type');
assert(cellSrc.includes("column_type === 'select'"), 'cell handles select type');
assert(cellSrc.includes("column_type === 'priority'"), 'cell handles priority type');
assert(cellSrc.includes('accent-primary'), 'checkbox uses primary accent token');
assert(cellSrc.includes('text-muted-foreground'), 'cell uses muted text token');
assert(cellSrc.includes('text-warning'), 'priority medium uses warning token');
assert(cellSrc.includes('text-warning-foreground'), 'priority high uses warning foreground token');
assert(cellSrc.includes('text-destructive'), 'priority critical uses destructive token');
assert(cellSrc.includes('focus:border-ring'), 'cell uses shared focus ring token');
assert(!/zinc-|accent-blue-500|text-yellow-400|text-orange-400|text-red-400/.test(cellSrc), 'cell has no legacy local color classes');

// cell: debounce for text
assert(cellSrc.includes('debounceTimer'), 'text cell uses debounce timer');
assert(cellSrc.includes('handleTextBlur'), 'text cell saves on blur');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
