import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const confirmStorePath = '../src/lib/stores/confirm.ts';
const confirmModalPath = '../src/lib/components/ConfirmModal.svelte';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

function extractBalancedBody(source, openBraceIndex, label) {
	let depth = 0;
	for (let index = openBraceIndex; index < source.length; index += 1) {
		const char = source[index];
		if (char === '{') {
			depth += 1;
		} else if (char === '}') {
			depth -= 1;
			if (depth === 0) {
				return source.slice(openBraceIndex + 1, index);
			}
		}
	}
	assert.fail(`Could not find closing brace for ${label}`);
}

function extractFunctionBody(source, functionName, filePath) {
	const marker = `function ${functionName}`;
	const functionIndex = source.indexOf(marker);
	assert.notEqual(functionIndex, -1, `${filePath} is missing function ${functionName}()`);

	const openBraceIndex = source.indexOf('{', functionIndex);
	assert.notEqual(openBraceIndex, -1, `${filePath} is missing a body for function ${functionName}()`);

	return extractBalancedBody(source, openBraceIndex, `${filePath} function ${functionName}()`);
}

function extractConfirmVariants(source) {
	const match = source.match(/export\s+type\s+ConfirmVariant\s*=\s*([^;]+);/);
	assert.ok(match, `${confirmStorePath} is missing export type ConfirmVariant`);
	return Array.from(match[1].matchAll(/'([^']+)'/g), ([, variant]) => variant);
}

test('ConfirmVariant keeps default warning and danger contract', () => {
	const variants = extractConfirmVariants(read(confirmStorePath));
	for (const requiredVariant of ['default', 'warning', 'danger']) {
		assert.ok(
			variants.includes(requiredVariant),
			`${confirmStorePath} ConfirmVariant is missing '${requiredVariant}'`
		);
	}
});

test('ConfirmModal button class handles warning variant', () => {
	const functionBody = extractFunctionBody(read(confirmModalPath), 'confirmButtonClass', confirmModalPath);
	assert.match(
		functionBody,
		/case\s+['"]warning['"]:/,
		`${confirmModalPath} confirmButtonClass() is missing a warning branch`
	);
	assert.match(
		functionBody,
		/bg-warning\b/,
		`${confirmModalPath} confirmButtonClass() warning branch is missing bg-warning`
	);
	assert.match(
		functionBody,
		/text-warning-foreground\b/,
		`${confirmModalPath} confirmButtonClass() warning branch is missing text-warning-foreground`
	);
});
