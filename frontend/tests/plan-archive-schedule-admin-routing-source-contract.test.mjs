import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const viteConfigSource = readFileSync('frontend/vite.config.ts', 'utf8');
const apiSource = readFileSync('frontend/src/lib/api/plan-archive-schedule.ts', 'utf8');

test('admin frontend mode falls back to admin API port 8001 when VITE_API_PORT is absent', () => {
	assert.match(viteConfigSource, /frontendMode === 'admin'\s*\?\s*'8001'\s*:\s*'8000'/);
	assert.match(viteConfigSource, /process\.env\.VITE_API_PORT\s*\|\|\s*env\.VITE_API_PORT\s*\|\|\s*defaultApiPortForMode\(\)/);
});

test('frontend-mode read-back reports the same resolved proxy apiPort', () => {
	assert.match(viteConfigSource, /frontendModePlugin\(apiPort\)/);
	assert.match(viteConfigSource, /JSON\.stringify\(\{\s*mode: frontendMode \|\| 'default',\s*outDir: frontendOutDir,\s*apiPort\s*\}\)/s);
});

test('archiveScheduleApi keeps pause and resume behind planRecordsRequest wrappers', () => {
	assert.match(apiSource, /pause:\s*\(\)\s*=>\s*[\r\n\t ]*planRecordsRequest<ArchiveSchedulePauseResumeResponse>\('\/records\/archive-schedule\/pause'/);
	assert.match(apiSource, /resume:\s*\(\)\s*=>\s*[\r\n\t ]*planRecordsRequest<ArchiveSchedulePauseResumeResponse>\('\/records\/archive-schedule\/resume'/);
	const archiveScheduleBlock = apiSource.slice(apiSource.indexOf('export const archiveScheduleApi'));
	assert.doesNotMatch(archiveScheduleBlock, /\/api\/v1/);
});
