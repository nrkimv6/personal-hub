export const MEMORY_PRESSURE_LEVEL_META = {
  critical: {
    label: '위험',
    badgeClass: 'bg-red-100 text-red-700 border border-red-300',
    toneClass: 'text-red-600',
  },
  emergency: {
    label: '긴급',
    badgeClass: 'bg-orange-100 text-orange-700 border border-orange-300',
    toneClass: 'text-orange-600',
  },
  fatal: {
    label: '치명',
    badgeClass: 'bg-rose-100 text-rose-700 border border-rose-300',
    toneClass: 'text-rose-600',
  },
  fatal_recovered: {
    label: '복구',
    badgeClass: 'bg-emerald-100 text-emerald-700 border border-emerald-300',
    toneClass: 'text-emerald-600',
  },
};

export function getMemoryPressureLevelMeta(level) {
  return MEMORY_PRESSURE_LEVEL_META[level] ?? MEMORY_PRESSURE_LEVEL_META.emergency;
}

export function formatMemoryPressureMb(value) {
  const mb = Number(value);
  if (!Number.isFinite(mb)) return '-';
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

export function formatMemoryPressureTimestamp(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

export function summarizeMemoryPressureProcesses(topProcesses, limit = 3) {
  if (!Array.isArray(topProcesses) || topProcesses.length === 0) {
    return '(프로세스 없음)';
  }
  return topProcesses
    .slice(0, limit)
    .map((proc) => {
      const name = proc?.name || 'unknown';
      const memory = formatMemoryPressureMb(proc?.memory_mb);
      return `${name} (${memory})`;
    })
    .join(', ');
}

/**
 * Raw `process_tree` 전문을 목록 UI용 excerpt로 자른다.
 * 이미 excerpt된 `process_tree_excerpt`에는 재적용하지 않는다.
 */
export function excerptMemoryPressureTree(treeText, maxLines = 80) {
  const raw = String(treeText ?? '');
  if (!raw) return '';
  const lines = raw.split(/\r?\n/);
  if (lines.length <= maxLines) return raw;
  const omitted = lines.length - maxLines;
  return `${lines.slice(0, maxLines).join('\n')}\n... (+${omitted} lines)`;
}

/**
 * Server가 이미 잘라서 내려준 `process_tree_excerpt`를 그대로 표시한다.
 */
export function renderMemoryPressureExcerpt(processTreeExcerpt) {
  return String(processTreeExcerpt ?? '');
}

export function toggleStringSelection(values, value) {
  if (!Array.isArray(values)) return [value];
  return values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];
}
