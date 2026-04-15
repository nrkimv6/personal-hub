import assert from 'node:assert/strict';
import test from 'node:test';
import {
  clampPan,
  clampZoom,
  computePinchScale,
  toNormalizedPoint,
  toViewPoint
} from '../src/routes/expo/utils/mapTransform.ts';

test('toViewPoint converts normalized coordinates into viewport pixels', () => {
  assert.deepEqual(toViewPoint(0.25, 0.75, 1200, 800), {
    x: 300,
    y: 600
  });
});

test('toNormalizedPoint clamps coordinates into 0..1 space', () => {
  assert.deepEqual(toNormalizedPoint(1500, -40, 1200, 800), {
    xNorm: 1,
    yNorm: 0
  });
});

test('computePinchScale returns ratio between distances', () => {
  assert.equal(computePinchScale(100, 160), 1.6);
  assert.equal(computePinchScale(0, 160), 1);
});

test('clampZoom keeps zoom within min/max bounds', () => {
  assert.equal(clampZoom(0.6, 1, 4), 1);
  assert.equal(clampZoom(2.25, 1, 4), 2.25);
  assert.equal(clampZoom(6, 1, 4), 4);
});

test('clampPan keeps translated content inside viewport', () => {
  assert.deepEqual(
    clampPan(-900, 120, {
      viewportWidth: 400,
      viewportHeight: 300,
      contentWidth: 1000,
      contentHeight: 700
    }),
    {
      panX: -600,
      panY: 0
    }
  );
});
