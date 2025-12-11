<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { proxyApi } from '$lib/api';
  import type { ProxyDetail, ProxyCheckHistory } from '$lib/types';

  let proxy: ProxyDetail | null = null;
  let loading = true;
  let error: string | null = null;

  $: proxyId = parseInt($page.params.id || '0');

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    error = null;
    try {
      proxy = await proxyApi.get(proxyId);
    } catch (e) {
      error = e instanceof Error ? e.message : '데이터를 불러오는데 실패했습니다.';
    } finally {
      loading = false;
    }
  }

  async function handleStatusChange(newStatus: string) {
    if (!proxy) return;
    try {
      await proxyApi.updateStatus(proxy.id, newStatus);
      await loadData();
    } catch (e) {
      alert(e instanceof Error ? e.message : '상태 변경에 실패했습니다.');
    }
  }

  async function handleDelete() {
    if (!proxy) return;
    if (!confirm(`정말 ${proxy.host}:${proxy.port} 프록시를 삭제하시겠습니까?`)) return;
    try {
      await proxyApi.delete(proxy.id);
      goto('/proxy/list');
    } catch (e) {
      alert(e instanceof Error ? e.message : '삭제에 실패했습니다.');
    }
  }

  function formatTime(seconds: number | null): string {
    if (seconds === null) return '-';
    return `${seconds.toFixed(3)}s`;
  }

  function formatPercent(value: number | null): string {
    if (value === null) return '-';
    return `${value.toFixed(1)}%`;
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('ko-KR');
  }

  function formatDateShort(dateStr: string | null): string {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('ko-KR', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  }

  function getStatusBadgeClass(status: string): string {
    const classes: Record<string, string> = {
      active: 'bg-green-100 text-green-800',
      pending: 'bg-yellow-100 text-yellow-800',
      inactive: 'bg-gray-100 text-gray-800',
      blacklisted: 'bg-red-100 text-red-800'
    };
    return classes[status] || 'bg-gray-100 text-gray-800';
  }

  function getCheckResultClass(isValid: boolean): string {
    return isValid
      ? 'bg-green-100 text-green-800'
      : 'bg-red-100 text-red-800';
  }
</script>

<div class="mb-4">
  <a href="/proxy/list" class="text-blue-600 hover:underline text-sm">&larr; 목록으로</a>
</div>

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
{:else if proxy}
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <!-- 기본 정보 -->
    <div class="lg:col-span-2 space-y-6">
      <div class="bg-white rounded-lg shadow p-6">
        <div class="flex items-start justify-between mb-4">
          <div>
            <h2 class="text-xl font-bold text-gray-900 font-mono">
              {proxy.host}:{proxy.port}
            </h2>
            <p class="text-gray-500 text-sm mt-1">ID: {proxy.id}</p>
          </div>
          <span class="px-3 py-1 text-sm rounded-full {getStatusBadgeClass(proxy.status)}">
            {proxy.status}
          </span>
        </div>

        <div class="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span class="text-gray-500">URL</span>
            <p class="font-mono text-gray-900 break-all">{proxy.url}</p>
          </div>
          <div>
            <span class="text-gray-500">프로토콜</span>
            <p class="uppercase text-gray-900">{proxy.protocol}</p>
          </div>
          <div>
            <span class="text-gray-500">소스</span>
            <p class="text-gray-900">{proxy.source || '-'}</p>
          </div>
          <div>
            <span class="text-gray-500">국가</span>
            <p class="text-gray-900">{proxy.country || '-'}</p>
          </div>
          <div>
            <span class="text-gray-500">최초 등록</span>
            <p class="text-gray-900">{formatDate(proxy.first_seen_at)}</p>
          </div>
          <div>
            <span class="text-gray-500">마지막 검증</span>
            <p class="text-gray-900">{formatDate(proxy.last_checked_at)}</p>
          </div>
        </div>
      </div>

      <!-- 성능 통계 -->
      <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold text-gray-900 mb-4">성능 통계</h3>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="bg-gray-50 rounded-lg p-4">
            <div class="text-sm text-gray-500">총 검증</div>
            <div class="text-2xl font-bold text-gray-900">{proxy.total_checks}</div>
          </div>
          <div class="bg-gray-50 rounded-lg p-4">
            <div class="text-sm text-gray-500">성공 횟수</div>
            <div class="text-2xl font-bold text-green-600">{proxy.success_count}</div>
          </div>
          <div class="bg-gray-50 rounded-lg p-4">
            <div class="text-sm text-gray-500">성공률</div>
            <div class="text-2xl font-bold text-blue-600">{formatPercent(proxy.success_rate)}</div>
          </div>
          <div class="bg-gray-50 rounded-lg p-4">
            <div class="text-sm text-gray-500">연속 실패</div>
            <div class="text-2xl font-bold text-red-600">{proxy.fail_count}</div>
          </div>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
          <div class="bg-gray-50 rounded-lg p-4">
            <div class="text-sm text-gray-500">평균 응답시간</div>
            <div class="text-xl font-bold text-gray-900">{formatTime(proxy.avg_response_time)}</div>
          </div>
          <div class="bg-gray-50 rounded-lg p-4">
            <div class="text-sm text-gray-500">최소 응답시간</div>
            <div class="text-xl font-bold text-green-600">{formatTime(proxy.min_response_time)}</div>
          </div>
          <div class="bg-gray-50 rounded-lg p-4">
            <div class="text-sm text-gray-500">최대 응답시간</div>
            <div class="text-xl font-bold text-orange-600">{formatTime(proxy.max_response_time)}</div>
          </div>
          <div class="bg-gray-50 rounded-lg p-4">
            <div class="text-sm text-gray-500">우선순위 점수</div>
            <div class="text-xl font-bold text-purple-600">{proxy.priority_score.toFixed(1)}</div>
          </div>
        </div>
      </div>

      <!-- 검증 이력 -->
      <div class="bg-white rounded-lg shadow">
        <div class="p-4 border-b border-gray-200">
          <h3 class="text-lg font-semibold text-gray-900">검증 이력</h3>
          <p class="text-sm text-gray-500">최근 50건</p>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">시간</th>
                <th class="px-4 py-2 text-center text-xs font-medium text-gray-500 uppercase">결과</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">응답시간</th>
                <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">상태코드</th>
                <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">에러</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-200">
              {#each proxy.check_history as check}
                <tr class="hover:bg-gray-50">
                  <td class="px-4 py-2 text-sm text-gray-600">
                    {formatDateShort(check.checked_at)}
                  </td>
                  <td class="px-4 py-2 text-center">
                    <span class="px-2 py-0.5 text-xs rounded-full {getCheckResultClass(check.is_valid)}">
                      {check.is_valid ? 'OK' : 'FAIL'}
                    </span>
                  </td>
                  <td class="px-4 py-2 text-right text-sm text-gray-600">
                    {formatTime(check.response_time)}
                  </td>
                  <td class="px-4 py-2 text-sm text-gray-600">
                    {check.http_status || '-'}
                  </td>
                  <td class="px-4 py-2 text-sm text-gray-500 truncate max-w-[200px]" title={check.error_message || ''}>
                    {check.error_type || '-'}
                    {#if check.error_message}
                      <span class="text-gray-400">: {check.error_message}</span>
                    {/if}
                  </td>
                </tr>
              {:else}
                <tr>
                  <td colspan="5" class="px-4 py-8 text-center text-gray-500">
                    검증 이력이 없습니다.
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 사이드바 - 액션 -->
    <div class="space-y-6">
      <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold text-gray-900 mb-4">액션</h3>
        <div class="space-y-3">
          {#if proxy.status === 'blacklisted'}
            <button
              on:click={() => handleStatusChange('active')}
              class="w-full px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
            >
              블랙리스트 해제
            </button>
          {:else}
            <button
              on:click={() => handleStatusChange('blacklisted')}
              class="w-full px-4 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700 transition-colors"
            >
              블랙리스트 등록
            </button>
          {/if}

          {#if proxy.status === 'inactive'}
            <button
              on:click={() => handleStatusChange('pending')}
              class="w-full px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
            >
              재검증 대기열 추가
            </button>
          {/if}

          <button
            on:click={handleDelete}
            class="w-full px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors"
          >
            프록시 삭제
          </button>
        </div>
      </div>

      <!-- 태그 -->
      {#if proxy.tags}
        <div class="bg-white rounded-lg shadow p-6">
          <h3 class="text-lg font-semibold text-gray-900 mb-4">태그</h3>
          <div class="flex flex-wrap gap-2">
            {#each proxy.tags.split(',') as tag}
              <span class="px-2 py-1 bg-gray-100 text-gray-700 rounded text-sm">
                {tag.trim()}
              </span>
            {/each}
          </div>
        </div>
      {/if}

      <!-- 추가 정보 -->
      <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold text-gray-900 mb-4">추가 정보</h3>
        <dl class="space-y-2 text-sm">
          <div class="flex justify-between">
            <dt class="text-gray-500">마지막 성공</dt>
            <dd class="text-gray-900">{formatDate(proxy.last_success_at)}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-gray-500">마지막 확인</dt>
            <dd class="text-gray-900">{formatDate(proxy.last_seen_at)}</dd>
          </div>
          {#if proxy.username}
            <div class="flex justify-between">
              <dt class="text-gray-500">인증</dt>
              <dd class="text-gray-900">필요</dd>
            </div>
          {/if}
        </dl>
      </div>
    </div>
  </div>
{/if}
