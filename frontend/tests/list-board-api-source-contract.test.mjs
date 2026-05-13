// list-board API source contract: request helper 사용 검증
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const apiFile = resolve(__dirname, '../src/lib/api/list-board.ts');
const src = readFileSync(apiFile, 'utf-8');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) { console.log(`  ✓ ${msg}`); passed++; }
  else { console.error(`  ✗ ${msg}`); failed++; }
}

console.log('list-board API source contract');

assert(src.includes("from './client'"), "imports from client");
assert(src.includes("request<"), "uses request<T> generic helper");
assert(!src.includes("fetch("), "no raw fetch()");
assert(src.includes("listBoardApi"), "exports listBoardApi");
assert(src.includes("/list-board/import"), "import endpoint defined");
assert(src.includes("/list-board/items"), "items endpoint defined");

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
