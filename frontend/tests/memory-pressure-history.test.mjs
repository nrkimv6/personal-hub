import test from 'node:test';
import assert from 'node:assert/strict';
import {
  getMemoryPressureLevelMeta,
  formatMemoryPressureMb,
  formatMemoryPressureTimestamp,
  summarizeMemoryPressureProcesses,
  excerptMemoryPressureTree,
  renderMemoryPressureExcerpt,
  toggleStringSelection,
} from '../src/lib/memory-pressure-history.js';

test('memory pressure level metadata maps labels and classes', () => {
  const critical = getMemoryPressureLevelMeta('critical');
  assert.equal(critical.label, '위험');
  assert.match(critical.badgeClass, /red/);

  const fallback = getMemoryPressureLevelMeta('unknown');
  assert.equal(fallback.label, '긴급');
});

test('memory pressure mb formatting switches to gb at 1024', () => {
  assert.equal(formatMemoryPressureMb(499), '499 MB');
  assert.equal(formatMemoryPressureMb(1536), '1.5 GB');
});

test('memory pressure timestamp formatter handles invalid input', () => {
  assert.equal(formatMemoryPressureTimestamp('not-a-date'), 'not-a-date');
  assert.equal(formatMemoryPressureTimestamp(''), '-');
});

test('memory pressure process summary prefers the first entries', () => {
  const summary = summarizeMemoryPressureProcesses([
    { name: 'python.exe', memory_mb: 512.0 },
    { name: 'chrome.exe', memory_mb: 128.0 },
    { name: 'node.exe', memory_mb: 64.0 },
  ]);

  assert.equal(summary, 'python.exe (512 MB), chrome.exe (128 MB), node.exe (64 MB)');
});

test('memory pressure tree excerpt trims raw process trees to the requested lines', () => {
  const tree = Array.from({ length: 100 }, (_, idx) => `line-${idx + 1}`).join('\n');
  const excerpt = excerptMemoryPressureTree(tree, 80);

  assert.ok(excerpt.includes('line-80'));
  assert.ok(excerpt.endsWith('... (+20 lines)'));
  assert.ok(!excerpt.includes('line-100'));
});

test('memory pressure server excerpt passthrough preserves suffix text', () => {
  const excerpt = Array.from({ length: 80 }, (_, idx) => `line-${idx + 1}`).join('\n') + '\n... (+20 lines)';

  assert.equal(renderMemoryPressureExcerpt(excerpt), excerpt);
  assert.equal(renderMemoryPressureExcerpt(renderMemoryPressureExcerpt(excerpt)), excerpt);
});

test('memory pressure server excerpt passthrough normalizes empty values', () => {
  assert.equal(renderMemoryPressureExcerpt(null), '');
  assert.equal(renderMemoryPressureExcerpt(undefined), '');
  assert.equal(renderMemoryPressureExcerpt(''), '');
});

test('memory pressure raw helper rewrites server excerpts incorrectly', () => {
  const serverExcerpt = Array.from({ length: 80 }, (_, idx) => `line-${idx + 1}`).join('\n') + '\n... (+20 lines)';
  const rewrapped = excerptMemoryPressureTree(serverExcerpt, 80);

  assert.notEqual(rewrapped, serverExcerpt);
  assert.ok(rewrapped.endsWith('... (+1 lines)'));
  assert.ok(rewrapped.includes('line-80'));
});

test('toggle string selection adds and removes values', () => {
  assert.deepEqual(toggleStringSelection(['critical'], 'emergency'), ['critical', 'emergency']);
  assert.deepEqual(toggleStringSelection(['critical', 'emergency'], 'critical'), ['emergency']);
});
