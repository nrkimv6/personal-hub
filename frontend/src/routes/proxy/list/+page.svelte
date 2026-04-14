<script lang="ts">
  import { onMount } from 'svelte';
  import { proxyApi } from '$lib/api';
  import type { Proxy, ProxyListParams, ProxyListResponse } from '$lib/types';

  let proxies: Proxy[] = [];
  let total = 0;
  let page = 1;
  let pageSize = 50;
  let totalPages = 0;
  let loading = true;
  let error: string | null = null;

  // 필터
  let statusFilter = '';
  let protocolFilter = '';
  let searchQuery = '';
  let sortBy = 'priority_score';
  let sortOrder: 'asc' | 'desc' = 'desc';

  const statusOptions = [
    { value: '', label: '전체 상태' },
    { value: 'active', label: 'Active' },
    { value: 'pending', label: 'Pending' },
    { value: 'inactive', label: 'Inactive' },
    { value: 'blacklisted', label: 'Blacklisted' }
  ];

  const protocolOptions = [
    { value: '', label: '전체 프로토콜' },
    { value: 'http', label: 'HTTP' },
    { value: 'https', label: 'HTTPS' },
    { value: 'socks5', label: 'SOCKS5' }
  ];

  const sortOptions = [
    { value: 'priority_score', label: '우선순위' },
    { value: 'avg_response_time', label: '응답시간' },
    { value: 'success_count', label: '성공횟수' },
    { value: 'last_checked_at', label: '마지막 검증' },
    { value: 'first_seen_at', label: '등록일' }
  ];

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    error = null;
    try {
      const params: ProxyListParams = {
        page,
        page_size: pageSize,
        sort_by: sortBy,
        sort_order: sortOrder
      };
      if (statusFilter) params.status = statusFilter;
      if (protocolFilter) params.protocol = protocolFilter;
      if (searchQuery) params.search = searchQuery;

      const response: ProxyListResponse = await proxyApi.list(params);
      proxies = response.items;
      total = response.total;
      totalPages = response.total_pages;
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터를 불러오는데 실패했습니다.';
    } finally {
      loading = false;
    }
  }

  function handleFilterChange() {
    page = 1;
    loadData();
  }

  function handleSort(column: string) {
    if (sortBy === column) {
      sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
    } else {
      sortBy = column;
      sortOrder = 'desc';
    }
    loadData();
  }

  function handlePageChange(newPage: number) {
    if (newPage < 1 || newPage > totalPages) return;
    page = newPage;
    loadData();
  }

  async function handleStatusChange(proxy: Proxy, newStatus: string) {
    try {
      await proxyApi.updateStatus(proxy.id, newStatus);
      await loadData();
    } catch (e) {
      alert(e instanceof Error ? e.message : '상태 변경에 실패했습니다.');
    }
  }

  async function handleDelete(proxy: Proxy) {
    if (!confirm(`정말 ${proxy.host}:${proxy.port} 프록시를 삭제하시겠습니까?`)) return;
    try {
      await proxyApi.delete(proxy.id);
      await loadData();
    } catch (e) {
      alert(e instanceof Error ? e.message : '삭제에 실패했습니다.');
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

  function getStatusBadgeClass(status: string): string {
    const classes: Record<string, string> = {
      active: 'bg-success-light text-success',
      pending: 'bg-warning-light text-warning-foreground',
      inactive: 'bg-muted text-foreground',
      blacklisted: 'bg-error-light text-error'
    };
    return classes[status] || 'bg-muted text-foreground';
  }

  function getSortIcon(column: string): string {
    if (sortBy !== column) return '';
    return sortOrder === 'asc' ? ' ↑' : ' ↓';
  }
</script>

<!-- 필터 바 -->
<div class="bg-white rounded-lg shadow p-4 mb-6">
  <div class="flex flex-wrap gap-4 items-end">
    <div class="flex-1 min-w-[200px]">
      <label for="search" class="block text-sm font-medium text-foreground mb-1">검색</label>
      <input
        id="search"
        type="text"
        bind:value={searchQuery}
        onkeyup={(e) => e.key === 'Enter' && handleFilterChange()}
        placeholder="IP, 호스트 검색..."
        class="w-full px-3 py-2 border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </div>
    <div>
      <label for="status" class="block text-sm font-medium text-foreground mb-1">상태</label>
      <select
        id="status"
        bind:value={statusFilter}
        onchange={handleFilterChange}
        class="px-3 py-2 border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {#each statusOptions as opt}
          <option value={opt.value}>{opt.label}</option>
        {/each}
      </select>
    </div>
    <div>
      <label for="protocol" class="block text-sm font-medium text-foreground mb-1">프로토콜</label>
      <select
        id="protocol"
        bind:value={protocolFilter}
        onchange={handleFilterChange}
        class="px-3 py-2 border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {#each protocolOptions as opt}
          <option value={opt.value}>{opt.label}</option>
        {/each}
      </select>
    </div>
    <div>
      <label for="sort" class="block text-sm font-medium text-foreground mb-1">정렬</label>
      <select
        id="sort"
        bind:value={sortBy}
        onchange={() => loadData()}
        class="px-3 py-2 border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {#each sortOptions as opt}
          <option value={opt.value}>{opt.label}</option>
        {/each}
      </select>
    </div>
    <button
      onclick={handleFilterChange}
      class="px-4 py-2 bg-primary text-white rounded-md hover:bg-primary-hover transition-colors"
    >
      검색
    </button>
  </div>
</div>

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
  <!-- 결과 정보 -->
  <div class="mb-4 text-sm text-muted-foreground">
    전체 {total.toLocaleString()}개 중 {proxies.length}개 표시
    (페이지 {page}/{totalPages})
  </div>

  <!-- 테이블 -->
  <div class="bg-white rounded-lg shadow overflow-hidden">
    <div class="overflow-x-auto">
      <table class="w-full">
        <thead class="bg-background">
          <tr>
            <th
              class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider cursor-pointer hover:bg-muted"
              onclick={() => handleSort('host')}
            >
              프록시{getSortIcon('host')}
            </th>
            <th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase tracking-wider">
              프로토콜
            </th>
            <th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase tracking-wider">
              상태
            </th>
            <th
              class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase tracking-wider cursor-pointer hover:bg-muted"
              onclick={() => handleSort('avg_response_time')}
            >
              응답시간{getSortIcon('avg_response_time')}
            </th>
            <th
              class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase tracking-wider cursor-pointer hover:bg-muted"
              onclick={() => handleSort('success_count')}
            >
              성공률{getSortIcon('success_count')}
            </th>
            <th
              class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase tracking-wider cursor-pointer hover:bg-muted"
              onclick={() => handleSort('priority_score')}
            >
              점수{getSortIcon('priority_score')}
            </th>
            <th
              class="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase tracking-wider cursor-pointer hover:bg-muted"
              onclick={() => handleSort('last_checked_at')}
            >
              마지막 검증{getSortIcon('last_checked_at')}
            </th>
            <th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase tracking-wider">
              액션
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border">
          {#each proxies as proxy}
            <tr class="hover:bg-muted">
              <td class="px-4 py-3">
                <a href="/proxy/{proxy.id}" class="text-primary hover:underline font-mono text-sm">
                  {proxy.host}:{proxy.port}
                </a>
                {#if proxy.country}
                  <span class="ml-2 text-xs text-muted-foreground">{proxy.country}</span>
                {/if}
              </td>
              <td class="px-4 py-3 text-center">
                <span class="text-xs uppercase text-muted-foreground">{proxy.protocol}</span>
              </td>
              <td class="px-4 py-3 text-center">
                <span class="px-2 py-0.5 text-xs rounded-full {getStatusBadgeClass(proxy.status)}">
                  {proxy.status}
                </span>
              </td>
              <td class="px-4 py-3 text-right text-sm text-muted-foreground">
                {formatTime(proxy.avg_response_time)}
              </td>
              <td class="px-4 py-3 text-right text-sm text-muted-foreground">
                {formatPercent(proxy.success_rate)}
                <span class="text-xs text-muted-foreground">
                  ({proxy.success_count}/{proxy.total_checks})
                </span>
              </td>
              <td class="px-4 py-3 text-right text-sm font-medium">
                {proxy.priority_score.toFixed(1)}
              </td>
              <td class="px-4 py-3 text-right text-sm text-muted-foreground">
                {formatDate(proxy.last_checked_at)}
              </td>
              <td class="px-4 py-3 text-center">
                <div class="flex items-center justify-center gap-1">
                  <a
                    href="/proxy/{proxy.id}"
                    class="p-1 text-muted-foreground hover:text-primary transition-colors"
                    title="상세 보기"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  </a>
                  {#if proxy.status === 'blacklisted'}
                    <button
                      onclick={() => handleStatusChange(proxy, 'active')}
                      class="p-1 text-muted-foreground hover:text-success transition-colors"
                      title="블랙리스트 해제"
                    >
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                    </button>
                  {:else}
                    <button
                      onclick={() => handleStatusChange(proxy, 'blacklisted')}
                      class="p-1 text-muted-foreground hover:text-error transition-colors"
                      title="블랙리스트 등록"
                    >
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                      </svg>
                    </button>
                  {/if}
                  <button
                    onclick={() => handleDelete(proxy)}
                    class="p-1 text-muted-foreground hover:text-error transition-colors"
                    title="삭제"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          {:else}
            <tr>
              <td colspan="8" class="px-4 py-8 text-center text-muted-foreground">
                프록시 데이터가 없습니다.
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <!-- 페이지네이션 -->
    {#if totalPages > 1}
      <div class="px-4 py-3 border-t border-border flex items-center justify-between">
        <div class="text-sm text-muted-foreground">
          페이지 {page} / {totalPages}
        </div>
        <div class="flex gap-2">
          <button
            onclick={() => handlePageChange(1)}
            disabled={page === 1}
            class="px-3 py-1 text-sm border border-border rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
          >
            처음
          </button>
          <button
            onclick={() => handlePageChange(page - 1)}
            disabled={page === 1}
            class="px-3 py-1 text-sm border border-border rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
          >
            이전
          </button>
          <button
            onclick={() => handlePageChange(page + 1)}
            disabled={page === totalPages}
            class="px-3 py-1 text-sm border border-border rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
          >
            다음
          </button>
          <button
            onclick={() => handlePageChange(totalPages)}
            disabled={page === totalPages}
            class="px-3 py-1 text-sm border border-border rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
          >
            마지막
          </button>
        </div>
      </div>
    {/if}
  </div>
{/if}
