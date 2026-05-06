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

const analyzeBindTargets = [
	'queueAnalyzeProvider',
	'queueAnalyzeModel',
	'manualAnalyzeProvider',
	'manualAnalyzeModel',
	'manualAnalyzeTimeout',
];

const localBindTargets = [...retrievalBindTargets, ...analyzeBindTargets];

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

function scriptContent(source) {
	return source.match(/<script\b[^>]*>([\s\S]*?)<\/script>/)?.[1] ?? source;
}

function stripLineComments(line) {
	return line.replace(/\/\/.*$/, '');
}

function braceDelta(line) {
	const cleaned = stripLineComments(line)
		.replace(/'[^'\\]*(?:\\.[^'\\]*)*'/g, "''")
		.replace(/"[^"\\]*(?:\\.[^"\\]*)*"/g, '""')
		.replace(/`[^`\\]*(?:\\.[^`\\]*)*`/g, '``');
	return (cleaned.match(/\{/g) ?? []).length - (cleaned.match(/\}/g) ?? []).length;
}

function collectTopLevelLetNames(source) {
	const lines = scriptContent(source).split(/\r?\n/);
	const names = [];
	let depth = 0;

	lines.forEach((line) => {
		const depthBefore = depth;
		const match = line.match(/^\s*let\s+([A-Za-z_$][\w$]*)\b/);
		if (depthBefore === 0 && match) {
			names.push(match[1]);
		}
		depth = Math.max(0, depth + braceDelta(line));
	});

	return names;
}

function duplicates(values) {
	const seen = new Set();
	const duplicateValues = new Set();
	for (const value of values) {
		if (seen.has(value)) {
			duplicateValues.add(value);
		}
		seen.add(value);
	}
	return [...duplicateValues];
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

test('ArchiveTab analyze bind targets are Svelte runes state', () => {
	const failures = analyzeBindTargets.filter((name) => {
		return !hasStateDeclaration(name);
	});

	assert.deepEqual(
		failures,
		[],
		`${archiveTabPath}: Analyze bind targets must be declared with $state(...): ${failures.join(', ')}`,
	);
});

test('ArchiveTab retrieval inputs do not bind to plain local lets', () => {
	const failures = localBindTargets.filter((name) => {
		const hasBind = new RegExp(`bind:value=\\{${name}\\}`).test(archiveTabSource);
		return hasBind && hasPlainLetDeclaration(name);
	});

	assert.deepEqual(
		failures,
		[],
		`${archiveTabPath}: Can only bind to state or props. Plain local let declarations cannot back retrieval bind:value targets: ${failures.join(', ')}`,
	);
});

test('ArchiveTab top-level let declarations are unique', () => {
	const duplicateNames = duplicates(collectTopLevelLetNames(archiveTabSource));

	assert.deepEqual(
		duplicateNames,
		[],
		`${archiveTabPath}: Duplicate top-level let declarations cause Svelte parse errors: ${duplicateNames.join(', ')}`,
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
