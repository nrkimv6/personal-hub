/**
 * Eventus history slots_info display helpers.
 *
 * `slots_info` 내부 항목은 serialize_slot()이 기록한 camelCase 키를 사용하며,
 * 정확한 좌석 수는 Eventus HTML에서 알 수 없으므로 available_count는
 * 열린 슬롯 sentinel 합계다 (availableCountKnown === false).
 */

export interface EventusHistorySlot {
  /** Eventus bundle ID */
  bundleId: string;
  /** 시간대 label (예: "10:00") — null이면 날짜 레이블 또는 bundleId로 fallback */
  timeKey: string | null;
  /** serialize_slot()이 설정한 표시 label (label = slot.label = timeKey or dateLabel or bundleId) */
  label?: string;
  /** 열린 슬롯: 1(sentinel), 닫힌 슬롯: 0 */
  availableCount: number;
  /** Eventus HTML은 정확한 좌석 수를 제공하지 않으므로 항상 false */
  availableCountKnown: boolean;
  /** "imminent"이면 마감임박, null이면 일반 열림 */
  urgencyHint: string | null;
  /** 닫힌 슬롯의 닫힘 사유 텍스트 */
  closedText?: string | null;
  /** 슬롯 ID (bundleId:timeKey) */
  slotId?: string;
  /** 소스 타입 (항상 "eventus") */
  sourceType?: string;
  /** Eventus event ID */
  eventId?: string | null;
  /** 날짜 레이블 */
  dateLabel?: string | null;
}

/**
 * unknown[] 형태의 slots_info 원소를 안전하게 EventusHistorySlot[]으로 변환한다.
 * bundleId(string), availableCount(number) 두 키가 없으면 해당 원소는 건너뛴다.
 */
export function parseEventusSlots(raw: unknown[]): EventusHistorySlot[] {
  if (!Array.isArray(raw)) return [];
  const result: EventusHistorySlot[] = [];
  for (const item of raw) {
    if (
      item === null ||
      typeof item !== 'object' ||
      typeof (item as Record<string, unknown>).bundleId !== 'string' ||
      typeof (item as Record<string, unknown>).availableCount !== 'number'
    ) {
      continue;
    }
    const r = item as Record<string, unknown>;
    result.push({
      bundleId: r.bundleId as string,
      timeKey: typeof r.timeKey === 'string' ? r.timeKey : null,
      label: typeof r.label === 'string' ? r.label : undefined,
      availableCount: r.availableCount as number,
      availableCountKnown: r.availableCountKnown === true,
      urgencyHint: typeof r.urgencyHint === 'string' ? r.urgencyHint : null,
      closedText: typeof r.closedText === 'string' ? r.closedText : null,
      slotId: typeof r.slotId === 'string' ? r.slotId : undefined,
      sourceType: typeof r.sourceType === 'string' ? r.sourceType : undefined,
      eventId: typeof r.eventId === 'string' ? r.eventId : null,
      dateLabel: typeof r.dateLabel === 'string' ? r.dateLabel : null,
    });
  }
  return result;
}

/** availableCount > 0인 열린 슬롯을 반환한다. */
export function getOpenSlots(slots: EventusHistorySlot[]): EventusHistorySlot[] {
  return slots.filter((s) => s.availableCount > 0);
}

/** availableCount === 0인 닫힌 슬롯을 반환한다. */
export function getClosedSlots(slots: EventusHistorySlot[]): EventusHistorySlot[] {
  return slots.filter((s) => s.availableCount === 0);
}

/**
 * 슬롯의 표시 레이블을 반환한다.
 * fallback 순서: label → timeKey → bundleId → '시간대 정보 없음'
 */
export function getSlotLabel(slot: EventusHistorySlot): string {
  if (slot.label) return slot.label;
  if (slot.timeKey) return slot.timeKey;
  if (slot.bundleId) return slot.bundleId;
  return '시간대 정보 없음';
}

/**
 * 슬롯의 상태 텍스트를 반환한다.
 * - availableCountKnown === false (Eventus 기본)  → '열림 (수량 미확인)'
 * - urgencyHint === 'imminent'                   → '마감임박'
 * - availableCount === 0                         → closedText or '마감'
 * - 그 외                                        → '열림'
 */
export function getSlotStatusText(slot: EventusHistorySlot): string {
  if (slot.availableCount === 0) {
    return slot.closedText ?? '마감';
  }
  if (slot.urgencyHint === 'imminent') {
    return '마감임박';
  }
  if (!slot.availableCountKnown) {
    return '열림 (수량 미확인)';
  }
  return '열림';
}
