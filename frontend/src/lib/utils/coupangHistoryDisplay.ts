export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '-';
  const rounded = Math.max(0, Math.round(seconds));
  if (rounded < 60) return `약 ${rounded}초`;
  const minutes = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return rest > 0 ? `약 ${minutes}분 ${rest}초` : `약 ${minutes}분`;
}

export function formatDurationList(secondsList: Array<number | null | undefined>): string {
  const durations = secondsList
    .map((seconds) => formatDuration(seconds))
    .filter((value) => value !== '-');
  return durations.length > 0 ? durations.join(' · ') : '-';
}
