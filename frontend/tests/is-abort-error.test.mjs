import test from 'node:test';
import assert from 'node:assert/strict';
import { isAbortError } from '../src/lib/utils/isAbortError.js';

test('isAbortError returns true for AbortError instances', () => {
  assert.equal(isAbortError(new DOMException('aborted', 'AbortError')), true);
});

test('isAbortError returns false for normal errors', () => {
  assert.equal(isAbortError(new Error('network down')), false);
});

test('isAbortError returns false for non-errors', () => {
  assert.equal(isAbortError(null), false);
  assert.equal(isAbortError({ name: 'AbortError' }), false);
});
