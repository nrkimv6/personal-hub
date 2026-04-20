import assert from 'node:assert/strict';
import test from 'node:test';

import { buildExpoExportPayload } from '../src/routes/expo/utils/authorDraft.ts';

test('buildExpoExportPayload serializes booth drafts into API contract', () => {
  const payload = buildExpoExportPayload(
    'coffee-expo-2026',
    [
      {
        name: 'A-09',
        pin: { xNorm: 0.12, yNorm: 0.34 },
        createdAt: '2026-04-20T15:00:00+09:00',
      },
    ],
    '커피엑스포 2026',
  );

  assert.equal(payload.slug, 'coffee-expo-2026');
  assert.equal(payload.title, '커피엑스포 2026');
  assert.equal(payload.booths.length, 1);
  assert.deepEqual(payload.booths[0], {
    id: 'A-09',
    name: 'A-09',
    pin: { xNorm: 0.12, yNorm: 0.34 },
  });
});

test('buildExpoExportPayload includes exported_at timestamp', () => {
  const payload = buildExpoExportPayload('coffee-expo-2026', [], '커피엑스포 2026');

  assert.ok(payload.exported_at);
  assert.ok(Number.isFinite(new Date(payload.exported_at).getTime()));
});

test('buildExpoExportPayload keeps booth serialization stable across multiple drafts', () => {
  const payload = buildExpoExportPayload(
    'coffee-expo-2026',
    [
      {
        name: 'A-01',
        pin: { xNorm: 0.18, yNorm: 0.29 },
        createdAt: '2026-04-20T15:00:00+09:00',
      },
      {
        name: 'B-02',
        pin: { xNorm: 0.37, yNorm: 0.5 },
        createdAt: '2026-04-20T15:01:00+09:00',
      },
    ],
    '커피엑스포 2026',
  );

  assert.deepEqual(
    payload.booths.map((booth) => booth.id),
    ['A-01', 'B-02'],
  );
});

test('buildExpoExportPayload handles empty drafts without placeholder rows', () => {
  const payload = buildExpoExportPayload('coffee-expo-2026', [], '커피엑스포 2026');

  assert.deepEqual(payload.booths, []);
});
