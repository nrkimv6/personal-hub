/**
 * expo author 시퀀서 단위 테스트.
 *
 * strict 충돌, skip 다음 번호 계산, overwrite 좌표 교체, undo 회귀 케이스를 검증한다.
 */
import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyOverwrite,
  buildNameFromNumber,
  detectCollision,
  findNextFreeNumber,
  hasDuplicate,
  hasDuplicateInDrafts,
  hasDuplicateInExisting,
  MAX_HISTORY,
  popHistory,
  pushHistory,
} from '../src/routes/expo/utils/authorSequencer.ts';
import type { ExpoBooth, ExpoDraftBooth, ExpoMapPin } from '../src/lib/types.ts';

// ---------------------------------------------------------------------------
// 헬퍼
// ---------------------------------------------------------------------------

const makeConfig = (prefix = 'A-', step = 1, padLength = 2) => ({
  prefix,
  step,
  padLength,
});

const makePin = (x = 0.5, y = 0.5): ExpoMapPin => ({ xNorm: x, yNorm: y });

const makeBooth = (id: string, name?: string): ExpoBooth =>
  ({ id, name: name ?? id, pin: makePin() } as ExpoBooth);

const makeDraft = (name: string, pin?: ExpoMapPin): ExpoDraftBooth => ({
  name,
  pin: pin ?? makePin(),
  createdAt: new Date().toISOString(),
  source: 'draft',
});

// ---------------------------------------------------------------------------
// buildNameFromNumber
// ---------------------------------------------------------------------------

test('buildNameFromNumber: 기본 prefix + zero-pad', () => {
  const cfg = makeConfig('A-', 1, 2);
  assert.equal(buildNameFromNumber(1, cfg), 'A-01');
  assert.equal(buildNameFromNumber(9, cfg), 'A-09');
  assert.equal(buildNameFromNumber(10, cfg), 'A-10');
});

test('buildNameFromNumber: padLength=3', () => {
  const cfg = makeConfig('B-', 1, 3);
  assert.equal(buildNameFromNumber(1, cfg), 'B-001');
  assert.equal(buildNameFromNumber(100, cfg), 'B-100');
});

test('buildNameFromNumber: step=5 시 번호 그대로 표현', () => {
  const cfg = makeConfig('C-', 5, 2);
  assert.equal(buildNameFromNumber(5, cfg), 'C-05');
  assert.equal(buildNameFromNumber(10, cfg), 'C-10');
});

// ---------------------------------------------------------------------------
// hasDuplicateInExisting / hasDuplicateInDrafts / hasDuplicate
// ---------------------------------------------------------------------------

test('hasDuplicateInExisting: id/name 모두 검사', () => {
  const existing = [makeBooth('A-01', 'A-01'), makeBooth('B-02', 'B-02')];
  assert.ok(hasDuplicateInExisting('A-01', existing));
  assert.ok(hasDuplicateInExisting('B-02', existing));
  assert.ok(!hasDuplicateInExisting('C-03', existing));
});

test('hasDuplicateInDrafts: 동일 이름 검사', () => {
  const drafts = [makeDraft('A-01'), makeDraft('A-02')];
  assert.ok(hasDuplicateInDrafts('A-01', drafts));
  assert.ok(!hasDuplicateInDrafts('A-03', drafts));
});

test('hasDuplicate: existing과 drafts 모두 검사', () => {
  const existing = [makeBooth('A-01')];
  const drafts = [makeDraft('A-02')];
  assert.ok(hasDuplicate('A-01', existing, drafts), 'existing booth 충돌');
  assert.ok(hasDuplicate('A-02', existing, drafts), 'draft 충돌');
  assert.ok(!hasDuplicate('A-03', existing, drafts), '충돌 없음');
});

// ---------------------------------------------------------------------------
// strict 모드: detectCollision
// ---------------------------------------------------------------------------

test('detectCollision: 충돌 없을 때 null 반환', () => {
  const existing = [makeBooth('A-01')];
  const drafts: ExpoDraftBooth[] = [];
  const result = detectCollision('A-02', makePin(), existing, drafts);
  assert.equal(result, null);
});

