import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const sourcePath = resolve('frontend/src/routes/crawl/schedules/[id]/runs/+page.svelte');
const source = readFileSync(sourcePath, 'utf8');

assert.match(source, /requires_time_window_repair/);
assert.match(source, /schedule_health/);
assert.match(source, /candidate_count_next_24h/);
assert.match(source, /스케줄 시간대 수정 필요/);
assert.match(source, /\/crawl\/schedules/);

console.log('crawl schedule runs health banner source contract passed');
