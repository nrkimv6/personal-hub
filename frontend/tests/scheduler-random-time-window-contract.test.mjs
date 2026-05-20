import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const sourcePath = resolve('frontend/src/routes/scheduler/ScheduleListTab.svelte');
const source = readFileSync(sourcePath, 'utf8');
const googlePagePath = resolve('frontend/src/routes/collect/google/+page.svelte');
const googlePageSource = readFileSync(googlePagePath, 'utf8');

assert.match(source, /scheduleWindows/);
assert.match(source, /editWindows/);
assert.doesNotMatch(source, /scheduleTimes/);
assert.doesNotMatch(source, /editTimes/);
assert.doesNotMatch(source, /time_windows:\s*\w+\.map\(\(\w+\)\s*=>\s*\(\{\s*start:\s*\w+,\s*end:\s*\w+\s*\}\)\)/);
assert.match(source, /시작\/종료 시각이 같을 수 없습니다/);
assert.match(source, /범위 수정 필요/);
assert.doesNotMatch(source, /min_interval_hours/);

assert.match(googlePageSource, /buildOneHourWindow/);
assert.doesNotMatch(
  googlePageSource,
  /time_windows:\s*\[\{\s*start:\s*scheduleTime,\s*end:\s*scheduleTime\s*\}\]/,
);

console.log('scheduler random time-window source contract passed');
