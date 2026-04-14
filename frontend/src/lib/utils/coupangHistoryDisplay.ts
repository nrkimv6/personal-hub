import type { MonitoringEvent } from '$lib/types';

const MEGABEAUTY_PREFIX = /2026\s*쿠팡\s*메가뷰티쇼/g;

function normalizeHistoryText(value: string | null | undefined): string {
  return (value ?? '')
    .replace(MEGABEAUTY_PREFIX, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function getSlotLabels(event: MonitoringEvent): string[] {
  if (!Array.isArray(event.slots_info)) {
    return [];
  }

  return event.slots_info
    .filter((slot): slot is { vendorItemName?: string } => Boolean(slot) && typeof slot === 'object')
    .map((slot) => normalizeHistoryText(slot.vendorItemName))
    .filter((label) => Boolean(label));
}

export interface CoupangHistoryDisplay {
  primaryLabel: string;
  extraOptionCount: number;
  fallbackLabel: string;
  slotLabels: string[];
}

export function getCoupangHistoryDisplay(event: MonitoringEvent): CoupangHistoryDisplay {
  const slotLabels = getSlotLabels(event);
  const fallbackLabel = normalizeHistoryText(event.time_range ?? event.biz_item_name ?? null) || '정보 없음';

  return {
    primaryLabel: slotLabels[0] ?? fallbackLabel,
    extraOptionCount: Math.max(slotLabels.length - 1, 0),
    fallbackLabel,
    slotLabels
  };
}

export function getCoupangHistoryTimeLabel(event: MonitoringEvent, display?: CoupangHistoryDisplay): string {
  const summary = display ?? getCoupangHistoryDisplay(event);
  return normalizeHistoryText(event.time_range ?? summary.primaryLabel ?? event.biz_item_name ?? null) || summary.fallbackLabel;
}
