import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const archiveTabPath = 'src/routes/plans/ArchiveTab.svelte';
const archiveTabSource = readFileSync(archiveTabPath, 'utf8');

const retrievalBindTargets = [
	'retrievalQ',
	'retrievalPath',
	'retrievalCategory',
	'retrievalTags',
	'retrievalIntent',
	'retrievalScope',
	'retrievalDateFrom',
	'retrievalDateTo',
	'retrievalRelationType',
	'retrievalLimit',
];

function findLetInitializer(name) {
	const match = archiveTabSource.match(new RegExp(`^[ \\t]*let[ \\t]+${name}[ \\t]*=([^\\r\\n]*)`, 'm'));
	return match?.[1].trimStart() ?? null;
}

function hasStateDeclaration(name) {
	return findLetInitializer(name)?.startsWith('$state(') === true;
}

function hasPlainLetDeclaration(name) {
	const initializer = findLetInitializer(name);
	return initializer != null && !initializer.startsWith('$state(');
}

test('ArchiveTab retrieval bind targets are Svelte runes state', () => {
	const failures = retrievalBindTargets.filter((name) => {
		return !hasStateDeclaration(name);
	});

	assert.deepEqual(
		failures,
		[],
		`${archiveTabPath}: Can only bind to state or props. Retrieval bind targets must be declared with $state(...): ${failures.join(', ')}`,
	);
});

test('ArchiveTab retrieval inputs do not bind to plain local lets', () => {
	const failures = retrievalBindTargets.filter((name) => {
		const hasBind = new RegExp(`bind:value=\\{${name}\\}`).test(archiveTabSource);
		return hasBind && hasPlainLetDeclaration(name);
	});

	assert.deepEqual(
		failures,
		[],
		`${archiveTabPath}: Can only bind to state or props. Plain local let declarations cannot back retrieval bind:value targets: ${failures.join(', ')}`,
	);
});

test('ArchiveTab local bind targets use runes state', () => {
	const declarationFailures = [];
	const bindPattern = /bind:(?:value|checked)=\{([A-Za-z_$][\w$]*)\}/g;

	for (const [, name] of archiveTabSource.matchAll(bindPattern)) {
		if (hasPlainLetDeclaration(name) && !hasStateDeclaration(name)) {
			declarationFailures.push(name);
		}
	}

	assert.deepEqual(
		[...new Set(declarationFailures)],
		[],
		`${archiveTabPath}: Can only bind to state or props. Local bind targets must use $state(...).`,
	);
});
