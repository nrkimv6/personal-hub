import type { MonitoringEvent } from '$lib/types';

const COUPANG_HISTORY_PREFIXES = [
  /메가뷰티쇼\s*버추얼스토어\s*/g,
  /2026\s*쿠팡\s*메가뷰티쇼\s*/g,
  /2026\s*메가뷰티쇼\s*버추얼스토어\s*/g,
  /쿠팡\s*메가뷰티쇼\s*/g
];

export function normalizeHistoryText(value: string | null | undefined): string {
  let normalized = value ?? '';
  for (const pattern of COUPANG_HISTORY_PREFIXES) {
    normalized = normalized.replace(pattern, '');
  }
  return normalized
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

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '-';
  const rounded = Math.max(0, Math.round(seconds));
  if (rounded < 60) return `약 ${rounded}초`;
  const minutes = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return rest > 0 ? `약 ${minutes}분 ${rest}초` : `약 ${minutes}분`;
}
