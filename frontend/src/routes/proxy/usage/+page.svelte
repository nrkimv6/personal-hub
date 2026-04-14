<script lang="ts">
  import { onMount } from 'svelte';
  import { proxyUsageApi } from '$lib/api';
  import type { ProxyUsageStatsResponse, ProxyUsageLog, RetryHistoryResponse } from '$lib/types';

  // 상태
  let stats: ProxyUsageStatsResponse | null = null;
  let recentLogs: ProxyUsageLog[] = [];
  let retryHistory: RetryHistoryResponse[] = [];
  let failedProxies: Array<{
    proxy_host: string;
    fail_count: number;
    last_error_type: string | null;
    last_failed_at: string;
  }> = [];

  let loading = true;
  let error: string | null = null;

  // 필터
  let hoursFilter = 24;
  let minFailures = 3;

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    error = null;
    try {
      const [statsData, logsData, retriesData, failedData] = await Promise.all([
        proxyUsageApi.stats({ hours: hoursFilter }),
        proxyUsageApi.recent({ limit: 50 }),
        proxyUsageApi.retries({ limit: 20 }),
        proxyUsageApi.failed({ hours: hoursFilter, min_failures: minFailures, limit: 20 })
      ]);
      stats = statsData;
      recentLogs = logsData;
      retryHistory = retriesData;
      failedProxies = failedData;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터를 불러오는데 실패했습니다.';
    } finally {
      loading = false;
    }
  }

  async function handleCleanup() {
    if (!confirm('30일 이전의 로그를 삭제하시겠습니까?')) return;

    try {
      const result = await proxyUsageApi.cleanup(30);
      alert(`${result.deleted_count}개의 로그가 삭제되었습니다.`);
      await loadData();
    } catch (e) {
      alert('정리 중 오류가 발생했습니다: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
    }
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return '-';
    // 서버에서 UTC로 저장된 시간을 KST로 변환
    const utcDate = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
    return new Date(utcDate).toLocaleString('ko-KR', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  }

  function formatPercent(value: number | null): string {
    if (value === null || value === undefined) return '-';
    return `${value.toFixed(1)}%`;
  }

  function formatMs(ms: number | null | undefined): string {
    if (ms === null || ms === undefined) return '-';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  function getErrorTypeBadgeClass(errorType: string | null): string {
    if (!errorType) return 'bg-muted text-foreground';
    const classes: Record<string, string> = {
      timeout: 'bg-warning-light text-warning-foreground',
      connection_error: 'bg-error-light text-error',
      http_403: 'bg-warning-light text-warning',
      http_429: 'bg-purple-light text-purple-800',
      http_500: 'bg-error-light text-error',
      unknown: 'bg-muted text-foreground'
    };
    return classes[errorType] || 'bg-muted text-foreground';
  }

  function truncateUrl(url: string, maxLen = 40): string {
    if (url.length <= maxLen) return url;
    return url.slice(0, maxLen) + '...';
  }
</script>

{#if loading}
  <div class="flex items-center justify-center py-12">
    <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    <span class="ml-3 text-muted-foreground">로딩 중...</span>
  </div>
{:else if error}
  <div class="bg-error-light border border-red-200 rounded-lg p-4 text-error">
    {error}
    <button onclick={loadData} class="ml-2 underline hover:no-underline">다시 시도</button>
  </div>
{:else}
  <!-- 필터 및 액션 -->
  <div class="flex items-center justify-between mb-6">
    <div class="flex items-center gap-4">
      <label class="flex items-center gap-2 text-sm text-muted-foreground">
        <span>기간:</span>
        <select
          bind:value={hoursFilter}
          onchange={loadData}
          class="px-3 py-1.5 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        >
          <option value={1}>1시간</option>
          <option value={6}>6시간</option>
          <option value={24}>24시간</option>
          <option value={72}>3일</option>
          <option value={168}>1주일</option>
        </select>
      </label>
    </div>
    <button
      onclick={handleCleanup}
      class="px-4 py-2 text-sm text-error border border-red-300 rounded-md hover:bg-error-light transition-colors"
    >
      오래된 로그 정리
    </button>
  </div>

  {#if stats}
    <!-- 통계 카드 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-muted-foreground">사용된 프록시</div>
        <div class="text-2xl font-bold text-foreground">{stats.total_proxies_used.toLocaleString()}</div>
      </div>
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-muted-foreground">총 시도 횟수</div>
        <div class="text-2xl font-bold text-primary">{stats.total_attempts.toLocaleString()}</div>
      </div>
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-muted-foreground">전체 성공률</div>
        <div class="text-2xl font-bold {stats.overall_success_rate >= 80 ? 'text-success' : stats.overall_success_rate >= 50 ? 'text-warning-foreground' : 'text-error'}">
          {formatPercent(stats.overall_success_rate)}
        </div>
      </div>
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-muted-foreground">에러 유형</div>
        <div class="text-2xl font-bold text-warning">
          {Object.keys(stats.by_error_type || {}).length}
        </div>
      </div>
    </div>

    <!-- 에러 유형별 분포 -->
    {#if stats.by_error_type && Object.keys(stats.by_error_type).length > 0}
      <div class="bg-white rounded-lg shadow p-6 mb-8">
        <h3 class="text-lg font-semibold text-foreground mb-4">에러 유형별 분포</h3>
        <div class="flex flex-wrap gap-3">
          {#each Object.entries(stats.by_error_type) as [errorType, count]}
            <div class="flex items-center gap-2 px-3 py-2 rounded-lg {getErrorTypeBadgeClass(errorType)}">
              <span class="font-medium">{errorType}</span>
              <span class="text-sm opacity-75">({count})</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- 프록시별 통계 -->
    {#if stats.by_proxy && stats.by_proxy.length > 0}
      <div class="bg-white rounded-lg shadow mb-8">
        <div class="p-4 border-b border-border">
          <h3 class="text-lg font-semibold text-foreground">프록시별 사용 통계</h3>
          <p class="text-sm text-muted-foreground">시도 횟수 기준 상위 프록시</p>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead class="bg-background">
              <tr>
                <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">프록시 호스트</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">시도</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">성공</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">실패</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">성공률</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">평균 응답</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">마지막 사용</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              {#each stats.by_proxy.slice(0, 15) as proxy}
                <tr class="hover:bg-muted">
                  <td class="px-4 py-2 font-mono text-sm text-foreground">{proxy.proxy_host}</td>
                  <td class="px-4 py-2 text-right text-sm text-muted-foreground">{proxy.total_attempts}</td>
                  <td class="px-4 py-2 text-right text-sm text-success">{proxy.success_count}</td>
                  <td class="px-4 py-2 text-right text-sm text-error">{proxy.fail_count}</td>
                  <td class="px-4 py-2 text-right text-sm {proxy.success_rate >= 80 ? 'text-success' : proxy.success_rate >= 50 ? 'text-warning-foreground' : 'text-error'}">
                    {formatPercent(proxy.success_rate)}
                  </td>
                  <td class="px-4 py-2 text-right text-sm text-muted-foreground">{formatMs(proxy.avg_response_time_ms)}</td>
                  <td class="px-4 py-2 text-right text-sm text-muted-foreground">{formatDate(proxy.last_used_at)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}
  {/if}

  <!-- 실패 프록시 목록 -->
  {#if failedProxies.length > 0}
    <div class="bg-white rounded-lg shadow mb-8">
      <div class="p-4 border-b border-border bg-error-light">
        <h3 class="text-lg font-semibold text-red-900">실패 프록시 (최근 {hoursFilter}시간)</h3>
        <p class="text-sm text-error">{minFailures}회 이상 실패한 프록시</p>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead class="bg-background">
            <tr>
              <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">프록시 호스트</th>
              <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">실패 횟수</th>
              <th class="px-4 py-2 text-center text-xs font-medium text-muted-foreground uppercase">마지막 에러</th>
              <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">마지막 실패</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            {#each failedProxies as proxy}
              <tr class="hover:bg-muted">
                <td class="px-4 py-2 font-mono text-sm text-foreground">{proxy.proxy_host}</td>
                <td class="px-4 py-2 text-right text-sm font-medium text-error">{proxy.fail_count}</td>
                <td class="px-4 py-2 text-center">
                  <span class="px-2 py-0.5 text-xs rounded-full {getErrorTypeBadgeClass(proxy.last_error_type)}">
                    {proxy.last_error_type || '-'}
                  </span>
                </td>
                <td class="px-4 py-2 text-right text-sm text-muted-foreground">{formatDate(proxy.last_failed_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}

  <!-- 재시도 이력 -->
  {#if retryHistory.length > 0}
    <div class="bg-white rounded-lg shadow mb-8">
      <div class="p-4 border-b border-border">
        <h3 class="text-lg font-semibold text-foreground">재시도 이력</h3>
        <p class="text-sm text-muted-foreground">최근 요청의 재시도 과정</p>
      </div>
      <div class="divide-y divide-border">
        {#each retryHistory as history}
          <div class="p-4">
            <div class="flex items-center justify-between mb-2">
              <div class="flex items-center gap-3">
                <span class="px-2 py-0.5 text-xs rounded-full {history.final_success ? 'bg-success-light text-success' : 'bg-error-light text-error'}">
                  {history.final_success ? '성공' : '실패'}
                </span>
                <span class="text-sm text-muted-foreground">
                  {history.business_name || '-'} / {history.biz_item_name || '-'}
                </span>
              </div>
              <span class="text-xs text-muted-foreground">
                {history.total_attempts}회 시도 | {history.total_duration_ms ? formatMs(history.total_duration_ms) : '-'}
              </span>
            </div>

            <div class="flex flex-wrap gap-2 mt-2">
              {#each history.attempts as attempt}
                <div class="flex items-center gap-1 px-2 py-1 rounded text-xs {attempt.success ? 'bg-success-light text-success' : 'bg-error-light text-error'}">
                  <span class="font-medium">#{attempt.attempt_number}</span>
                  <span class="font-mono">{attempt.proxy_host || truncateUrl(attempt.proxy_url, 15)}</span>
                  {#if attempt.success}
                    <span class="text-success">{attempt.http_status || 'OK'}</span>
                  {:else}
                    <span>{attempt.error_type || 'error'}</span>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- 최근 사용 로그 -->
  <div class="bg-white rounded-lg shadow">
    <div class="p-4 border-b border-border">
      <h3 class="text-lg font-semibold text-foreground">최근 사용 로그</h3>
      <p class="text-sm text-muted-foreground">최근 50건의 프록시 사용 기록</p>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full">
        <thead class="bg-background">
          <tr>
            <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">시간</th>
            <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">프록시</th>
            <th class="px-4 py-2 text-center text-xs font-medium text-muted-foreground uppercase">시도</th>
            <th class="px-4 py-2 text-center text-xs font-medium text-muted-foreground uppercase">결과</th>
            <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">응답시간</th>
            <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">에러</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          {#each recentLogs as log}
            <tr class="hover:bg-muted">
              <td class="px-4 py-2 text-sm text-muted-foreground">{formatDate(log.timestamp)}</td>
              <td class="px-4 py-2 font-mono text-sm text-foreground">{log.proxy_host || truncateUrl(log.proxy_url, 25)}</td>
              <td class="px-4 py-2 text-center text-sm text-muted-foreground">#{log.attempt_number}</td>
              <td class="px-4 py-2 text-center">
                {#if log.success}
                  <span class="px-2 py-0.5 text-xs rounded-full bg-success-light text-success">
                    {log.http_status || 'OK'}
                  </span>
                {:else}
                  <span class="px-2 py-0.5 text-xs rounded-full bg-error-light text-error">
                    {log.http_status || 'FAIL'}
                  </span>
                {/if}
              </td>
              <td class="px-4 py-2 text-right text-sm text-muted-foreground">{formatMs(log.response_time_ms)}</td>
              <td class="px-4 py-2 text-sm">
                {#if log.error_type}
                  <span class="px-2 py-0.5 text-xs rounded-full {getErrorTypeBadgeClass(log.error_type)}">
                    {log.error_type}
                  </span>
                {:else}
                  <span class="text-muted-foreground">-</span>
                {/if}
              </td>
            </tr>
          {:else}
            <tr>
              <td colspan="6" class="px-4 py-8 text-center text-muted-foreground">
                사용 로그가 없습니다.
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{/if}
