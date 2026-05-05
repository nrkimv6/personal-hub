/**
 * author 시퀀서 핵심 로직 — 순수 함수 모음.
 *
 * BoothAuthorPanel.svelte의 상태 머신 중 테스트 가능한 순수 함수 부분을
 * 이 모듈로 분리한다. DOM/Svelte 의존 없이 node:test 환경에서 실행 가능하다.
 */

import type { ExpoBooth, ExpoDraftBooth, ExpoMapPin } from '$lib/types';

// ---------------------------------------------------------------------------
// 이름 생성
// ---------------------------------------------------------------------------

export interface NameConfig {
  prefix: string;
  padLength: number;
  step: number;
}

export function buildNameFromNumber(num: number, config: NameConfig): string {
  return `${config.prefix}${String(num).padStart(Math.max(1, config.padLength), '0')}`;
}

// ---------------------------------------------------------------------------
// 중복 판정
// ---------------------------------------------------------------------------

export function hasDuplicateInExisting(name: string, existingBooths: ExpoBooth[]): boolean {
  return existingBooths.some((b) => b.id === name || b.name === name);
}

export function hasDuplicateInDrafts(name: string, drafts: ExpoDraftBooth[]): boolean {
  return drafts.some((d) => d.name === name);
}

export function hasDuplicate(
  name: string,
  existingBooths: ExpoBooth[],
  drafts: ExpoDraftBooth[]
): boolean {
  return hasDuplicateInExisting(name, existingBooths) || hasDuplicateInDrafts(name, drafts);
}

// ---------------------------------------------------------------------------
// skip 모드: 다음 빈 번호 탐색
// ---------------------------------------------------------------------------

export interface FindNextFreeResult {
  number: number;
  skipped: string[];
}

/**
 * fromNumber부터 step씩 증가하며 충돌 없는 첫 번째 번호를 반환한다.
 * 최대 1000회 탐색 후 후보가 없으면 해당 번호를 그대로 반환한다.
 */
export function findNextFreeNumber(
  fromNumber: number,
  config: NameConfig,
  existingBooths: ExpoBooth[],
  drafts: ExpoDraftBooth[]
): FindNextFreeResult {
  const skipped: string[] = [];
  let candidate = fromNumber;
  for (let i = 0; i < 1000; i++) {
    const name = buildNameFromNumber(candidate, config);
    if (!hasDuplicate(name, existingBooths, drafts)) {
      return { number: candidate, skipped };
    }
    skipped.push(name);
    candidate += config.step;
  }
  return { number: candidate, skipped };
}

// ---------------------------------------------------------------------------
// overwrite 모드: 동일 이름의 draft 좌표 교체
// ---------------------------------------------------------------------------

export interface OverwriteResult {
  drafts: ExpoDraftBooth[];
  /** draft를 새로 추가했는지 (기존 draft 교체가 아닌 경우) */
  wasNewEntry: boolean;
}

/**
 * `name`이 이미 drafts에 있으면 좌표를 교체하고,
 * 없으면 existingBooths override용 draft를 새로 추가한다.
 */
export function applyOverwrite(
  name: string,
  pin: ExpoMapPin,
  drafts: ExpoDraftBooth[]
): OverwriteResult {
  const now = new Date().toISOString();
  const draftIdx = drafts.findIndex((d) => d.name === name);

  if (draftIdx >= 0) {
    const prev = drafts[draftIdx];
    const next: ExpoDraftBooth[] = drafts.map((d, idx) =>
      idx === draftIdx
        ? {
            ...d,
            pin,
            updatedAt: now,
            source: 'overwrite' as const,
            overwrittenFrom: prev.pin,
          }
        : d
    );
    return { drafts: next, wasNewEntry: false };
  }

  // 정적 booth override
  const next: ExpoDraftBooth[] = [
    ...drafts,
    {
      name,
      pin,
      createdAt: now,
      updatedAt: now,
      source: 'overwrite' as const,
    },
  ];
  return { drafts: next, wasNewEntry: true };
}

// ---------------------------------------------------------------------------
// strict 모드: 충돌 판정 결과
// ---------------------------------------------------------------------------

export interface CollisionInfo {
  name: string;
  inExistingBooth: boolean;
  inDraft: boolean;
  existingBoothName?: string;
  pendingPin: ExpoMapPin;
}

/**
 * strict 모드에서 candidateName의 충돌 여부를 검사한다.
 * 충돌 없으면 null 반환.
 */
export function detectCollision(
  candidateName: string,
  pin: ExpoMapPin,
  existingBooths: ExpoBooth[],
  drafts: ExpoDraftBooth[]
): CollisionInfo | null {
  if (!hasDuplicate(candidateName, existingBooths, drafts)) return null;

  return {
    name: candidateName,
    inExistingBooth: hasDuplicateInExisting(candidateName, existingBooths),
    inDraft: hasDuplicateInDrafts(candidateName, drafts),
    existingBoothName: existingBooths.find(
      (b) => b.id === candidateName || b.name === candidateName
    )?.name,
    pendingPin: pin,
  };
}

// ---------------------------------------------------------------------------
// undo 지원: 히스토리 관리
// ---------------------------------------------------------------------------

export const MAX_HISTORY = 50;

export function pushHistory(
  history: ExpoDraftBooth[][],
  current: ExpoDraftBooth[]
): ExpoDraftBooth[][] {
  return [...history.slice(-MAX_HISTORY + 1), current];
}

export function popHistory(
  history: ExpoDraftBooth[][]
): { history: ExpoDraftBooth[][]; restored: ExpoDraftBooth[] | null } {
  if (history.length === 0) return { history, restored: null };
  const next = history.slice(0, -1);
  const restored = history[history.length - 1];
  return { history: next, restored };
}
