import { existsSync, readdirSync, readFileSync, statSync } from 'fs';
import { dirname, join, resolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(__dirname, '..');
const routesRoot = join(frontendRoot, 'src/routes');
const monitoringTypesFile = join(frontendRoot, 'src/lib/types/monitoring.ts');

let passed = 0;
let failed = 0;

function assert(condition, msg) {
	if (condition) {
		console.log(`  ✓ ${msg}`);
		passed += 1;
	} else {
		console.error(`  ✗ ${msg}`);
		failed += 1;
	}
}

function walkSvelteFiles(dir, files = []) {
	for (const entry of readdirSync(dir)) {
		const fullPath = join(dir, entry);
		const stats = statSync(fullPath);
		if (stats.isDirectory()) {
			walkSvelteFiles(fullPath, files);
		} else if (entry.endsWith('.svelte')) {
			files.push(fullPath);
		}
	}
	return files;
}

function routeFileForHref(href) {
	const cleanHref = href.split('?')[0].replace(/^\/+|\/+$/g, '');
	return join(routesRoot, cleanHref, '+page.svelte');
}

function displayPath(file) {
	return file.replace(frontendRoot + '\\', 'frontend\\').replaceAll('/', '\\');
}

function read(file) {
	return readFileSync(file, 'utf-8');
}

// Keep this empty unless a route is intentionally outside the page shell system.
// Any entry must include a removal condition in the reason.
const createHrefShellAllowlist = new Map([
	// ['/example', 'remove after route is migrated to PageHeader or TabbedPageLayout'],
]);

console.log('layout surface source contract');

const directH1Violations = walkSvelteFiles(routesRoot)
	.map((file) => ({ file, source: read(file) }))
	.filter(({ source }) => /<h1(\s|>)/.test(source));

assert(
	directH1Violations.length === 0,
	`direct-h1: expected 0 route-level <h1>, found ${directH1Violations.map((v) => displayPath(v.file)).join(', ') || 'none'}`
);

const monitoringTypes = read(monitoringTypesFile);
const createHrefs = [...monitoringTypes.matchAll(/createHref:\s*'([^']+)'/g)].map((match) => match[1]);
const uniqueCreateHrefs = [...new Set(createHrefs)];

for (const href of uniqueCreateHrefs) {
	if (createHrefShellAllowlist.has(href)) {
		console.log(`  - createHref-shell-allowlist: ${href} (${createHrefShellAllowlist.get(href)})`);
		continue;
	}

	const routeFile = routeFileForHref(href);
	const exists = existsSync(routeFile);
	assert(exists, `createHref-shell-missing: ${href} has route file ${displayPath(routeFile)}`);
	if (!exists) continue;

	const source = read(routeFile);
	assert(
		/\b(PageHeader|TabbedPageLayout)\b/.test(source),
		`createHref-shell-missing: ${href} route uses PageHeader or TabbedPageLayout`
	);
}

const monitoredRouteContracts = [
	{ href: '/monitoring', shell: 'TabbedPageLayout' },
	{ href: '/popply', shell: 'TabbedPageLayout' },
	{ href: '/events', shell: 'TabbedPageLayout' },
];

for (const { href, shell } of monitoredRouteContracts) {
	const routeFile = routeFileForHref(href);
	const source = read(routeFile);
	assert(source.includes(shell), `raw-main-container: ${href} uses ${shell}`);
	assert(
		source.includes('containerClass="space-y-3 p-4 md:p-6"'),
		`raw-main-container: ${href} uses compact shared containerClass`
	);
	assert(!/<main\b/.test(source), `raw-main-container: ${href} has no route-level raw <main>`);
	assert(!/<header\b/.test(source), `raw-header: ${href} has no route-level raw <header>`);
}

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
