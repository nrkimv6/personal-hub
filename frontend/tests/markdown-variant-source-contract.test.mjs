import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

const markdownVariantsSource = read('../src/lib/components/markdown/markdownVariants.ts');
const markdownContentSource = read('../src/lib/components/markdown/MarkdownContent.svelte');
const filePreviewModalSource = read('../src/routes/file-search/MarkdownPreviewModal.svelte');
const resultListSource = read('../src/routes/file-search/ResultList.svelte');
const noteFormModalSource = read('../src/routes/notes/components/NoteFormModal.svelte');
const noteDetailModalSource = read('../src/routes/notes/components/NoteDetailModal.svelte');
const reportPageSource = read('../src/routes/reports/[id]/+page.svelte');

test('markdown variants expose a dedicated file preview boundary', () => {
	assert.match(
		markdownVariantsSource,
		/export type MarkdownContentVariant = 'compact' \| 'default' \| 'document' \| 'filePreview' \| 'plan';/
	);
	assert.match(markdownVariantsSource, /filePreview:\s*\[/);
	assert.match(markdownVariantsSource, /max-w-\[78ch\]/);
	assert.match(markdownVariantsSource, /prose-blockquote:bg-muted\/40/);
	assert.match(markdownVariantsSource, /prose-pre:bg-muted/);
	assert.match(markdownVariantsSource, /prose-table:text-xs/);
});

test('file search keeps inline and modal markdown previews separate', () => {
	assert.match(
		resultListSource,
		/<MarkdownContent\s+content=\{previewCache\[file\.file_path\]\.content\}\s+variant="compact"/
	);
	assert.match(
		filePreviewModalSource,
		/<MarkdownContent\s+content=\{preview\.content\}\s+variant="filePreview"/
	);
});

test('compact markdown preview has explicit light panel contrast defenses', () => {
	const compactMatch = markdownVariantsSource.match(/compact:\s*\[([\s\S]*?)\]\.join\(' '\),\s*default:/);
	assert.ok(compactMatch, 'compact variant should stay as a joined class list');
	const compactClasses = compactMatch[1];

	for (const requiredClass of [
		'text-foreground',
		'prose-headings:text-foreground',
		'prose-code:text-foreground',
		'prose-pre:text-foreground',
		'prose-table:text-xs',
		'prose-th:text-foreground',
		'prose-td:text-foreground',
	]) {
		assert.match(compactClasses, new RegExp(requiredClass.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
	}
	assert.doesNotMatch(compactClasses, /dark:prose-invert/);
});

test('notes and reports keep their existing markdown variant policy', () => {
	assert.match(noteFormModalSource, /<MarkdownContent\s+content=\{content\}\s+variant="default"/);
	assert.match(noteDetailModalSource, /class=\{variantClasses\.default\}/);
	assert.match(reportPageSource, /<MarkdownContent content=\{report\.content\} variant="document" \/>/);
});

test('shared MarkdownContent renderer ownership is unchanged for this focused readability pass', () => {
	assert.match(
		markdownContentSource,
		/import \{ renderMarkdown \} from '\.\.\/\.\.\/\.\.\/routes\/notes\/utils\/markdown';/
	);
});