test('detectCollision: 기존 부스 충돌 시 inExistingBooth=true', () => {
  const existing = [makeBooth('A-01', 'A-01')];
  const drafts: ExpoDraftBooth[] = [];
  const result = detectCollision('A-01', makePin(), existing, drafts);
  assert.ok(result !== null, '충돌 감지 필요');
  assert.ok(result!.inExistingBooth);
  assert.ok(!result!.inDraft);
  assert.equal(result!.existingBoothName, 'A-01');
  assert.equal(result!.name, 'A-01');
});

test('detectCollision: draft 충돌 시 inDraft=true', () => {
  const existing: ExpoBooth[] = [];
  const drafts = [makeDraft('A-02')];
  const result = detectCollision('A-02', makePin(), existing, drafts);
  assert.ok(result !== null);
  assert.ok(!result!.inExistingBooth);
  assert.ok(result!.inDraft);
});

test('detectCollision: pendingPin이 결과에 포함된다', () => {
  const existing = [makeBooth('A-01')];
  const pin = makePin(0.3, 0.7);
  const result = detectCollision('A-01', pin, existing, []);
  assert.deepEqual(result!.pendingPin, pin);
});

// ---------------------------------------------------------------------------
// skip 모드: findNextFreeNumber
// ---------------------------------------------------------------------------

test('findNextFreeNumber: 충돌 없으면 fromNumber 그대로 반환', () => {
  const cfg = makeConfig('A-', 1, 2);
  const { number, skipped } = findNextFreeNumber(3, cfg, [], []);
  assert.equal(number, 3);
  assert.deepEqual(skipped, []);
});

test('findNextFreeNumber: A-01 충돌 시 A-02 반환', () => {
  const cfg = makeConfig('A-', 1, 2);
  const existing = [makeBooth('A-01')];
  const { number, skipped } = findNextFreeNumber(1, cfg, existing, []);
  assert.equal(number, 2);
  assert.deepEqual(skipped, ['A-01']);
});

test('findNextFreeNumber: 연속 충돌 시 건너뛴 목록 누적', () => {
  const cfg = makeConfig('A-', 1, 2);
  const existing = [makeBooth('A-01'), makeBooth('A-02'), makeBooth('A-03')];
  const { number, skipped } = findNextFreeNumber(1, cfg, existing, []);
  assert.equal(number, 4);
  assert.deepEqual(skipped, ['A-01', 'A-02', 'A-03']);
});

test('findNextFreeNumber: step=5 시 A-05 → A-10 건너뜀', () => {
  const cfg = makeConfig('A-', 5, 2);
  const existing = [makeBooth('A-05')];
  const { number, skipped } = findNextFreeNumber(5, cfg, existing, []);
  assert.equal(number, 10);
  assert.deepEqual(skipped, ['A-05']);
});

test('findNextFreeNumber: drafts도 충돌 대상에 포함', () => {
  const cfg = makeConfig('A-', 1, 2);
  const drafts = [makeDraft('A-01'), makeDraft('A-02')];
  const { number, skipped } = findNextFreeNumber(1, cfg, [], drafts);
  assert.equal(number, 3);
  assert.deepEqual(skipped, ['A-01', 'A-02']);
});

// ---------------------------------------------------------------------------
// overwrite 모드: applyOverwrite
// ---------------------------------------------------------------------------

test('applyOverwrite: draft에 동일 이름 있으면 좌표 교체', () => {
  const oldPin = makePin(0.1, 0.2);
  const newPin = makePin(0.8, 0.9);
  const drafts: ExpoDraftBooth[] = [
    { name: 'A-01', pin: oldPin, createdAt: '2026-01-01T00:00:00Z', source: 'draft' },
  ];

  const { drafts: next, wasNewEntry } = applyOverwrite('A-01', newPin, drafts);
  assert.ok(!wasNewEntry, '기존 draft 교체여야 한다');
  assert.equal(next.length, 1);
  assert.deepEqual(next[0].pin, newPin);
  assert.equal(next[0].source, 'overwrite');
  assert.deepEqual(next[0].overwrittenFrom, oldPin);
});

test('applyOverwrite: draft에 없으면 신규 항목 추가', () => {
  const pin = makePin(0.5, 0.6);
  const { drafts: next, wasNewEntry } = applyOverwrite('A-99', pin, []);
  assert.ok(wasNewEntry, '새 항목 추가여야 한다');
  assert.equal(next.length, 1);
  assert.equal(next[0].name, 'A-99');
  assert.equal(next[0].source, 'overwrite');
  assert.deepEqual(next[0].pin, pin);
});

