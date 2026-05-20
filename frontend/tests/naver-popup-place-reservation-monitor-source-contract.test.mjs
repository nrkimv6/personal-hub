import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const typesFile = resolve(__dirname, '../src/lib/types.ts');
const apiFile = resolve(__dirname, '../src/lib/api/naver-booking.ts');
const panelFile = resolve(__dirname, '../src/lib/components/naver/PopupUrlMonitorPanel.svelte');

const types = readFileSync(typesFile, 'utf-8');
const api = readFileSync(apiFile, 'utf-8');
const panel = readFileSync(panelFile, 'utf-8');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
  if (condition) {
    console.log(`  ✓ ${msg}`);
    passed++;
  } else {
    console.error(`  ✗ ${msg}`);
    failed++;
  }
}

console.log('naver popup place reservation monitor source contract');

assert(types.includes("PopupMonitorKind = 'popup_list' | 'place_reservation'"), 'monitor kind literal is typed');
assert(types.includes('monitor_kind?: PopupMonitorKind'), 'create/update payload includes monitor_kind');
assert(types.includes('stop_on_detected?: boolean'), 'create/update payload includes stop_on_detected');
assert(types.includes('detected_at: string | null'), 'response type includes detected_at');
assert(types.includes('reservation_state?'), 'snapshot type includes reservation_state');

assert(api.includes("request<PopupUrlMonitor>('/naver-popup/monitors'"), 'create endpoint preserves monitor route');
assert(api.includes("request<PopupUrlMonitor>(`/naver-popup/monitors/${id}`"), 'update endpoint preserves monitor route');

assert(panel.includes("monitor_kind: PopupMonitorKind"), 'panel form tracks monitor_kind');
assert(panel.includes("stop_on_detected: boolean"), 'panel form tracks stop_on_detected');
assert(panel.includes("DEFAULT_PLACE_RESERVATION_URL"), 'panel has place reservation URL default');
assert(panel.includes("value=\"place_reservation\""), 'panel exposes place_reservation option');
assert(panel.includes("monitor_kind: form.monitor_kind"), 'payload sends monitor_kind');
assert(panel.includes("stop_on_detected: form.stop_on_detected"), 'payload sends stop_on_detected');
assert(panel.includes("reservationState"), 'panel renders reservation snapshot');
assert(panel.includes("monitorKindLabel"), 'panel renders kind label');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);

