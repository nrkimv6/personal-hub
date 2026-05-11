<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import {
    HardDrive,
    Cpu,
    FileText,
    BarChart3,
    AlertTriangle,
    Circle,
    RefreshCw,
    History,
    Filter,
    ChevronDown,
    ChevronRight
  } from 'lucide-svelte';
  import {
    memoryPressureHistoryApi,
    type MemoryPressureHistoryResponse,
    type MemoryPressureLevel
  } from '$lib/api';
  import { fetchWithTimeout } from '$lib/api/client';
  import {
    getMemoryPressureLevelMeta,
    formatMemoryPressureMb,
    formatMemoryPressureTimestamp,
    summarizeMemoryPressureProcesses,
    renderMemoryPressureExcerpt,
    toggleStringSelection
  } from '$lib/memory-pressure-history.js';

  interface MemoryInfo {
    total_mb: number;
    used_mb: number;
    available_mb: number;
    percent: number;
  }

  interface PageFileInfo {
    total_mb: number;
    used_mb: number;
    free_mb: number;
    percent: number;
  }

  interface ProcessMemoryItem {
    name: string;
    pid: number;
    working_set_mb: number;
    count: number;
  }

  interface MemoryResponse {
    ram: MemoryInfo;
    pagefile: PageFileInfo;
    top_processes: ProcessMemoryItem[];
    danger_level: 'normal' | 'warning' | 'critical';
  }

  const HISTORY_LEVELS: MemoryPressureLevel[] = ['critical', 'emergency', 'fatal', 'fatal_recovered'];
  const HISTORY_LIMIT_OPTIONS = [50, 100, 200];
  const HISTORY_SINCE_OPTIONS: Array<{ label: string; value: number }> = [
    { label: '24시간', value: 24 },
    { label: '7일', value: 168 }
  ];

  // Props
  let { onDangerChange }: { onDangerChange?: (level: string) => void } = $props();

  // 상태
  let data = $state<MemoryResponse | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let lastUpdated = $state<Date | null>(null);
  let activeView = $state<'live' | 'history'>('live');

  let historyData = $state<MemoryPressureHistoryResponse | null>(null);
  let historyLoading = $state(false);
  let historyError = $state<string | null>(null);
  let historyLastUpdated = $state<Date | null>(null);
  let historyLimit = $state<number>(50);
  let historySinceHours = $state<number>(24);
  let historyLevels = $state<MemoryPressureLevel[]>([...HISTORY_LEVELS]);

  let intervalId: ReturnType<typeof setInterval> | null = null;

  async function fetchMemory() {
    try {
      const resp = await fetchWithTimeout('/api/v1/system/memory');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
      error = null;
      lastUpdated = new Date();
      if (data && onDangerChange) {
        onDangerChange(data.danger_level);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : '알 수 없는 오류';
    } finally {
      loading = false;
    }
  }

  async function fetchHistory() {
    historyLoading = true;
    try {
      const params = {
        limit: historyLimit,
        levels: historyLevels,
        since_hours: historySinceHours
      };
      const resp = await memoryPressureHistoryApi.list(params);
      historyData = resp;
      historyError = null;
      historyLastUpdated = new Date();
    } catch (e) {
      historyError = e instanceof Error ? e.message : '알 수 없는 오류';
    } finally {
      historyLoading = false;
    }
  }

  function syncLivePolling() {
    if (intervalId) {
      clearInterval(intervalId);
      intervalId = null;
    }
    if (activeView === 'live') {
      intervalId = setInterval(fetchMemory, 30_000);
    }
  }

  function changeView(view: 'live' | 'history') {
    if (activeView === view) {
      return;
    }
    activeView = view;
    syncLivePolling();
    if (view === 'live') {
      void fetchMemory();
    } else {
      void fetchHistory();
    }
  }

  function refreshActiveView() {
    if (activeView === 'live') {
      void fetchMemory();
      return;
    }
    void fetchHistory();
  }

  function toggleHistoryLevel(level: MemoryPressureLevel) {
    historyLevels = toggleStringSelection(historyLevels, level) as MemoryPressureLevel[];
    if (activeView === 'history') {
      void fetchHistory();
    }
  }

  function changeHistoryLimit(event: Event) {
    historyLimit = Number((event.currentTarget as HTMLSelectElement).value);
    if (activeView === 'history') {
      void fetchHistory();
    }
  }

  function changeHistoryWindow(event: Event) {
    historySinceHours = Number((event.currentTarget as HTMLSelectElement).value);
    if (activeView === 'history') {
      void fetchHistory();
    }
  }

  function getHistorySummaryCount(level: MemoryPressureLevel) {
    return historyData ? historyData.summary[level] : 0;
  }

  onMount(() => {
    void fetchMemory();
    syncLivePolling();
  });

  onDestroy(() => {
    if (intervalId) clearInterval(intervalId);
  });

  // 위험도 색상
  function dangerColor(level: 'normal' | 'warning' | 'critical') {
    if (level === 'critical') return 'text-red-600';
    if (level === 'warning') return 'text-amber-600';
    return 'text-green-600';
  }

  function dangerBg(level: 'normal' | 'warning' | 'critical') {
    if (level === 'critical') return 'bg-red-100 text-red-700 border border-red-300';
    if (level === 'warning') return 'bg-amber-100 text-amber-700 border border-amber-300';
    return 'bg-green-100 text-green-700 border border-green-300';
  }

  function gaugeColor(level: 'normal' | 'warning' | 'critical') {
    if (level === 'critical') return 'bg-red-500';
    if (level === 'warning') return 'bg-amber-400';
    return 'bg-green-500';
  }

  function dangerLabel(level: 'normal' | 'warning' | 'critical') {
    if (level === 'critical') return '위험';
    if (level === 'warning') return '경고';
    return '정상';
  }

  function fmtMb(mb: number): string {
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${mb.toFixed(0)} MB`;
  }
</script>

<div class="space-y-6">
  <div class="flex flex-wrap items-start justify-between gap-4">
    <div class="space-y-3">
      <div class="flex items-center gap-3">
        <h2 class="text-lg font-semibold flex items-center gap-2">
          <HardDrive class="w-5 h-5" /> 메모리 현황
        </h2>
        {#if activeView === 'live' && data}
          <span class="px-3 py-1 rounded-full text-sm font-medium {dangerBg(data.danger_level)} flex items-center gap-1.5">
            <Circle class="w-2.5 h-2.5 fill-current" />
            {dangerLabel(data.danger_level)}
          </span>
        {:else if activeView === 'history' && historyData}
          <span class="px-3 py-1 rounded-full text-sm font-medium bg-slate-100 text-slate-700 border border-slate-300 flex items-center gap-1.5">
            <History class="w-3.5 h-3.5" />
            총 {historyData.summary.total}건
          </span>
        {/if}
      </div>

      <div class="flex flex-wrap gap-2">
        <button
          onclick={() => changeView('live')}
          class="px-3 py-1.5 rounded-md text-sm font-medium transition-colors border {activeView === 'live' ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}"
        >
          실시간 현황
        </button>
        <button
          onclick={() => changeView('history')}
          class="px-3 py-1.5 rounded-md text-sm font-medium transition-colors border {activeView === 'history' ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}"
        >
          압박 이력
        </button>
      </div>
    </div>

    <div class="flex items-center gap-2 text-sm text-gray-500">
      {#if activeView === 'live' && lastUpdated}
        <span>업데이트: {lastUpdated.toLocaleTimeString()}</span>
      {:else if activeView === 'history' && historyLastUpdated}
        <span>업데이트: {historyLastUpdated.toLocaleTimeString()}</span>
      {/if}
      <button
        onclick={refreshActiveView}
        class="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-medium transition-colors flex items-center gap-1"
      >
        <RefreshCw class="w-3 h-3 {((activeView === 'live' && loading) || (activeView === 'history' && historyLoading)) ? 'animate-spin' : ''}" />
        새로고침
      </button>
    </div>
  </div>

  {#if activeView === 'live'}
    {#if loading}
      <div class="space-y-4 animate-pulse">
        <div class="h-24 bg-gray-200 rounded-lg"></div>
        <div class="h-24 bg-gray-200 rounded-lg"></div>
        <div class="h-48 bg-gray-200 rounded-lg"></div>
      </div>
    {:else if error}
      <div class="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 flex items-start gap-2">
        <AlertTriangle class="w-5 h-5 shrink-0 mt-0.5" />
        <div>
          <p class="font-medium">메모리 정보 조회 실패</p>
          <p class="text-sm mt-1">{error}</p>
        </div>
      </div>
    {:else if data}
      <div class="bg-white rounded-lg border border-gray-200 p-5 shadow-sm">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-semibold text-gray-800 flex items-center gap-2">
            <Cpu class="w-5 h-5 text-gray-400" /> RAM (물리 메모리)
          </h3>
          <span class="text-sm {dangerColor(data.danger_level)} font-medium">
            {data.ram.percent.toFixed(1)}% 사용
          </span>
        </div>
        <div class="w-full bg-gray-100 rounded-full h-4 overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-500 {gaugeColor(data.danger_level)}"
            style="width: {Math.min(data.ram.percent, 100)}%"
          ></div>
        </div>
        <div class="flex justify-between text-xs text-gray-500 mt-2">
          <span>사용: {fmtMb(data.ram.used_mb)}</span>
          <span>여유: {fmtMb(data.ram.available_mb)}</span>
          <span>전체: {fmtMb(data.ram.total_mb)}</span>
        </div>
      </div>

      <div class="bg-white rounded-lg border border-gray-200 p-5 shadow-sm">
        <div class="flex items-center justify-between mb-3">
          <h3 class="font-semibold text-gray-800 flex items-center gap-2">
            <FileText class="w-5 h-5 text-gray-400" /> PageFile (가상 메모리)
          </h3>
          <span class="text-sm text-gray-600 font-medium">
            {data.pagefile.percent.toFixed(1)}% 사용
          </span>
        </div>
        {#if data.pagefile.total_mb === 0}
          <p class="text-sm text-gray-500 italic">PageFile 없음 (비활성화)</p>
        {:else}
          <div class="w-full bg-gray-100 rounded-full h-4 overflow-hidden">
            <div
              class="h-full rounded-full bg-blue-400 transition-all duration-500"
              style="width: {Math.min(data.pagefile.percent, 100)}%"
            ></div>
          </div>
          <div class="flex justify-between text-xs text-gray-500 mt-2">
            <span>사용: {fmtMb(data.pagefile.used_mb)}</span>
            <span>여유: {fmtMb(data.pagefile.free_mb)}</span>
            <span>전체: {fmtMb(data.pagefile.total_mb)}</span>
          </div>
        {/if}
      </div>

      <div class="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
        <div class="px-5 py-4 border-b border-gray-200">
          <h3 class="font-semibold text-gray-800 flex items-center gap-2">
            <BarChart3 class="w-5 h-5 text-gray-400" /> 프로세스별 메모리 (Top {data.top_processes.length})
          </h3>
        </div>
        {#if data.top_processes.length === 0}
          <p class="p-5 text-sm text-gray-500 italic">프로세스 정보 없음</p>
        {:else}
          <table class="w-full text-sm">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wide">#</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wide">프로세스</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-600 uppercase tracking-wide">메모리</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              {#each data.top_processes as proc, i}
                <tr class="hover:bg-gray-50 transition-colors">
                  <td class="px-4 py-2.5 text-gray-400 text-xs">{i + 1}</td>
                  <td class="px-4 py-2.5 text-gray-800 font-mono text-xs">
                    {proc.name}
                    {#if proc.count > 1}
                      <span class="ml-1 text-gray-400">(x{proc.count})</span>
                    {/if}
                  </td>
                  <td class="px-4 py-2.5 text-right font-medium text-gray-700">
                    {fmtMb(proc.working_set_mb)}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>

      <p class="text-xs text-gray-400 text-center">30초마다 자동 새로고침</p>
    {/if}
  {:else}
    <div class="space-y-4">
      <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 class="font-semibold text-gray-800 flex items-center gap-2">
              <History class="w-5 h-5 text-gray-400" /> 메모리 압박 히스토리
            </h3>
            <p class="mt-1 text-sm text-gray-500">500MB 이상은 히스토리만 남고, 500MB 미만만 실제 알림이 발행된다.</p>
          </div>
          <div class="flex flex-wrap gap-2">
            {#each HISTORY_LIMIT_OPTIONS as option}
              <button
                onclick={() => { historyLimit = option; void fetchHistory(); }}
                class="px-3 py-1.5 rounded-md text-sm font-medium border transition-colors {historyLimit === option ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}"
              >
                최근 {option}건
              </button>
            {/each}
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <label class="flex items-center gap-2 text-sm text-gray-600">
            <Filter class="w-4 h-4 text-gray-400" />
            기간
            <select
              class="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm"
              onchange={changeHistoryWindow}
              value={historySinceHours}
            >
              {#each HISTORY_SINCE_OPTIONS as option}
                <option value={option.value}>{option.label}</option>
              {/each}
            </select>
          </label>

          <div class="flex flex-wrap gap-2">
            {#each HISTORY_LEVELS as level}
              <button
                onclick={() => toggleHistoryLevel(level)}
                class="px-3 py-1.5 rounded-full text-sm font-medium border transition-colors {historyLevels.includes(level) ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'}"
              >
                {getMemoryPressureLevelMeta(level).label}
              </button>
            {/each}
          </div>

          <div class="text-xs text-gray-500">
            선택 레벨: {historyLevels.length ? historyLevels.map((level) => getMemoryPressureLevelMeta(level).label).join(', ') : '전체'}
          </div>
        </div>
      </div>

      {#if historyData}
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <div class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <p class="text-xs uppercase tracking-wide text-gray-500">Total</p>
            <p class="mt-2 text-2xl font-semibold text-gray-900">{historyData.summary.total}</p>
          </div>
          {#each HISTORY_LEVELS as level}
            <div class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <p class="text-xs uppercase tracking-wide text-gray-500">{getMemoryPressureLevelMeta(level).label}</p>
              <p class="mt-2 text-2xl font-semibold text-gray-900">{getHistorySummaryCount(level)}</p>
            </div>
          {/each}
        </div>
      {/if}

      {#if historyLoading}
        <div class="space-y-4 animate-pulse">
          <div class="h-24 bg-gray-200 rounded-lg"></div>
          <div class="h-48 bg-gray-200 rounded-lg"></div>
        </div>
      {:else if historyError}
        <div class="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700 flex items-start gap-2">
          <AlertTriangle class="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <p class="font-medium">히스토리 조회 실패</p>
            <p class="text-sm mt-1">{historyError}</p>
          </div>
        </div>
      {:else if historyData && historyData.items.length > 0}
        <div class="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
          <div class="px-5 py-4 border-b border-gray-200 flex items-center justify-between gap-3">
            <h3 class="font-semibold text-gray-800 flex items-center gap-2">
              <History class="w-5 h-5 text-gray-400" /> 압박 이력 목록
            </h3>
            <span class="text-xs text-gray-500">최신 항목이 위에 표시됩니다.</span>
          </div>

          <table class="w-full text-sm">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wide">시각</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wide">level</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-600 uppercase tracking-wide">여유 메모리</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wide">상위 프로세스</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wide">상세</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              {#each historyData.items as item}
                {@const meta = getMemoryPressureLevelMeta(item.level)}
                <tr class="align-top hover:bg-gray-50/80 transition-colors">
                  <td class="px-4 py-3 text-gray-700 whitespace-nowrap">{formatMemoryPressureTimestamp(item.timestamp)}</td>
                  <td class="px-4 py-3">
                    <span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium {meta.badgeClass}">
                      {meta.label}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-right font-medium {item.available_mb < 500 ? 'text-red-600' : 'text-gray-700'}">
                    {formatMemoryPressureMb(item.available_mb)}
                  </td>
                  <td class="px-4 py-3 text-gray-700 text-xs">
                    {summarizeMemoryPressureProcesses(item.top_processes)}
                  </td>
                  <td class="px-4 py-3">
                    <details class="group">
                      <summary class="list-none cursor-pointer inline-flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-900">
                        <ChevronDown class="w-4 h-4 group-open:hidden" />
                        <ChevronRight class="w-4 h-4 hidden group-open:inline-block" />
                        상세
                      </summary>
                      <div class="mt-3 space-y-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
                        <div>
                          <p class="text-[11px] uppercase tracking-wide text-gray-500">Top processes</p>
                          {#if item.top_processes.length > 0}
                            <ul class="mt-2 space-y-1 text-xs text-gray-700">
                              {#each item.top_processes.slice(0, 5) as proc}
                                <li class="font-mono">{proc.name} · {formatMemoryPressureMb(proc.memory_mb)}</li>
                              {/each}
                            </ul>
                          {:else}
                            <p class="mt-2 text-xs text-gray-500">프로세스 정보 없음</p>
                          {/if}
                        </div>
                        <div>
                          <p class="text-[11px] uppercase tracking-wide text-gray-500">process_tree_excerpt</p>
                          <pre class="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded border border-gray-200 bg-white p-2 text-[11px] leading-4 text-gray-700">{renderMemoryPressureExcerpt(item.process_tree_excerpt)}</pre>
                        </div>
                      </div>
                    </details>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else if historyData}
        <div class="rounded-lg border border-dashed border-gray-300 bg-white p-8 text-center text-gray-500">
          선택한 기간과 레벨에 해당하는 메모리 압박 이력이 없습니다.
        </div>
      {/if}
    </div>
  {/if}
</div>
