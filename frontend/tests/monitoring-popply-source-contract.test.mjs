import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const typesFile = resolve(__dirname, '../src/lib/types/monitoring.ts');
const unifiedFile = resolve(__dirname, '../src/lib/api/monitoringUnified.ts');
const apiFile = resolve(__dirname, '../src/lib/api/popplyReservation.ts');

const types = readFileSync(typesFile, 'utf-8');
const unified = readFileSync(unifiedFile, 'utf-8');
const api = readFileSync(apiFile, 'utf-8');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) { console.log(`  ✓ ${msg}`); passed++; }
  else { console.error(`  ✗ ${msg}`); failed++; }
}

console.log('monitoring POPPLY source contract');

assert(types.includes("'popply'"), "MonitorType includes popply");
assert(types.includes("popply: {"), "MONITOR_TYPE_META has popply");
assert(types.includes("createHref: '/popply'"), "popply createHref points to /popply");
assert(api.includes("popplyReservationApi"), "popplyReservationApi exported");
assert(api.includes("'/popply'"), "popply API base path defined");
assert(unified.includes("fetchPopplyItems"), "unified fetcher exists");
assert(unified.includes("type: 'popply'"), "unified item type is popply");
assert(unified.includes("detailHref: '/popply'"), "unified item detail href is /popply");
assert(unified.includes("popplyReservationApi.disableSchedule"), "toggle disable branch exists");
assert(unified.includes("popplyReservationApi.enableSchedule"), "toggle enable branch exists");

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
