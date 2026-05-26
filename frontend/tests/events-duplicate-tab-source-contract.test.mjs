import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

const eventsPagePath = '../src/routes/events/+page.svelte';
const duplicateTabPath = '../src/lib/components/events/EventDuplicateTab.svelte';
const mergeModalPath = '../src/lib/components/events/EventMergePreviewModal.svelte';
const apiPath = '../src/lib/api/system.ts';

test('/events supports tab=duplicates and renders EventDuplicateTab', () => {
	const source = read(eventsPagePath);
	assert.match(source, /type\s+TabMode\s*=[^;]*'duplicates'/, `${eventsPagePath} TabMode must include duplicates`);
	assert.match(source, /ADMIN_DUPLICATES_TAB\s*:\s*TabMode\s*=\s*'duplicates'/, `${eventsPagePath} must define duplicates tab constant`);
	assert.match(source, /label:\s*'중복 검토'/, `${eventsPagePath} must expose a duplicate review tab label`);
	assert.match(source, /<EventDuplicateTab\s*\/>/, `${eventsPagePath} must render EventDuplicateTab for the duplicates tab`);
});

test('EventDuplicateTab calls candidates, preview, merge, and dismiss API surface', () => {
	const source = read(duplicateTabPath);
	const modal = read(mergeModalPath);
	const api = read(apiPath);

	assert.match(api, /eventDuplicateApi\s*=\s*{/, `${apiPath} must export eventDuplicateApi`);
	for (const method of ['candidates', 'preview', 'merge', 'dismiss']) {
		assert.match(api, new RegExp(`${method}\\s*:`), `${apiPath} eventDuplicateApi is missing ${method}()`);
	}
	assert.match(source, /eventDuplicateApi\.candidates/, `${duplicateTabPath} must load duplicate candidates`);
	assert.match(source, /eventDuplicateApi\.dismiss/, `${duplicateTabPath} must dismiss duplicate pairs`);
	assert.match(source, /<EventMergePreviewModal/, `${duplicateTabPath} must open merge preview modal`);
	assert.match(modal, /eventDuplicateApi\.preview/, `${mergeModalPath} must load merge preview`);
	assert.match(modal, /eventDuplicateApi\.merge/, `${mergeModalPath} must execute merge`);
});

test('merge execute button is disabled while in-flight', () => {
	const modal = read(mergeModalPath);
	assert.match(modal, /let\s+merging\s*=\s*\$state\(false\)/, `${mergeModalPath} must track in-flight merge state`);
	assert.match(modal, /disabled=\{!preview\s*\|\|\s*merging\}/, `${mergeModalPath} merge button must be disabled while merging`);
	assert.match(modal, /loading=\{merging\}/, `${mergeModalPath} merge button must show loading while merging`);
});
