import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

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

function extractFunctionBody(source, functionName) {
	const marker = `function ${functionName}`;
	const functionIndex = source.indexOf(marker);
	if (functionIndex === -1) {
		assert.fail(`Could not find function ${functionName}`);
	}

	const openBraceIndex = source.indexOf('{', functionIndex);
	if (openBraceIndex === -1) {
		assert.fail(`Could not find function body for ${functionName}`);
	}

	return extractBalancedBody(source, openBraceIndex, `function ${functionName}`);
}

function extractHandlerBody(source, marker) {
	const markerIndex = source.indexOf(marker);
	if (markerIndex === -1) {
		assert.fail(`Could not find handler marker ${marker}`);
	}

	const openBraceIndex = source.indexOf('{', markerIndex);
	if (openBraceIndex === -1) {
		assert.fail(`Could not find handler body for ${marker}`);
	}

	return extractBalancedBody(source, openBraceIndex, `handler ${marker}`);
}

test('api gate state keeps three-state recovery contract', () => {
	const src = read('../src/lib/server/api-gate-state.ts');
	assert.match(src, /type GateStateName = 'open' \| 'closed' \| 'recovering'/);
	assert.match(src, /const REQUIRED_READY_SUCCESSES = 3/);
	assert.match(src, /readySuccessCount >= REQUIRED_READY_SUCCESSES/);
	assert.match(src, /openGate\('auto-recovery'\)/);
	assert.match(src, /slice\(-MAX_RECENT_EVENTS\)/);
});

test('client api gate starts closed until local status is known', () => {
	const src = read('../src/lib/stores/apiGate.svelte.ts');
	assert.match(src, /const INITIAL_REASON = 'API 상태 확인 중'/);
	assert.match(src, /let state = \$state<GateStateName>\('recovering'\)/);
	assert.match(src, /let initialStatusSettled = false/);
	assert.match(src, /function applySnapshot\(snapshot: GateSnapshot\)[\s\S]+initialStatusSettled = true;/);
	assert.match(src, /async function ensureInitialStatus\(\)/);
	assert.match(src, /headers: \{ 'x-api-gate-bypass': '1' \}/);
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

test('api gate stream route guards close and enqueue races', () => {
	const stream = read('../src/routes/__local/api-gate/stream/+server.ts');
	const safeCloseBody = extractFunctionBody(stream, 'safeClose');
	const safeEnqueueBody = extractFunctionBody(stream, 'safeEnqueue');
	const abortBody = extractHandlerBody(stream, "addEventListener('abort'");
	const cancelBody = extractHandlerBody(stream, 'cancel()');

	assert.match(stream, /let streamClosed = false/);
	assert.match(stream, /function cleanup\(\)/);
	assert.match(stream, /function safeClose\(\)/);
	assert.match(stream, /function safeEnqueue\(eventName: string, data: unknown\)/);
	assert.match(safeCloseBody, /controller\.close\(\);/);
	assert.match(safeCloseBody, /\}\s*catch\s*\{/);
	assert.match(safeEnqueueBody, /if \(streamClosed\) return;/);
	assert.match(safeEnqueueBody, /controller\.enqueue\(encodeSse\(eventName, data\)\);/);
	assert.match(safeEnqueueBody, /\}\s*catch\s*\{[\s\S]+streamClosed = true;[\s\S]+cleanup\(\);/);
	assert.match(stream, /subscribe\(\(snapshot\) => \{[\s\S]+safeEnqueue\('gate_state', snapshot\)/);
	assert.match(stream, /setInterval\(\(\) => \{[\s\S]+safeEnqueue\('heartbeat', \{\}\)/);
	assert.match(abortBody, /safeClose\(\);/);
	assert.doesNotMatch(abortBody, /controller\.(?:close|enqueue)\(/);
	assert.match(cancelBody, /streamClosed = true;/);
	assert.match(cancelBody, /cleanup\(\);/);
	assert.doesNotMatch(cancelBody, /controller\.(?:close|enqueue)\(/);
});

test('client fetch guard blocks same-origin api calls and preserves bypasses', () => {
	const hook = read('../src/hooks.client.ts');
	const client = read('../src/lib/api/client.ts');
	assert.match(hook, /new ApiGateClosedError\(\)/);
	assert.match(hook, /path\.startsWith\('\/__local\/'\)/);
	assert.match(hook, /path\.startsWith\('\/_app\/'\)/);
	assert.match(hook, /GATE_BYPASS_PATHS\.includes/);
	assert.match(hook, /x-api-gate-bypass/);
	assert.match(hook, /shouldBlockApiRequestForGate\(url\.toString\(\)\)/);
	assert.match(client, /GATE_BLOCK_PATTERN\.test\(parsed\.pathname\)/);
	assert.match(client, /apiGate\.state !== 'open'/);
	assert.match(client, /const GATE_DIRECT_PORTS = new Set\(\['8000', '8001'\]\)/);
	assert.match(client, /export function shouldBlockApiRequestForGate/);
	assert.match(client, /await apiGate\.ensureInitialStatus\(\)/);
	assert.match(client, /await waitForApiGate\(url, options\)/);
	assert.match(client, /hasGateBypassHeader\(options\)/);
});

test('layout keeps svelte app mounted during api gate recovery', () => {
	const layout = read('../src/routes/+layout.svelte');
	assert.doesNotMatch(layout, /location\.reload\(\)/);
	assert.match(layout, /void authStore\.checkAuth\(\);/);
	assert.match(layout, /apiGate\.refreshStatus\(\)[\s\S]+\.finally\(\(\) => \{[\s\S]+authStore\.checkAuth\(\)/);
});

test('direct self restart uses explicit gate bypass header', () => {
	const src = read('../src/lib/api/system.ts');
	assert.match(src, /http:\/\/\$\{location\.hostname\}:\$\{port\}\/api\/v1\/system\/self-restart/);
	assert.match(src, /headers: \{ 'x-api-gate-bypass': '1' \}/);
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
