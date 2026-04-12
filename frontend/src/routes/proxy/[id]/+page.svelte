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
    // 서버에서 UTC로 저장된 시간을 KST로 변환
    const utcDate = dateStr.endsWith('Z') ? dateStr : dateStr + 'Z';
    return new Date(utcDate).toLocaleString('ko-KR');
  }

  function formatDateShort(dateStr: string | null): string {
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

  function getStatusBadgeClass(status: string): string {
    const classes: Record<string, string> = {
      active: 'bg-success-light text-success',
      pending: 'bg-warning-light text-warning-foreground',
      inactive: 'bg-muted text-foreground',
      blacklisted: 'bg-error-light text-error'
    };
    return classes[status] || 'bg-muted text-foreground';
  }

  function getCheckResultClass(isValid: boolean): string {
    return isValid
      ? 'bg-success-light text-success'
      : 'bg-error-light text-error';
  }
</script>

<div class="mb-4">
  <a href="/proxy/list" class="text-primary hover:underline text-sm">&larr; 목록으로</a>
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
{:else if proxy}
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <!-- 기본 정보 -->
    <div class="lg:col-span-2 space-y-6">
      <div class="bg-white rounded-lg shadow p-6">
        <div class="flex items-start justify-between mb-4">
          <div>
            <h2 class="text-xl font-bold text-foreground font-mono">
              {proxy.host}:{proxy.port}
            </h2>
            <p class="text-muted-foreground text-sm mt-1">ID: {proxy.id}</p>
          </div>
          <span class="px-3 py-1 text-sm rounded-full {getStatusBadgeClass(proxy.status)}">
            {proxy.status}
          </span>
        </div>

        <div class="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span class="text-muted-foreground">URL</span>
            <p class="font-mono text-foreground break-all">{proxy.url}</p>
          </div>
          <div>
            <span class="text-muted-foreground">프로토콜</span>
            <p class="uppercase text-foreground">{proxy.protocol}</p>
          </div>
          <div>
            <span class="text-muted-foreground">소스</span>
            <p class="text-foreground">{proxy.source || '-'}</p>
          </div>
          <div>
            <span class="text-muted-foreground">국가</span>
            <p class="text-foreground">{proxy.country || '-'}</p>
          </div>
          <div>
            <span class="text-muted-foreground">최초 등록</span>
            <p class="text-foreground">{formatDate(proxy.first_seen_at)}</p>
          </div>
          <div>
            <span class="text-muted-foreground">마지막 검증</span>
            <p class="text-foreground">{formatDate(proxy.last_checked_at)}</p>
          </div>
        </div>
      </div>

      <!-- 성능 통계 -->
      <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold text-foreground mb-4">성능 통계</h3>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="bg-background rounded-lg p-4">
            <div class="text-sm text-muted-foreground">총 검증</div>
            <div class="text-2xl font-bold text-foreground">{proxy.total_checks}</div>
          </div>
          <div class="bg-background rounded-lg p-4">
            <div class="text-sm text-muted-foreground">성공 횟수</div>
            <div class="text-2xl font-bold text-success">{proxy.success_count}</div>
          </div>
          <div class="bg-background rounded-lg p-4">
            <div class="text-sm text-muted-foreground">성공률</div>
            <div class="text-2xl font-bold text-primary">{formatPercent(proxy.success_rate)}</div>
          </div>
          <div class="bg-background rounded-lg p-4">
            <div class="text-sm text-muted-foreground">연속 실패</div>
            <div class="text-2xl font-bold text-error">{proxy.fail_count}</div>
          </div>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
          <div class="bg-background rounded-lg p-4">
            <div class="text-sm text-muted-foreground">평균 응답시간</div>
            <div class="text-xl font-bold text-foreground">{formatTime(proxy.avg_response_time)}</div>
          </div>
          <div class="bg-background rounded-lg p-4">
            <div class="text-sm text-muted-foreground">최소 응답시간</div>
            <div class="text-xl font-bold text-success">{formatTime(proxy.min_response_time)}</div>
          </div>
          <div class="bg-background rounded-lg p-4">
            <div class="text-sm text-muted-foreground">최대 응답시간</div>
            <div class="text-xl font-bold text-warning">{formatTime(proxy.max_response_time)}</div>
          </div>
          <div class="bg-background rounded-lg p-4">
            <div class="text-sm text-muted-foreground">우선순위 점수</div>
            <div class="text-xl font-bold text-purple">{proxy.priority_score.toFixed(1)}</div>
          </div>
        </div>
      </div>

      <!-- 검증 이력 -->
      <div class="bg-white rounded-lg shadow">
        <div class="p-4 border-b border-border">
          <h3 class="text-lg font-semibold text-foreground">검증 이력</h3>
          <p class="text-sm text-muted-foreground">최근 50건</p>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead class="bg-background">
              <tr>
                <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">시간</th>
                <th class="px-4 py-2 text-center text-xs font-medium text-muted-foreground uppercase">결과</th>
                <th class="px-4 py-2 text-right text-xs font-medium text-muted-foreground uppercase">응답시간</th>
                <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">상태코드</th>
                <th class="px-4 py-2 text-left text-xs font-medium text-muted-foreground uppercase">에러</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              {#each proxy.check_history as check}
                <tr class="hover:bg-muted">
                  <td class="px-4 py-2 text-sm text-muted-foreground">
                    {formatDateShort(check.checked_at)}
                  </td>
                  <td class="px-4 py-2 text-center">
                    <span class="px-2 py-0.5 text-xs rounded-full {getCheckResultClass(check.is_valid)}">
                      {check.is_valid ? 'OK' : 'FAIL'}
                    </span>
                  </td>
                  <td class="px-4 py-2 text-right text-sm text-muted-foreground">
                    {formatTime(check.response_time)}
                  </td>
                  <td class="px-4 py-2 text-sm text-muted-foreground">
                    {check.http_status || '-'}
                  </td>
                  <td class="px-4 py-2 text-sm text-muted-foreground truncate max-w-[200px]" title={check.error_message || ''}>
                    {check.error_type || '-'}
                    {#if check.error_message}
                      <span class="text-muted-foreground">: {check.error_message}</span>
                    {/if}
                  </td>
                </tr>
              {:else}
                <tr>
                  <td colspan="5" class="px-4 py-8 text-center text-muted-foreground">
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
        <h3 class="text-lg font-semibold text-foreground mb-4">액션</h3>
        <div class="space-y-3">
          {#if proxy.status === 'blacklisted'}
            <button
              onclick={() => handleStatusChange('active')}
              class="w-full px-4 py-2 bg-success text-white rounded-md hover:bg-success/90 transition-colors"
            >
              블랙리스트 해제
            </button>
          {:else}
            <button
              onclick={() => handleStatusChange('blacklisted')}
              class="w-full px-4 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700 transition-colors"
            >
              블랙리스트 등록
            </button>
          {/if}

          {#if proxy.status === 'inactive'}
            <button
              onclick={() => handleStatusChange('pending')}
              class="w-full px-4 py-2 bg-primary text-white rounded-md hover:bg-primary-hover transition-colors"
            >
              재검증 대기열 추가
            </button>
          {/if}

          <button
            onclick={handleDelete}
            class="w-full px-4 py-2 bg-error text-white rounded-md hover:bg-error/90 transition-colors"
          >
            프록시 삭제
          </button>
        </div>
      </div>

      <!-- 태그 -->
      {#if proxy.tags}
        <div class="bg-white rounded-lg shadow p-6">
          <h3 class="text-lg font-semibold text-foreground mb-4">태그</h3>
          <div class="flex flex-wrap gap-2">
            {#each proxy.tags.split(',') as tag}
              <span class="px-2 py-1 bg-muted text-foreground rounded text-sm">
                {tag.trim()}
              </span>
            {/each}
          </div>
        </div>
      {/if}

      <!-- 추가 정보 -->
      <div class="bg-white rounded-lg shadow p-6">
        <h3 class="text-lg font-semibold text-foreground mb-4">추가 정보</h3>
        <dl class="space-y-2 text-sm">
          <div class="flex justify-between">
            <dt class="text-muted-foreground">마지막 성공</dt>
            <dd class="text-foreground">{formatDate(proxy.last_success_at)}</dd>
          </div>
          <div class="flex justify-between">
            <dt class="text-muted-foreground">마지막 확인</dt>
            <dd class="text-foreground">{formatDate(proxy.last_seen_at)}</dd>
          </div>
          {#if proxy.username}
            <div class="flex justify-between">
              <dt class="text-muted-foreground">인증</dt>
              <dd class="text-foreground">필요</dd>
            </div>
          {/if}
        </dl>
      </div>
    </div>
  </div>
{/if}
