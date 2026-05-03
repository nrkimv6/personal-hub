import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('api gate state keeps three-state recovery contract', () => {
	const src = read('../src/lib/server/api-gate-state.ts');
	assert.match(src, /type GateStateName = 'open' \| 'closed' \| 'recovering'/);
	assert.match(src, /const REQUIRED_READY_SUCCESSES = 3/);
	assert.match(src, /readySuccessCount >= REQUIRED_READY_SUCCESSES/);
	assert.match(src, /openGate\('auto-recovery'\)/);
	assert.match(src, /slice\(-MAX_RECENT_EVENTS\)/);
});

test('api gate local routes expose status close open and stream', () => {
	const status = read('../src/routes/__local/api-gate/status/+server.ts');
	const close = read('../src/routes/__local/api-gate/close/+server.ts');
	const open = read('../src/routes/__local/api-gate/open/+server.ts');
	const stream = read('../src/routes/__local/api-gate/stream/+server.ts');

	assert.match(status, /getGateSnapshot/);
	assert.match(close, /assertLocalRequest/);
	assert.match(close, /already_closed/);
	assert.match(open, /assertLocalRequest/);
	assert.match(stream, /text\/event-stream/);
	assert.match(stream, /event: \$\{event\}\\ndata:/);
});

test('api gate local routes use generic RequestEvent source', () => {
	const close = read('../src/routes/__local/api-gate/close/+server.ts');
	const open = read('../src/routes/__local/api-gate/open/+server.ts');
	const stream = read('../src/routes/__local/api-gate/stream/+server.ts');

	for (const source of [close, open, stream]) {
		assert.doesNotMatch(source, /from ['"]\.\/\$types['"]/);
		assert.match(source, /RequestEvent[\s\S]+from ['"]@sveltejs\/kit['"]/);
	}
});

test('client fetch guard blocks same-origin api calls and preserves bypasses', () => {
	const hook = read('../src/hooks.client.ts');
	assert.match(hook, /GATE_BLOCK_PATTERN\.test\(url\.pathname\)/);
	assert.match(hook, /apiGate\.state !== 'open'/);
	assert.match(hook, /new ApiGateClosedError\(\)/);
	assert.match(hook, /path\.startsWith\('\/__local\/'\)/);
	assert.match(hook, /path\.startsWith\('\/_app\/'\)/);
	assert.match(hook, /GATE_BYPASS_PATHS\.includes/);
	assert.match(hook, /x-api-gate-bypass/);
});

test('api gate singleton does not create component effects at module scope', () => {
	const store = read('../src/lib/stores/apiGate.svelte.ts');
	assert.doesNotMatch(store, /\$effect\s*\(/);
	assert.match(store, /scheduleStaleTimer\(\)/);
	assert.match(store, /clearStaleTimer\(\)/);
});

test('restart-api closes frontend gate before self restart', () => {
	const src = read('../../scripts/services/browser_worker_runtime/api_actions.py');
	assert.match(src, /def _close_api_gate\(api_port: int\)/);
	assert.match(src, /http:\/\/127\.0\.0\.1:\{frontend_port\}\/__local\/api-gate\/close/);
	assert.match(src, /_close_api_gate\(target\.api_port\)[\s\S]+if not manager\._check_wmi_health/);
});
