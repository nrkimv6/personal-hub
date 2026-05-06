import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const archiveTabPath = 'src/routes/plans/ArchiveTab.svelte';
const residualStatePath = 'src/routes/plans/archive-tab/planArchiveResidualState.svelte.ts';
const archiveTabSource = readFileSync(archiveTabPath, 'utf8');
const residualStateSource = readFileSync(residualStatePath, 'utf8');
let svelteCompile = null;
let svelteCompilerLoadError = null;

try {
	({ compile: svelteCompile } = await import('svelte/compiler'));
} catch (error) {
	svelteCompilerLoadError = error;
}

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

const localBindTargets = [...retrievalBindTargets];

function findLetInitializer(name) {
	const match = residualStateSource.match(new RegExp(`^[ \\t]*${name}[ \\t]*=([^\\r\\n]*)`, 'm'));
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

function formatSvelteCompileError(error) {
	const details = [
		error?.message,
		error?.code ? `code: ${error.code}` : null,
		error?.start ? `start: ${error.start.line}:${error.start.column}` : null,
		error?.end ? `end: ${error.end.line}:${error.end.column}` : null,
		error?.frame,
	].filter(Boolean);
	return details.join('\n');
}

test('ArchiveTab Svelte markup parses', {
	skip: svelteCompile ? false : `svelte/compiler unavailable: ${svelteCompilerLoadError?.code ?? svelteCompilerLoadError?.message ?? 'unknown'}`,
}, () => {
	try {
		svelteCompile(archiveTabSource, {
			filename: archiveTabPath,
			generate: false,
		});
	} catch (error) {
		assert.fail(`${archiveTabPath}: Svelte markup must parse cleanly.\n${formatSvelteCompileError(error)}`);
	}
});

test('planArchiveResidualState retrieval bind targets are Svelte runes state', () => {
	const failures = retrievalBindTargets.filter((name) => {
		return !hasStateDeclaration(name);
	});

	assert.deepEqual(
		failures,
		[],
		`${residualStatePath}: Retrieval bind targets must be declared with $state(...): ${failures.join(', ')}`,
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

test('planArchiveResidualState does not keep analyze bind targets', () => {
	const forbidden = [
		'queueAnalyzeProvider',
		'queueAnalyzeModel',
		'manualAnalyzeProvider',
		'manualAnalyzeModel',
		'manualAnalyzeTimeout',
	];
	const found = forbidden.filter((name) => residualStateSource.includes(name));

	assert.deepEqual(
		found,
		[],
		`${residualStatePath}: Analyze bind state belongs to scheduler page, not ArchiveTab residual state.`,
	);
});
