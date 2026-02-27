<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

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

  // Props
  let { onDangerChange }: { onDangerChange?: (level: string) => void } = $props();

  // 상태
  let data = $state<MemoryResponse | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let lastUpdated = $state<Date | null>(null);

  let intervalId: ReturnType<typeof setInterval> | null = null;

  async function fetchMemory() {
    try {
      const resp = await fetch('/api/v1/system/memory');
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

  onMount(() => {
    fetchMemory();
    intervalId = setInterval(fetchMemory, 30_000);
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
    if (level === 'critical') return '🔴 위험';
    if (level === 'warning') return '🟡 경고';
    return '🟢 정상';
  }

  function fmtMb(mb: number): string {
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${mb.toFixed(0)} MB`;
  }
</script>

<div class="space-y-6">

  <!-- 헤더 -->
  <div class="flex items-center justify-between">
    <div class="flex items-center gap-3">
      <h2 class="text-lg font-semibold">💾 메모리 현황</h2>
      {#if data}
        <span class="px-3 py-1 rounded-full text-sm font-medium {dangerBg(data.danger_level)}">
          {dangerLabel(data.danger_level)}
        </span>
      {/if}
    </div>
    <div class="flex items-center gap-2 text-sm text-gray-500">
      {#if lastUpdated}
        <span>업데이트: {lastUpdated.toLocaleTimeString()}</span>
      {/if}
      <button
        onclick={fetchMemory}
        class="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-medium transition-colors"
      >
        새로고침
      </button>
    </div>
  </div>

  <!-- 로딩 스켈레톤 -->
  {#if loading}
    <div class="space-y-4 animate-pulse">
      <div class="h-24 bg-gray-200 rounded-lg"></div>
      <div class="h-24 bg-gray-200 rounded-lg"></div>
      <div class="h-48 bg-gray-200 rounded-lg"></div>
    </div>

  <!-- 에러 -->
  {:else if error}
    <div class="p-4 rounded-lg bg-red-50 border border-red-200 text-red-700">
      <p class="font-medium">⚠️ 메모리 정보 조회 실패</p>
      <p class="text-sm mt-1">{error}</p>
    </div>

  <!-- 데이터 -->
  {:else if data}

    <!-- RAM 게이지 -->
    <div class="bg-white rounded-lg border border-gray-200 p-5 shadow-sm">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold text-gray-800">🧠 RAM (물리 메모리)</h3>
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

    <!-- PageFile 게이지 -->
    <div class="bg-white rounded-lg border border-gray-200 p-5 shadow-sm">
      <div class="flex items-center justify-between mb-3">
        <h3 class="font-semibold text-gray-800">📄 PageFile (가상 메모리)</h3>
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

    <!-- 프로세스 Top 15 테이블 -->
    <div class="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden">
      <div class="px-5 py-4 border-b border-gray-200">
        <h3 class="font-semibold text-gray-800">📊 프로세스별 메모리 (Top {data.top_processes.length})</h3>
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
</div>
