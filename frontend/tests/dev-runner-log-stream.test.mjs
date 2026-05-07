import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/dev-runner/log-stream.svelte.ts", import.meta.url),
  "utf8",
);
const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

test("LogStream owns SSE connection state and EventSource lifecycle", () => {
  assert.match(source, /export class LogStream/);
  assert.match(source, /connected = \$state<'connected' \| 'disconnected'>/);
  assert.match(source, /sseStarted = \$state\(false\)/);
  assert.match(source, /reconnectCount = \$state\(0\)/);
  assert.match(source, /redisAvailable = \$state\(false\)/);
  assert.match(source, /private eventSource: EventSource \| null = null/);
  assert.match(source, /devRunnerLogApi\.connectMergeStream\(runnerId\)/);
  assert.match(source, /devRunnerLogApi\.connectStream\(runnerId, this\.options\.getSinceLine\(\)\)/);
});

test("LogViewer delegates stream UI state and reconnect methods to LogStream", () => {
  assert.match(logViewer, /const stream = new LogStream\(\{/);
  assert.match(logViewer, /let connected = \$derived\(stream\.connected\)/);
  assert.match(logViewer, /let reconnectCount = \$derived\(stream\.reconnectCount\)/);
  assert.match(logViewer, /let redisAvailable = \$derived\(stream\.redisAvailable\)/);
  assert.match(logViewer, /await stream\.start\(\)/);
  assert.match(logViewer, /stream\.stop\(\)/);
  assert.match(logViewer, /void stream\.reconnectForModeSwitch/);
  assert.match(logViewer, /stream\.complete\(reason\)/);
});
