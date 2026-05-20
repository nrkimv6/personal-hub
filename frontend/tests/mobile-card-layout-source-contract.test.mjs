import { readFileSync } from 'fs';
import { dirname, join, resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(__dirname, '..');

let passed = 0;
let failed = 0;

function assert(condition, message) {
	if (condition) {
		console.log(`  ✓ ${message}`);
		passed += 1;
	} else {
		console.error(`  ✗ ${message}`);
		failed += 1;
	}
}

function read(relativePath) {
	return readFileSync(join(frontendRoot, relativePath), 'utf-8');
}

function hasMobileCards(source) {
	return source.includes('md:hidden') && /<article\b/.test(source);
}

function hasDesktopTable(source) {
	return source.includes('hidden') && source.includes('md:block') && /<table\b/.test(source);
}

console.log('mobile card layout source contract');

const requiredContracts = [
	'src/routes/collect/VideoDownloadsTab.svelte',
	'src/routes/collect/history/+page.svelte',
	'src/routes/writing/WritingTab.svelte',
	'src/routes/automation/GitReposTab.svelte',
	'src/routes/scheduler/RunHistoryTab.svelte',
	'src/routes/system/BootHistoryTab.svelte',
	'src/routes/llm/components/LlmRequestsPanel.svelte'
];

for (const file of requiredContracts) {
	const source = read(file);
	assert(hasMobileCards(source), `${file}: renders mobile cards`);
	assert(hasDesktopTable(source), `${file}: keeps desktop-only table`);
}

const videoDownloads = read('src/routes/collect/VideoDownloadsTab.svelte');
const firstMobileCard = videoDownloads.indexOf('md:hidden');
const desktopTable = videoDownloads.indexOf('<table class="w-full">');
assert(firstMobileCard >= 0 && desktopTable > firstMobileCard, 'collect videos: mobile card appears before table markup');
assert(
	videoDownloads.includes('hidden bg-white rounded-lg border border-border overflow-hidden md:block'),
	'collect videos: desktop table wrapper is hidden on mobile'
);

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
