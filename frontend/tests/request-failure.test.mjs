import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyRequestFailure } from '../src/lib/api/requestFailure.js';

test('classifyRequestFailure returns abort for AbortError', () => {
  const result = classifyRequestFailure(new DOMException('aborted', 'AbortError'), '/api/v1/test');
  assert.equal(result.kind, 'abort');
  assert.equal(result.error.name, 'AbortError');
});

test('classifyRequestFailure returns timeout for timeout errors', () => {
  const result = classifyRequestFailure(new Error('요청 타임아웃 (30000ms): /api/v1/test'), '/api/v1/test');
  assert.equal(result.kind, 'timeout');
});

test('classifyRequestFailure returns connection for network errors', () => {
  const result = classifyRequestFailure(new Error('fetch failed'), '/api/v1/test');
  assert.equal(result.kind, 'connection');
  assert.equal(result.message, 'API 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.');
});
