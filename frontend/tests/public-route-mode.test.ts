import assert from 'node:assert/strict';
import test from 'node:test';
import {
  getExpoRouteContract,
  getLocalhostRouteModeFallback
} from '../src/lib/utils/publicRouteMode.ts';

test('localhost preview port resolves to public mode', () => {
  assert.equal(getLocalhostRouteModeFallback('localhost', '6100'), 'public');
  assert.equal(getLocalhostRouteModeFallback('127.0.0.2', '6100'), 'public');
});

test('localhost non-preview ports resolve to admin dev mode', () => {
  assert.equal(getLocalhostRouteModeFallback('localhost', '6101'), 'admin');
  assert.equal(getLocalhostRouteModeFallback('127.0.0.1', '5173'), 'admin');
});

test('expo contract blocks author and workspace in public preview', () => {
  const contract = getExpoRouteContract({
    isAdmin: true,
    mode: 'admin',
    url: new URL('http://localhost:6100/events?tab=expo')
  });

  assert.equal(contract.isPublicPreview, true);
  assert.equal(contract.canOpenExpoAdminWorkspace, false);
  assert.equal(contract.shouldRedirectExpoAuthor, true);
});

test('expo contract allows workspace on admin dev origin', () => {
  const contract = getExpoRouteContract({
    isAdmin: false,
    url: new URL('http://localhost:6101/events?tab=expo')
  });

  assert.equal(contract.isLocalAdminDev, true);
  assert.equal(contract.canOpenExpoAdminWorkspace, true);
  assert.equal(contract.shouldRedirectExpoAuthor, false);
});
