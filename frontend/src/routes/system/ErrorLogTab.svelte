<script lang="ts">
  import { onMount } from 'svelte';
  import {
    errorApi,
    type ErrorLog,
    type ErrorLogStatsResponse,
    type ErrorListParams,
    type OperationalIssue,
  } from '$lib/api';
  import { createSelection } from '$lib/utils/selection.svelte';

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
  let operationalLoading = $state(true);

  // 필터
  let source = $state('');
  let severity = $state('');
  let resolved = $state<boolean | undefined>(undefined);
  let search = $state('');
  let page = $state(1);
  let pageSize = $state(50);

  // 선택 상태
  const selection = createSelection();

  // 모달
  let detailModal = $state<ErrorLog | null>(null);
  let sources = $state<string[]>([]);
  let operationalIssues = $state<OperationalIssue[]>([]);
  let operationalSource = $state('');

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

  async function fetchOperationalIssues() {
    operationalLoading = true;
    try {
      const result = await errorApi.operational({
        source: operationalSource || undefined,
        limit: 20,
      });
      operationalIssues = result.items;
    } catch (e) {
      console.error('Failed to fetch operational issues:', e);
    } finally {
      operationalLoading = false;
    }
  }

  function handleFilterChange() {
    page = 1;
    selection.clear();
    fetchErrors();
  }

  function selectOperationalSource(next: string) {
    operationalSource = next;
    fetchOperationalIssues();
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
    if (selection.count === 0) return;
    try {
      await errorApi.resolveBulk(selection.toArray(), 'user');
      selection.clear();
      fetchErrors();
      fetchStats();
    } catch (e) {
      console.error('Failed to resolve errors:', e);
    }
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
      case 'critical': return 'bg-error-light text-error dark:bg-red-900/30 dark:text-red-400';
      case 'error': return 'bg-warning-light text-warning dark:bg-orange-900/30 dark:text-orange-400';
      case 'warning': return 'bg-warning-light text-warning-foreground dark:bg-yellow-900/30 dark:text-yellow-400';
      default: return 'bg-muted text-foreground dark:bg-gray-800 dark:text-muted-foreground';
    }
  }

  function getSourceColor(src: string): string {
    const colors: Record<string, string> = {
      api: 'bg-primary-light text-primary dark:bg-blue-900/30 dark:text-blue-400',
      database: 'bg-error-light text-error dark:bg-red-900/30 dark:text-red-300',
      migration: 'bg-warning-light text-warning dark:bg-orange-900/30 dark:text-orange-300',
      worker: 'bg-purple-light text-purple-800 dark:bg-purple-900/30 dark:text-purple-400',
      naver: 'bg-success-light text-success dark:bg-green-900/30 dark:text-green-400',
      instagram: 'bg-pink-light text-pink dark:bg-pink-900/30 dark:text-pink-400',
      writing: 'bg-primary-light text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-400',
    };
    return colors[src] || 'bg-muted text-foreground dark:bg-gray-800 dark:text-muted-foreground';
  }

  onMount(() => {
    fetchStats();
    fetchErrors();
    fetchSources();
    fetchOperationalIssues();
    const interval = setInterval(() => {
      fetchStats();
      fetchErrors();
      fetchOperationalIssues();
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
        <div class="text-sm text-error">Critical</div>
        <div class="text-2xl font-bold text-error">{stats.summary.critical_count}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-warning">Error</div>
        <div class="text-2xl font-bold text-warning">{stats.summary.error_count}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-warning">Warning</div>
        <div class="text-2xl font-bold text-warning-foreground">{stats.summary.warning_count}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-muted-foreground dark:text-muted-foreground">미해결</div>
        <div class="text-2xl font-bold text-foreground dark:text-white">{stats.summary.unresolved_count}</div>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
        <div class="text-sm text-success">해결률</div>
        <div class="text-2xl font-bold text-success">{stats.summary.resolve_rate}%</div>
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

  <!-- DB / 마이그레이션 운영 장애 -->
  <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-sm font-medium text-foreground dark:text-white">DB / 마이그레이션 장애 이력</h3>
        <p class="text-xs text-muted-foreground dark:text-muted-foreground mt-1">
          DB 연결 실패나 스키마/마이그레이션 오류는 파일에도 기록되어 DB 장애 중에도 보존됩니다.
        </p>
      </div>
      <div class="flex gap-2">
        <button
          onclick={() => selectOperationalSource('')}
          class={`px-3 py-1.5 rounded-lg text-xs border ${operationalSource === '' ? 'bg-primary text-white border-primary' : 'border-border text-muted-foreground dark:border-gray-600 dark:text-muted-foreground'}`}
        >
          전체
        </button>
        <button
          onclick={() => selectOperationalSource('database')}
          class={`px-3 py-1.5 rounded-lg text-xs border ${operationalSource === 'database' ? 'bg-error text-white border-error' : 'border-border text-muted-foreground dark:border-gray-600 dark:text-muted-foreground'}`}
        >
          DB
        </button>
        <button
          onclick={() => selectOperationalSource('migration')}
          class={`px-3 py-1.5 rounded-lg text-xs border ${operationalSource === 'migration' ? 'bg-warning text-white border-warning' : 'border-border text-muted-foreground dark:border-gray-600 dark:text-muted-foreground'}`}
        >
          마이그레이션
        </button>
      </div>
    </div>

    {#if operationalLoading}
      <div class="text-sm text-muted-foreground dark:text-muted-foreground">운영 장애 이력 로딩 중...</div>
    {:else if operationalIssues.length === 0}
      <div class="text-sm text-muted-foreground dark:text-muted-foreground">기록된 운영 장애가 없습니다.</div>
    {:else}
      <div class="space-y-3">
        {#each operationalIssues as issue}
          <div class="border border-border dark:border-gray-700 rounded-lg p-3 space-y-2">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs text-muted-foreground dark:text-muted-foreground">{formatDate(issue.created_at)}</span>
              <span class="px-2 py-1 text-xs rounded-full {getSourceColor(issue.source)}">{issue.source}</span>
              <span class="px-2 py-1 text-xs rounded-full {getSeverityColor(issue.severity)}">{issue.severity}</span>
              <span class="text-xs font-mono text-foreground dark:text-gray-300">{issue.error_type}</span>
            </div>
            <div class="text-sm text-foreground dark:text-white break-words">{issue.message}</div>
            {#if issue.context && Object.keys(issue.context).length > 0}
              <details class="text-xs">
                <summary class="cursor-pointer text-muted-foreground dark:text-muted-foreground">컨텍스트</summary>
                <pre class="mt-2 p-3 bg-muted dark:bg-gray-900 rounded overflow-auto">{JSON.stringify(issue.context, null, 2)}</pre>
              </details>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- 필터 -->
  <div class="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
    <div class="flex flex-wrap gap-4 items-end">
      <div>
        <label for="error-log-source" class="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">소스</label>
        <select
          id="error-log-source"
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
        <label for="error-log-severity" class="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">심각도</label>
        <select
          id="error-log-severity"
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
        <label for="error-log-resolved" class="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">해결 상태</label>
        <select
          id="error-log-resolved"
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
        <label for="error-log-search" class="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">검색</label>
        <input
          id="error-log-search"
          type="text"
          bind:value={search}
          onkeyup={(e) => e.key === 'Enter' && handleFilterChange()}
          placeholder="메시지 검색..."
          class="w-full px-3 py-2 border border-border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-foreground dark:text-white text-sm"
        />
      </div>
      {#if selection.count > 0}
        <button
          onclick={resolveBulk}
          class="px-4 py-2 bg-success text-white rounded-lg hover:bg-success/90 text-sm"
        >
          {selection.count}개 해결 처리
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
            <input type="checkbox" checked={selection.isAllSelected(errors.map(e => e.id))} onchange={() => selection.selectAll(errors.map(e => e.id))} />
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
                  checked={selection.has(error.id)}
                  onchange={() => selection.toggle(error.id)}
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
                  <span class="text-success">해결됨</span>
                {:else}
                  <span class="text-error">미해결</span>
                {/if}
              </td>
              <td class="px-4 py-3 text-right">
                <button
                  onclick={() => detailModal = error}
                  class="text-primary hover:text-primary-hover dark:text-blue-400 dark:hover:text-blue-300 text-sm mr-2"
                >
                  상세
                </button>
                {#if !error.resolved}
                  <button
                    onclick={() => resolveError(error.id)}
                    class="text-success hover:text-success dark:text-green-400 dark:hover:text-green-300 text-sm"
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
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" role="button" tabindex="-1" onclick={() => detailModal = null} onkeydown={(e) => { if (e.key === 'Escape') detailModal = null; }}>
    <div class="bg-white dark:bg-gray-800 rounded-lg max-w-3xl w-full max-h-[80vh] overflow-auto m-4" role="dialog" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
      <div class="p-6">
        <div class="flex justify-between items-start mb-4">
          <h2 class="text-lg font-bold text-foreground dark:text-white">에러 상세</h2>
          <button onclick={() => detailModal = null} class="text-muted-foreground hover:text-foreground dark:text-muted-foreground dark:hover:text-gray-200" aria-label="닫기">
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
            <div class="p-3 bg-success-light dark:bg-green-900/20 rounded">
              <p class="text-success dark:text-green-400">
                해결됨 ({detailModal.resolved_at ? new Date(detailModal.resolved_at).toLocaleString('ko-KR') : ''})
                {#if detailModal.resolved_by}
                  by {detailModal.resolved_by}
                {/if}
              </p>
              {#if detailModal.notes}
                <p class="text-sm text-success dark:text-green-300 mt-1">{detailModal.notes}</p>
              {/if}
            </div>
          {:else}
            <button
              onclick={() => { resolveError(detailModal!.id); detailModal = null; }}
              class="w-full py-2 bg-success text-white rounded-lg hover:bg-success/90"
            >
              해결 처리
            </button>
          {/if}
        </div>
      </div>
    </div>
  </div>
{/if}