test('applyOverwrite: 다른 draft에 영향 없음', () => {
  const drafts: ExpoDraftBooth[] = [
    { name: 'A-01', pin: makePin(0.1, 0.1), createdAt: '2026-01-01T00:00:00Z', source: 'draft' },
    { name: 'A-02', pin: makePin(0.2, 0.2), createdAt: '2026-01-01T00:00:00Z', source: 'draft' },
  ];
  const newPin = makePin(0.9, 0.9);
  const { drafts: next } = applyOverwrite('A-01', newPin, drafts);
  assert.equal(next.length, 2);
  // A-02는 그대로
  assert.deepEqual(next[1].pin, makePin(0.2, 0.2));
  assert.equal(next[1].source, 'draft');
});

test('applyOverwrite: overwrittenFrom에 이전 pin이 기록된다', () => {
  const prev = makePin(0.1, 0.2);
  const next_ = makePin(0.7, 0.8);
  const drafts: ExpoDraftBooth[] = [
    { name: 'A-01', pin: prev, createdAt: '2026-01-01T00:00:00Z', source: 'draft' },
  ];
  const { drafts: result } = applyOverwrite('A-01', next_, drafts);
  assert.deepEqual(result[0].overwrittenFrom, prev);
});

// ---------------------------------------------------------------------------
// undo 지원: pushHistory / popHistory
// ---------------------------------------------------------------------------

test('pushHistory: 이전 상태가 히스토리에 추가된다', () => {
  const d1 = [makeDraft('A-01')];
  const d2 = [makeDraft('A-01'), makeDraft('A-02')];
  const h0: ExpoDraftBooth[][] = [];
  const h1 = pushHistory(h0, d1);
  const h2 = pushHistory(h1, d2);
  assert.equal(h2.length, 2);
  assert.deepEqual(h2[0], d1);
  assert.deepEqual(h2[1], d2);
});

test('pushHistory: MAX_HISTORY 초과 시 오래된 항목 제거', () => {
  let history: ExpoDraftBooth[][] = [];
  for (let i = 0; i < MAX_HISTORY + 5; i++) {
    history = pushHistory(history, [makeDraft(`A-${i.toString().padStart(2, '0')}`)]);
  }
  assert.equal(history.length, MAX_HISTORY);
});

test('popHistory: 빈 히스토리에서 null 반환', () => {
  const { history: next, restored } = popHistory([]);
  assert.equal(restored, null);
  assert.equal(next.length, 0);
});

test('popHistory: 마지막 상태를 복원하고 히스토리를 줄인다', () => {
  const d1 = [makeDraft('A-01')];
  const d2 = [makeDraft('A-01'), makeDraft('A-02')];
  const history = [d1, d2];
  const { history: next, restored } = popHistory(history);
  assert.deepEqual(restored, d2);
  assert.equal(next.length, 1);
  assert.deepEqual(next[0], d1);
});

test('undo 회귀: strict 충돌 후 draft 없음 → undo해도 변화 없음', () => {
  // strict 충돌이 발생하면 draft를 추가하지 않으므로 undo할 게 없다
  const existing = [makeBooth('A-01')];
  const drafts: ExpoDraftBooth[] = [];
  const collision = detectCollision('A-01', makePin(), existing, drafts);
  assert.ok(collision !== null, '충돌 감지 확인');

  // drafts가 변하지 않았으므로 undo 히스토리도 없음
  const history: ExpoDraftBooth[][] = [];
  const { restored } = popHistory(history);
  assert.equal(restored, null);
});

test('undo 회귀: overwrite 후 undo → 이전 pin으로 복원', () => {
  const origPin = makePin(0.1, 0.2);
  const newPin = makePin(0.8, 0.9);
  const before: ExpoDraftBooth[] = [
    { name: 'A-01', pin: origPin, createdAt: '2026-01-01T00:00:00Z', source: 'draft' },
  ];

  // overwrite 전 히스토리 스냅샷 저장
  const history = pushHistory([], before);

  // overwrite 적용
  const { drafts: after } = applyOverwrite('A-01', newPin, before);
  assert.deepEqual(after[0].pin, newPin);

  // undo: 이전 상태 복원
  const { restored } = popHistory(history);
  assert.ok(restored !== null);
  assert.deepEqual(restored![0].pin, origPin);
});
