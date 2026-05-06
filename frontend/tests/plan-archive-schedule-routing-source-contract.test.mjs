import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const automationPage = readFileSync('frontend/src/routes/automation/+page.svelte', 'utf8');
const schedulerListTab = readFileSync('frontend/src/routes/scheduler/ScheduleListTab.svelte', 'utf8');

test('automation page does not pass runner or initialRunner to ArchiveTab', () => {
	// ArchiveTab 사용 부분에 runner/initialRunner prop 전달 없음
	const archiveTabUsages = automationPage.match(/<ArchiveTab[^/]*\/>/g) ?? [];
	for (const usage of archiveTabUsages) {
		assert.doesNotMatch(usage, /runner/, `ArchiveTab usage should not have runner prop: ${usage}`);
		assert.doesNotMatch(usage, /initialRunner/, `ArchiveTab usage should not have initialRunner prop: ${usage}`);
	}
});

test('runner query param is DevRunnerTab-only contract', () => {
	assert.match(automationPage, /DevRunnerTab.*initialRunner|initialRunner.*DevRunnerTab/s);
	assert.doesNotMatch(automationPage, /<ArchiveTab[^/]*runner/);
});

test('scheduler plan archive card links to /scheduler/plan-archive', () => {
	assert.match(schedulerListTab, /href="\/scheduler\/plan-archive"/);
	assert.doesNotMatch(schedulerListTab, /href="\/plans\?tab=archive"/);
});

test('scheduler plan archive link label is 운영 not 상세', () => {
	assert.match(schedulerListTab, /Plan Archive 운영/);
	assert.doesNotMatch(schedulerListTab, /Plan Archive 상세/);
});
