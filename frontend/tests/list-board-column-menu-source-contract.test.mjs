// list-board column menu — CRUD source contract
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const apiFile = resolve(__dirname, '../src/lib/api/list-board.ts');
const menuFile = resolve(__dirname, '../src/routes/list-board/ColumnMenu.svelte');
const pageFile = resolve(__dirname, '../src/routes/list-board/+page.svelte');
const apiSrc = readFileSync(apiFile, 'utf-8');
const menuSrc = readFileSync(menuFile, 'utf-8');
const pageSrc = readFileSync(pageFile, 'utf-8');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) { console.log(`  ✓ ${msg}`); passed++; }
  else { console.error(`  ✗ ${msg}`); failed++; }
}

console.log('list-board column menu source contract');

// API layer
assert(apiSrc.includes('listColumns'), 'API has listColumns helper');
assert(apiSrc.includes('createColumn'), 'API has createColumn helper');
assert(apiSrc.includes('updateColumn'), 'API has updateColumn helper');
assert(apiSrc.includes('deleteColumn'), 'API has deleteColumn helper');
assert(apiSrc.includes('/list-board/columns'), 'columns endpoint path present');
assert(!apiSrc.includes("fetch("), 'no raw fetch in API');

// column types
assert(apiSrc.includes("'checkbox' | 'text' | 'select' | 'priority'"), 'ColumnType union defined');

// ColumnMenu component
assert(menuSrc.includes('createColumn'), 'ColumnMenu calls createColumn');
assert(menuSrc.includes('deleteColumn'), 'ColumnMenu calls deleteColumn');
assert(menuSrc.includes('handleCreate'), 'ColumnMenu has handleCreate handler');
assert(menuSrc.includes('handleDelete'), 'ColumnMenu has handleDelete handler');
assert(menuSrc.includes("column_type"), 'ColumnMenu handles column_type field');
assert(menuSrc.includes('options'), 'ColumnMenu handles options for select type');
assert(menuSrc.includes('border border-border'), 'ColumnMenu uses shared border token');
assert(menuSrc.includes('bg-background'), 'ColumnMenu uses shared input/button background token');
assert(menuSrc.includes('text-muted-foreground'), 'ColumnMenu uses shared muted text token');
assert(menuSrc.includes('bg-primary'), 'ColumnMenu uses primary action token');
assert(menuSrc.includes('text-destructive'), 'ColumnMenu uses destructive token for errors/delete hover');
assert(menuSrc.includes('confirm('), 'ColumnMenu keeps existing confirm flow in this scoped redesign');
assert(menuSrc.includes('alert('), 'ColumnMenu keeps existing alert flow in this scoped redesign');
assert(!/zinc-|bg-blue-600|text-red-400/.test(menuSrc), 'ColumnMenu has no legacy local color classes');

// page integration
assert(pageSrc.includes('ColumnMenu'), 'page includes ColumnMenu component');
assert(pageSrc.includes('listColumns'), 'page calls listColumns');
assert(pageSrc.includes('loadColumns'), 'page has loadColumns function');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
