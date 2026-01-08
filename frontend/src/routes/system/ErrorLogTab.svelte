<script lang="ts">
  import { onMount } from 'svelte';
  import { errorApi, type ErrorLog, type ErrorLogStatsResponse, type ErrorListParams } from '$lib/api';

  // Props
  interface Props {
    onUnresolvedChange?: (count: number) => void;
  }
  let { onUnresolvedChange }: Props = $props();

  // 상태
  let stats = $state<ErrorLogStatsResponse | null>(null);
  let errors = $state<ErrorLog[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let statsLoading = $state(true);

  // 필터
  let source = $state('');
  let severity = $state('');
  let resolved = $state<boolean | undefined>(undefined);
  let search = $state('');
  let page = $state(1);
  let pageSize = $state(50);

  // 선택 상태
  let selectedIds = $state<Set<number>>(new Set());
  let selectAll = $state(false);

  // 모달
  let detailModal = $state<ErrorLog | null>(null);
  let sources = $state<string[]>([]);

  const REFRESH_INTERVAL = 30000; // 30초

  async function fetchStats() {
    statsLoading = true;
    try {
      stats = await errorApi.stats(24);
      if (stats && onUnresolvedChange) {
        onUnresolvedChange(stats.summary.unresolved_count);
      }
    } catch (e) {
      console.error('Failed to fetch stats:', e);
    } finally {
      statsLoading = false;
    }
  }

  async function fetchErrors() {
    loading = true;
    try {
      const params: ErrorListParams = { page, page_size: pageSize };
      if (source) params.source = source;
      if (severity) params.severity = severity;
      if (resolved !== undefined) params.resolved = resolved;
      if (search) params.search = search;

      const result = await errorApi.list(params);
      errors = result.items;
      total = result.total;
    } catch (e) {
      console.error('Failed to fetch errors:', e);
    } finally {
      loading = false;
    }
  }

  async function fetchSources() {
    try {
      sources = await errorApi.sources();
    } catch (e) {
      console.error('Failed to fetch sources:', e);
    }
  }

  function handleFilterChange() {
    page = 1;
    selectedIds = new Set();
    selectAll = false;
    fetchErrors();
  }

  async function resolveError(id: number) {
    try {
      await errorApi.resolve(id, { resolved: true, resolved_by: 'user' });
      fetchErrors();
      fetchStats();
    } catch (e) {
      console.error('Failed to resolve error:', e);
    }
  }

  async function resolveBulk() {
    if (selectedIds.size === 0) return;
    try {
      await errorApi.resolveBulk(Array.from(selectedIds), 'user');
      selectedIds = new Set();
      selectAll = false;
      fetchErrors();
      fetchStats();
    } catch (e) {
      console.error('Failed to resolve errors:', e);
    }
  }

  function toggleSelect(id: number) {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) {
      newSet.delete(id);
    } else {
      newSet.add(id);
    }
    selectedIds = newSet;
    selectAll = errors.every(e => selectedIds.has(e.id));
  }

  function toggleSelectAll() {
    if (selectAll) {
      selectedIds = new Set();
    } else {
      selectedIds = new Set(errors.map(e => e.id));
    }
    selectAll = !selectAll;
  }

  function formatDate(dateStr: string): string {
    const date = new Date(dateStr);
    return date.toLocaleString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function getSeverityColor(sev: string): string {
    switch (sev) {
      case 'critical': return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400';
      case 'error': return 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400';
      case 'warning': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400';
      default: return 'bg-muted text-foreground dark:bg-gray-800 dark:text-muted-foreground';
    }
  }

  function getSourceColor(src: string): string {
    const colors: Record<string, string> = {
      api: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
      worker: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-400',
      naver: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
      instagram: 'bg-pink-100 text-pink-800 dark:bg-pink-900/30 dark:text-pink-400',
      writing: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-400',
    };
    return colors[src] || 'bg-muted text-foreground dark:bg-gray-800 dark:text-muted-foreground';
  }

  onMount(() => {
    fetchStats();
    fetchErrors();
    fetchSources();
    const interval = setInterval(() => {
      fetchStats();
      fetchErrors();
    }, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  });
</script>

<div class="space-y-6">
  <!-- 통계 카드 -->
  {#if stats}
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-muted-foreground dark:text-muted-foreground">전체</div>
        <div class="text-2xl font-bold text-foreground dark:text-white">{stats.summary.total_count}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-red-500">Critical</div>
        <div class="text-2xl font-bold text-red-600">{stats.summary.critical_count}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-orange-500">Error</div>
        <div class="text-2xl font-bold text-orange-600">{stats.summary.error_count}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-yellow-500">Warning</div>
        <div class="text-2xl font-bold text-yellow-600">{stats.summary.warning_count}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-muted-foreground dark:text-muted-foreground">미해결</div>
        <div class="text-2xl font-bold text-foreground dark:text-white">{stats.summary.unresolved_count}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-green-500">해결률</div>
        <div class="text-2xl font-bold text-green-600">{stats.summary.resolve_rate}%</div>
      </div>
    </div>

    <!-- TOP 에러 타입 -->
    {#if stats.by_type.length > 0}
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <h3 class="text-sm font-medium text-muted-foreground dark:text-muted-foreground mb-3">자주 발생하는 에러 (24시간)</h3>
        <div class="space-y-2">
          {#each stats.by_type.slice(0, 5) as typeStats}
            <div class="flex justify-between items-center text-sm">
              <span class="font-mono text-foreground dark:text-gray-300">{typeStats.error_type}</span>
              <span class="text-muted-foreground dark:text-muted-foreground">{typeStats.count}회</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  {/if}

  <!-- 필터 -->
  <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
    <div class="flex flex-wrap gap-4 items-end">
      <div>
        <label class="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">소스</label>
        <select
          bind:value={source}
          onchange={handleFilterChange}
          class="px-3 py-2 border border-border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-foreground dark:text-white text-sm"
        >
          <option value="">전체</option>
          {#each sources as src}
            <option value={src}>{src}</option>
          {/each}
        </select>
      </div>
      <div>
        <label class="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">심각도</label>
        <select
          bind:value={severity}
          onchange={handleFilterChange}
          class="px-3 py-2 border border-border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-foreground dark:text-white text-sm"
        >
          <option value="">전체</option>
          <option value="critical">Critical</option>
          <option value="error">Error</option>
          <option value="warning">Warning</option>
        </select>
      </div>
      <div>
        <label class="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">해결 상태</label>
        <select
          bind:value={resolved}
          onchange={handleFilterChange}
          class="px-3 py-2 border border-border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-foreground dark:text-white text-sm"
        >
          <option value={undefined}>전체</option>
          <option value={false}>미해결</option>
          <option value={true}>해결됨</option>
        </select>
      </div>
      <div class="flex-1">
        <label class="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">검색</label>
        <input
          type="text"
          bind:value={search}
          onkeyup={(e) => e.key === 'Enter' && handleFilterChange()}
          placeholder="메시지 검색..."
          class="w-full px-3 py-2 border border-border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-foreground dark:text-white text-sm"
        />
      </div>
      {#if selectedIds.size > 0}
        <button
          onclick={resolveBulk}
          class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm"
        >
          {selectedIds.size}개 해결 처리
        </button>
      {/if}
    </div>
  </div>

  <!-- 에러 목록 -->
  <div class="bg-white dark:bg-gray-800 rounded-lg shadow-sm overflow-hidden">
    <table class="min-w-full divide-y divide-border dark:divide-gray-700">
      <thead class="bg-background dark:bg-gray-900">
        <tr>
          <th class="w-10 px-4 py-3">
            <input type="checkbox" checked={selectAll} onchange={toggleSelectAll} />
          </th>
          <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground dark:text-muted-foreground uppercase">시간</th>
          <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground dark:text-muted-foreground uppercase">소스</th>
          <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground dark:text-muted-foreground uppercase">심각도</th>
          <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground dark:text-muted-foreground uppercase">타입</th>
          <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground dark:text-muted-foreground uppercase">메시지</th>
          <th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground dark:text-muted-foreground uppercase">상태</th>
          <th class="px-4 py-3"></th>
        </tr>
      </thead>
      <tbody class="divide-y divide-border dark:divide-gray-700">
        {#if loading}
          <tr>
            <td colspan="8" class="px-4 py-8 text-center text-muted-foreground dark:text-muted-foreground">
              로딩 중...
            </td>
          </tr>
        {:else if errors.length === 0}
          <tr>
            <td colspan="8" class="px-4 py-8 text-center text-muted-foreground dark:text-muted-foreground">
              에러가 없습니다
            </td>
          </tr>
        {:else}
          {#each errors as error}
            <tr class="hover:bg-muted dark:hover:bg-gray-700/50">
              <td class="px-4 py-3">
                <input
                  type="checkbox"
                  checked={selectedIds.has(error.id)}
                  onchange={() => toggleSelect(error.id)}
                />
              </td>
              <td class="px-4 py-3 text-sm text-muted-foreground dark:text-muted-foreground whitespace-nowrap">
                {formatDate(error.created_at)}
              </td>
              <td class="px-4 py-3">
                <span class="px-2 py-1 text-xs rounded-full {getSourceColor(error.source)}">
                  {error.source}
                </span>
              </td>
              <td class="px-4 py-3">
                <span class="px-2 py-1 text-xs rounded-full {getSeverityColor(error.severity)}">
                  {error.severity}
                </span>
              </td>
              <td class="px-4 py-3 text-sm font-mono text-foreground dark:text-gray-300">
                {error.error_type}
              </td>
              <td class="px-4 py-3 text-sm text-muted-foreground dark:text-muted-foreground max-w-md truncate">
                {error.message}
              </td>
              <td class="px-4 py-3 text-center">
                {#if error.resolved}
                  <span class="text-green-500">해결됨</span>
                {:else}
                  <span class="text-red-500">미해결</span>
                {/if}
              </td>
              <td class="px-4 py-3 text-right">
                <button
                  onclick={() => detailModal = error}
                  class="text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 text-sm mr-2"
                >
                  상세
                </button>
                {#if !error.resolved}
                  <button
                    onclick={() => resolveError(error.id)}
                    class="text-green-600 hover:text-green-800 dark:text-green-400 dark:hover:text-green-300 text-sm"
                  >
                    해결
                  </button>
                {/if}
              </td>
            </tr>
          {/each}
        {/if}
      </tbody>
    </table>

    <!-- 페이지네이션 -->
    {#if total > pageSize}
      <div class="px-4 py-3 border-t border-border dark:border-gray-700 flex justify-between items-center">
        <span class="text-sm text-muted-foreground dark:text-muted-foreground">
          총 {total}개 중 {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)}
        </span>
        <div class="flex gap-2">
          <button
            onclick={() => { page--; fetchErrors(); }}
            disabled={page <= 1}
            class="px-3 py-1 border rounded text-sm disabled:opacity-50"
          >
            이전
          </button>
          <button
            onclick={() => { page++; fetchErrors(); }}
            disabled={page * pageSize >= total}
            class="px-3 py-1 border rounded text-sm disabled:opacity-50"
          >
            다음
          </button>
        </div>
      </div>
    {/if}
  </div>
</div>

<!-- 상세 모달 -->
{#if detailModal}
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onclick={() => detailModal = null}>
    <div class="bg-white dark:bg-gray-800 rounded-lg max-w-3xl w-full max-h-[80vh] overflow-auto m-4" onclick={(e) => e.stopPropagation()}>
      <div class="p-6">
        <div class="flex justify-between items-start mb-4">
          <h2 class="text-lg font-bold text-foreground dark:text-white">에러 상세</h2>
          <button onclick={() => detailModal = null} class="text-muted-foreground hover:text-foreground dark:text-muted-foreground dark:hover:text-gray-200">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <span class="text-sm text-muted-foreground dark:text-muted-foreground">시간</span>
              <p class="text-foreground dark:text-white">{new Date(detailModal.created_at).toLocaleString('ko-KR')}</p>
            </div>
            <div>
              <span class="text-sm text-muted-foreground dark:text-muted-foreground">소스</span>
              <p><span class="px-2 py-1 text-xs rounded-full {getSourceColor(detailModal.source)}">{detailModal.source}</span></p>
            </div>
            <div>
              <span class="text-sm text-muted-foreground dark:text-muted-foreground">심각도</span>
              <p><span class="px-2 py-1 text-xs rounded-full {getSeverityColor(detailModal.severity)}">{detailModal.severity}</span></p>
            </div>
            <div>
              <span class="text-sm text-muted-foreground dark:text-muted-foreground">타입</span>
              <p class="font-mono text-foreground dark:text-white">{detailModal.error_type}</p>
            </div>
          </div>

          <div>
            <span class="text-sm text-muted-foreground dark:text-muted-foreground">메시지</span>
            <p class="text-foreground dark:text-white mt-1">{detailModal.message}</p>
          </div>

          {#if detailModal.traceback}
            <div>
              <span class="text-sm text-muted-foreground dark:text-muted-foreground">트레이스백</span>
              <pre class="mt-1 p-3 bg-muted dark:bg-gray-900 rounded text-xs overflow-auto max-h-60">{detailModal.traceback}</pre>
            </div>
          {/if}

          {#if detailModal.context && Object.keys(detailModal.context).length > 0}
            <div>
              <span class="text-sm text-muted-foreground dark:text-muted-foreground">컨텍스트</span>
              <pre class="mt-1 p-3 bg-muted dark:bg-gray-900 rounded text-xs overflow-auto">{JSON.stringify(detailModal.context, null, 2)}</pre>
            </div>
          {/if}

          {#if detailModal.resolved}
            <div class="p-3 bg-green-50 dark:bg-green-900/20 rounded">
              <p class="text-green-800 dark:text-green-400">
                해결됨 ({detailModal.resolved_at ? new Date(detailModal.resolved_at).toLocaleString('ko-KR') : ''})
                {#if detailModal.resolved_by}
                  by {detailModal.resolved_by}
                {/if}
              </p>
              {#if detailModal.notes}
                <p class="text-sm text-green-700 dark:text-green-300 mt-1">{detailModal.notes}</p>
              {/if}
            </div>
          {:else}
            <button
              onclick={() => { resolveError(detailModal!.id); detailModal = null; }}
              class="w-full py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
            >
              해결 처리
            </button>
          {/if}
        </div>
      </div>
    </div>
  </div>
{/if}
