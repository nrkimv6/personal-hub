import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/lib/dev-runner/log-parse.ts", import.meta.url),
  "utf8",
);
const logViewer = readFileSync(
  new URL("../src/lib/components/dev-runner/LogViewer.svelte", import.meta.url),
  "utf8",
);

test("log-parse owns wrapper, header-only, separator, and parseLine contracts", () => {
  assert.match(source, /export const WRAPPER_PREFIX_PATTERN = \/\^\\\[\(PR\|PS\)/);
  assert.match(source, /export const HEADER_ONLY_TAGS = new Set\(\[/);
  assert.match(source, /export const SEPARATOR_PATTERN = '════════════════'/);
  assert.match(source, /export function parseLine/);
  assert.match(source, /head\.replace\(WRAPPER_PREFIX_PATTERN/);
  assert.match(source, /strippedHead\.match\(MERGE_TAG_PATTERN\)/);
});

test("LogViewer keeps line sequence ownership while delegating parsing", () => {
  assert.match(logViewer, /return createParsedLineId\(lineSequence, tag, timestamp, raw\)/);
  assert.match(logViewer, /return parseRawLine\(text, isStale, createLineId\)/);
  assert.match(logViewer, /buildParsedSessionSeparator\(identity, createLineId\)/);
});
