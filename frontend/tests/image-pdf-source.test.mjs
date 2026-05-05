import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import test from 'node:test';

const apiSource = await readFile(new URL('../src/lib/api/image-pdf.ts', import.meta.url), 'utf8');
const pageSource = await readFile(new URL('../src/routes/file-search/+page.svelte', import.meta.url), 'utf8');
const tabSource = await readFile(new URL('../src/routes/file-search/ImagePdfTab.svelte', import.meta.url), 'utf8');

test('image-pdf API sends backend form field names', () => {
	assert.match(apiSource, /form\.append\('preserve_dpi'/);
	assert.match(apiSource, /form\.append\('output_name'/);
	assert.match(apiSource, /parseContentDispositionFilename/);
});

test('file-search registers image-pdf tab and component', () => {
	assert.match(pageSource, /'image-pdf'/);
	assert.match(pageSource, /ImagePdfTab/);
	assert.match(pageSource, /이미지 → PDF/);
});

test('ImagePdfTab uses accessible controls and lucide icons', () => {
	assert.match(tabSource, /for="image-pdf-white"/);
	assert.match(tabSource, /for="image-pdf-black"/);
	assert.match(tabSource, /from 'lucide-svelte'/);
	assert.doesNotMatch(tabSource, /[📄🖼️✅❌]/u);
});
