import type { SlotInfo, DateSlots } from '$lib/types';

/** 슬롯 배경색 (가용 여부 및 잔여석 기준) */
export function getSlotBgColor(slot: SlotInfo): string {
	if (!slot.is_available) return 'bg-error-light';
	if (slot.remaining <= 2) return 'bg-warning-light';
	return 'bg-success-light';
}

/** 슬롯 텍스트색 (가용 여부 및 잔여석 기준) */
export function getSlotTextColor(slot: SlotInfo): string {
	if (!slot.is_available) return 'text-error';
	if (slot.remaining <= 2) return 'text-warning-foreground';
	return 'text-success';
}

/** 슬롯 테두리색 (가용 여부 및 잔여석 기준) */
export function getSlotBorderColor(slot: SlotInfo): string {
	if (!slot.is_available) return 'border-red-200';
	if (slot.remaining <= 2) return 'border-yellow-200';
	return 'border-green-200';
}

/** 예약 진행률 (0~100) */
export function getProgress(booked: number, capacity: number): number {
	return capacity > 0 ? (booked / capacity) * 100 : 0;
}

/** 진행률 바 색상 */
export function getProgressColor(booked: number, capacity: number): string {
	const ratio = capacity > 0 ? booked / capacity : 1;
	if (ratio >= 1) return 'bg-error';
	if (ratio >= 0.8) return 'bg-warning';
	return 'bg-success';
}

/**
 * 날짜 요약 상태 텍스트색
 *
 * `total_capacity === 0`일 때 division by zero를 방지하기 위해
 * `total_capacity > 0 &&` 가드를 포함한 안전 버전을 사용한다.
 */
export function getDateStatusColor(dateSlots: DateSlots): string {
	const { total_remaining, total_capacity } = dateSlots.summary;
	if (total_remaining === 0) return 'text-error';
	if (total_capacity > 0 && total_remaining / total_capacity < 0.2) return 'text-warning-foreground';
	return 'text-success';
}
