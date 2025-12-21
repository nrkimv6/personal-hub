<script lang="ts">
  import { onMount } from 'svelte';
  import { proxyApi } from '$lib/api';
  import type { ProxyStats, Proxy, ProxyCollectionRun } from '$lib/types';

  let stats: ProxyStats | null = null;
  let topProxies: Proxy[] = [];
  let recentRuns: ProxyCollectionRun[] = [];
  let loading = true;
  let error: string | null = null;

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    error = null;
    try {
      const [statsData, topData, runsData] = await Promise.all([
        proxyApi.stats(),
        proxyApi.top(10),
        proxyApi.runs(5)
      ]);
      stats = statsData;
      topProxies = topData;
      recentRuns = runsData;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터를 불러오는데 실패했습니다.';
    } finally {
      loading = false;
    }
  }

  function formatTime(seconds: number | null): string {
    if (seconds === null) return '-';
    return `${seconds.toFixed(2)}s`;
  }

  function formatPercent(value: number | null): string {
    if (value === null) return '-';
    return `${value.toFixed(1)}%`;
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return '-';
    // 서버에서 UTC로 저장된 시간을 KST로 변환
    const utcDate = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
    return new Date(utcDate).toLocaleString('ko-KR', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function formatDuration(seconds: number | null): string {
    if (seconds === null) return '-';
    if (seconds < 60) return `${Math.round(seconds)}초`;
    return `${Math.floor(seconds / 60)}분 ${Math.round(seconds % 60)}초`;
  }

  function getStatusBadgeClass(status: string): string {
    const classes: Record<string, string> = {
      running: 'bg-blue-100 text-blue-800',
      completed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
      cancelled: 'bg-gray-100 text-gray-800'
    };
    return classes[status] || 'bg-gray-100 text-gray-800';
  }
</script>

{#if loading}
  <div class="flex items-center justify-center py-12">
    <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    <span class="ml-3 text-gray-600">로딩 중...</span>
  </div>
{:else if error}
  <div class="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
    {error}
    <button on:click={loadData} class="ml-2 underline hover:no-underline">다시 시도</button>
  </div>
{:else if stats}
  <!-- 통계 카드 -->
  <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-8">
    <div class="bg-white rounded-lg shadow p-4">
      <div class="text-sm text-gray-500">전체 프록시</div>
      <div class="text-2xl font-bold text-gray-900">{stats.total.toLocaleString()}</div>
    </div>
    <div class="bg-white rounded-lg shadow p-4">
      <div class="text-sm text-gray-500">활성 프록시</div>
      <div class="text-2xl font-bold text-green-600">{stats.active.toLocaleString()}</div>
    </div>
    <div class="bg-white rounded-lg shadow p-4">
      <div class="text-sm text-gray-500">평균 응답시간</div>
      <div class="text-2xl font-bold text-blue-600">{formatTime(stats.avg_response_time)}</div>
    </div>
    <div class="bg-white rounded-lg shadow p-4">
      <div class="text-sm text-gray-500">전체 성공률</div>
      <div class="text-2xl font-bold text-purple-600">{formatPercent(stats.overall_success_rate)}</div>
    </div>
    <div class="bg-white rounded-lg shadow p-4">
      <div class="text-sm text-gray-500">오늘 검증</div>
      <div class="text-2xl font-bold text-orange-600">{stats.today_checks.toLocaleString()}</div>
    </div>
  </div>

  <!-- 상태별 분포 및 프로토콜별 분포 -->
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
    <!-- 상태별 분포 -->
    <div class="bg-white rounded-lg shadow p-6">
      <h3 class="text-lg font-semibold text-gray-900 mb-4">상태별 분포</h3>
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="w-3 h-3 rounded-full bg-green-500"></span>
            <span class="text-gray-700">Active</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="font-medium">{stats.active.toLocaleString()}</span>
            <span class="text-gray-500 text-sm">
              ({stats.total > 0 ? ((stats.active / stats.total) * 100).toFixed(1) : 0}%)
            </span>
          </div>
        </div>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="w-3 h-3 rounded-full bg-yellow-500"></span>
            <span class="text-gray-700">Pending</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="font-medium">{stats.pending.toLocaleString()}</span>
            <span class="text-gray-500 text-sm">
              ({stats.total > 0 ? ((stats.pending / stats.total) * 100).toFixed(1) : 0}%)
            </span>
          </div>
        </div>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="w-3 h-3 rounded-full bg-gray-500"></span>
            <span class="text-gray-700">Inactive</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="font-medium">{stats.inactive.toLocaleString()}</span>
            <span class="text-gray-500 text-sm">
              ({stats.total > 0 ? ((stats.inactive / stats.total) * 100).toFixed(1) : 0}%)
            </span>
          </div>
        </div>
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="w-3 h-3 rounded-full bg-red-500"></span>
            <span class="text-gray-700">Blacklisted</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="font-medium">{stats.blacklisted.toLocaleString()}</span>
            <span class="text-gray-500 text-sm">
              ({stats.total > 0 ? ((stats.blacklisted / stats.total) * 100).toFixed(1) : 0}%)
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 프로토콜별 분포 -->
    <div class="bg-white rounded-lg shadow p-6">
      <h3 class="text-lg font-semibold text-gray-900 mb-4">프로토콜별 분포</h3>
      <div class="space-y-3">
        {#each Object.entries(stats.by_protocol) as [protocol, count]}
          <div class="flex items-center justify-between">
            <span class="text-gray-700 uppercase">{protocol}</span>
            <div class="flex items-center gap-2">
              <span class="font-medium">{count.toLocaleString()}</span>
              <span class="text-gray-500 text-sm">
                ({stats.total > 0 ? ((count / stats.total) * 100).toFixed(1) : 0}%)
              </span>
            </div>
          </div>
        {:else}
          <p class="text-gray-500 text-sm">프로토콜 정보가 없습니다.</p>
        {/each}
      </div>
    </div>
  </div>

  <!-- TOP 10 프록시 및 최근 수집 이력 -->
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <!-- TOP 10 프록시 -->
    <div class="bg-white rounded-lg shadow">
      <div class="p-4 border-b border-gray-200">
        <h3 class="text-lg font-semibold text-gray-900">TOP 10 프록시</h3>
        <p class="text-sm text-gray-500">우선순위 점수 기준</p>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">프록시</th>
              <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">응답시간</th>
              <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">성공률</th>
              <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">점수</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            {#each topProxies as proxy}
              <tr class="hover:bg-gray-50">
                <td class="px-4 py-2">
                  <a href="/proxy/{proxy.id}" class="text-blue-600 hover:underline text-sm font-mono">
                    {proxy.host}:{proxy.port}
                  </a>
                </td>
                <td class="px-4 py-2 text-right text-sm text-gray-600">
                  {formatTime(proxy.avg_response_time)}
                </td>
                <td class="px-4 py-2 text-right text-sm text-gray-600">
                  {formatPercent(proxy.success_rate)}
                </td>
                <td class="px-4 py-2 text-right text-sm font-medium text-gray-900">
                  {proxy.priority_score.toFixed(1)}
                </td>
              </tr>
            {:else}
              <tr>
                <td colspan="4" class="px-4 py-8 text-center text-gray-500">
                  프록시 데이터가 없습니다.
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      {#if topProxies.length > 0}
        <div class="p-4 border-t border-gray-200">
          <a href="/proxy/list" class="text-blue-600 hover:underline text-sm">전체 목록 보기 &rarr;</a>
        </div>
      {/if}
    </div>

    <!-- 최근 수집 이력 -->
    <div class="bg-white rounded-lg shadow">
      <div class="p-4 border-b border-gray-200">
        <h3 class="text-lg font-semibold text-gray-900">최근 수집 이력</h3>
        <p class="text-sm text-gray-500">최근 5회 수집 결과</p>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">시작 시간</th>
              <th class="px-4 py-2 text-center text-xs font-medium text-gray-500 uppercase">상태</th>
              <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">수집</th>
              <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">유효</th>
              <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">소요</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            {#each recentRuns as run}
              <tr class="hover:bg-gray-50">
                <td class="px-4 py-2 text-sm text-gray-600">
                  {formatDate(run.started_at)}
                </td>
                <td class="px-4 py-2 text-center">
                  <span class="px-2 py-0.5 text-xs rounded-full {getStatusBadgeClass(run.status)}">
                    {run.status}
                  </span>
                </td>
                <td class="px-4 py-2 text-right text-sm text-gray-600">
                  {run.collected_count.toLocaleString()}
                </td>
                <td class="px-4 py-2 text-right text-sm text-gray-600">
                  {run.valid_count.toLocaleString()}
                </td>
                <td class="px-4 py-2 text-right text-sm text-gray-600">
                  {formatDuration(run.duration_seconds)}
                </td>
              </tr>
            {:else}
              <tr>
                <td colspan="5" class="px-4 py-8 text-center text-gray-500">
                  수집 이력이 없습니다.
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- 국가별 분포 -->
  {#if stats.by_country && stats.by_country.length > 0}
    <div class="mt-6 bg-white rounded-lg shadow p-6">
      <h3 class="text-lg font-semibold text-gray-900 mb-4">국가별 분포 (TOP 10)</h3>
      <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
        {#each stats.by_country.slice(0, 10) as item}
          <div class="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <span class="text-gray-700">{item.country || 'Unknown'}</span>
            <span class="font-medium">{item.count.toLocaleString()}</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}
{/if}
