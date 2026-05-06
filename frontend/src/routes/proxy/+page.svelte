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
      running: 'bg-primary-light text-primary',
      completed: 'bg-success-light text-success',
      failed: 'bg-error-light text-error',
      cancelled: 'bg-muted text-foreground'
    };
    return classes[status] || 'bg-muted text-foreground';
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
{:else if stats}
  <div class="space-y-6">
    <!-- 통계 카드 -->
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-muted-foreground">전체 프록시</div>
        <div class="text-2xl font-bold text-foreground">{stats.total.toLocaleString()}</div>
      </div>
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-muted-foreground">활성 프록시</div>
        <div class="text-2xl font-bold text-success">{stats.active.toLocaleString()}</div>
      </div>
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-muted-foreground">평균 응답시간</div>
        <div class="text-2xl font-bold text-primary">{formatTime(stats.avg_response_time)}</div>
      </div>
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-muted-foreground">전체 성공률</div>
        <div class="text-2xl font-bold text-purple">{formatPercent(stats.overall_success_rate)}</div>
      </div>
      <div class="bg-white rounded-lg shadow p-4">
        <div class="text-sm text-muted-foreground">오늘 검증</div>
        <div class="text-2xl font-bold text-warning">{stats.today_checks.toLocaleString()}</div>
      </div>
    </div>

    <!-- 상태별 분포 및 프로토콜별 분포 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- 상태별 분포 -->
      <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold text-foreground mb-4">상태별 분포</h3>
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="w-3 h-3 rounded-full bg-success"></span>
              <span class="text-foreground">Active</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="font-medium">{stats.active.toLocaleString()}</span>
              <span class="text-muted-foreground text-sm">
                ({stats.total > 0 ? ((stats.active / stats.total) * 100).toFixed(1) : 0}%)
              </span>
            </div>
          </div>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="w-3 h-3 rounded-full bg-warning"></span>
              <span class="text-foreground">Pending</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="font-medium">{stats.pending.toLocaleString()}</span>
              <span class="text-muted-foreground text-sm">
                ({stats.total > 0 ? ((stats.pending / stats.total) * 100).toFixed(1) : 0}%)
              </span>
            </div>
          </div>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="w-3 h-3 rounded-full bg-background0"></span>
              <span class="text-foreground">Inactive</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="font-medium">{stats.inactive.toLocaleString()}</span>
              <span class="text-muted-foreground text-sm">
                ({stats.total > 0 ? ((stats.inactive / stats.total) * 100).toFixed(1) : 0}%)
              </span>
            </div>
          </div>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="w-3 h-3 rounded-full bg-error"></span>
              <span class="text-foreground">Blacklisted</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="font-medium">{stats.blacklisted.toLocaleString()}</span>
              <span class="text-muted-foreground text-sm">
                ({stats.total > 0 ? ((stats.blacklisted / stats.total) * 100).toFixed(1) : 0}%)
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 프로토콜별 분포 -->
      <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold text-foreground mb-4">프로토콜별 분포</h3>
        <div class="space-y-3">
          {#each Object.entries(stats.by_protocol) as [protocol, count]}
            <div class="flex items-center justify-between">
              <span class="text-foreground uppercase">{protocol}</span>
              <div class="flex items-center gap-2">
                <span class="font-medium">{count.toLocaleString()}</span>
                <span class="text-muted-foreground text-sm">
                  ({stats.total > 0 ? ((count / stats.total) * 100).toFixed(1) : 0}%)
                </span>
              </div>
            </div>
          {:else}
            <p class="text-muted-foreground text-sm">프로토콜 정보가 없습니다.</p>
          {/each}
        </div>
      </div>
    </div>

    <!-- TOP 10 프록시 및 최근 수집 이력 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- TOP 10 프록시 -->
      <div class="bg-white rounded-lg shadow">
        <div class="p-4 border-b border-border">
          <h3 class="text-lg font-semibold text-foreground">TOP 10 프록시</h3>
          <p class="text-sm text-muted-foreground">우선순위 점수 기준</p>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead class="bg-background">
              <tr>
                <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">프록시</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">응답시간</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">성공률</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">점수</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              {#each topProxies as proxy}
                <tr class="hover:bg-muted">
                  <td class="px-4 py-2">
                    <a href="/proxy/{proxy.id}" class="text-primary hover:underline text-sm font-mono">
                      {proxy.host}:{proxy.port}
                    </a>
                  </td>
                  <td class="px-4 py-2 text-right text-sm text-muted-foreground">
                    {formatTime(proxy.avg_response_time)}
                  </td>
                  <td class="px-4 py-2 text-right text-sm text-muted-foreground">
                    {formatPercent(proxy.success_rate)}
                  </td>
                  <td class="px-4 py-2 text-right text-sm font-medium text-foreground">
                    {proxy.priority_score.toFixed(1)}
                  </td>
                </tr>
              {:else}
                <tr>
                  <td colspan="4" class="px-4 py-8 text-center text-muted-foreground">
                    프록시 데이터가 없습니다.
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        {#if topProxies.length > 0}
          <div class="p-4 border-t border-border">
            <a href="/proxy/list" class="text-primary hover:underline text-sm">전체 목록 보기 &rarr;</a>
          </div>
        {/if}
      </div>

      <!-- 최근 수집 이력 -->
      <div class="bg-white rounded-lg shadow">
        <div class="p-4 border-b border-border">
          <h3 class="text-lg font-semibold text-foreground">최근 수집 이력</h3>
          <p class="text-sm text-muted-foreground">최근 5회 수집 결과</p>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead class="bg-background">
              <tr>
                <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">시작 시간</th>
                <th class="px-4 py-2 text-center text-xs font-medium text-muted-foreground uppercase">상태</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">수집</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">유효</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">소요</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              {#each recentRuns as run}
                <tr class="hover:bg-muted">
                  <td class="px-4 py-2 text-sm text-muted-foreground">
                    {formatDate(run.started_at)}
                  </td>
                  <td class="px-4 py-2 text-center">
                    <span class="px-2 py-0.5 text-xs rounded-full {getStatusBadgeClass(run.status)}">
                      {run.status}
                    </span>
                  </td>
                  <td class="px-4 py-2 text-right text-sm text-muted-foreground">
                    {run.collected_count.toLocaleString()}
                  </td>
                  <td class="px-4 py-2 text-right text-sm text-muted-foreground">
                    {run.valid_count.toLocaleString()}
                  </td>
                  <td class="px-4 py-2 text-right text-sm text-muted-foreground">
                    {formatDuration(run.duration_seconds)}
                  </td>
                </tr>
              {:else}
                <tr>
                  <td colspan="5" class="px-4 py-8 text-center text-muted-foreground">
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
      <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold text-foreground mb-4">국가별 분포 (TOP 10)</h3>
        <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
          {#each stats.by_country.slice(0, 10) as item}
            <div class="flex items-center justify-between p-3 bg-background rounded-lg">
              <span class="text-foreground">{item.country || 'Unknown'}</span>
              <span class="font-medium">{item.count.toLocaleString()}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  </div>
{/if}
