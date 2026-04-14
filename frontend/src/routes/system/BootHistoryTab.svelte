<script lang="ts">
  import { onMount } from 'svelte';
  import { bootHistoryApi, type BootHistoryItem } from '$lib/api';

  let loading = true;
  let refreshing = false;
  let error: string | null = null;
  let systemBootAt: string | null = null;
  let items: BootHistoryItem[] = [];

  const dateTimeFormatter = new Intl.DateTimeFormat('ko-KR', {
    dateStyle: 'medium',
    timeStyle: 'medium'
  });

  async function loadBootHistory(initial = false) {
    if (initial) {
      loading = true;
    } else {
      refreshing = true;
    }

    try {
      const response = await bootHistoryApi.list(100);
      systemBootAt = response.system_boot_at;
      items = response.items;
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : '부팅 이력 로드 실패';
    } finally {
      loading = false;
      refreshing = false;
    }
  }

  onMount(() => {
    void loadBootHistory(true);
  });

  $: runningCount = items.filter((item) => item.current).length;
  $: attentionCount = items.filter((item) => item.needs_attention).length;
  $: restartedCount = items.filter((item) => item.restarted).length;

  function formatDateTime(value: string | null) {
    if (!value) return '—';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return dateTimeFormatter.format(parsed);
  }

  function formatDuration(seconds: number | null) {
    if (seconds === null || seconds === undefined) return '—';
    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    const parts: string[] = [];
    if (hours > 0) parts.push(`${hours}시간`);
    if (minutes > 0 || hours > 0) parts.push(`${minutes}분`);
    parts.push(`${secs}초`);
    return parts.join(' ');
  }

  function statusLabel(status: BootHistoryItem['status']) {
    if (status === 'running') return '실행 중';
    if (status === 'restarted') return '재시작됨';
    if (status === 'stopped') return '중지됨';
    return status;
  }

  function causeLabel(cause: string | null) {
    const labels: Record<string, string> = {
      normal_shutdown: '정상 종료',
      signal: '시그널 종료',
      python_exception: '파이썬 예외',
      external_kill: '강제 종료',
      system_reboot: '시스템 재부팅 추정',
      unknown: '원인 불명',
      crash_loop: '크래시 루프'
    };

    if (!cause) return '—';
    return labels[cause] ?? cause;
  }

  function statusClass(status: BootHistoryItem['status']) {
    if (status === 'running') return 'bg-emerald-100 text-emerald-700';
    if (status === 'restarted') return 'bg-blue-100 text-blue-700';
    return 'bg-amber-100 text-amber-700';
  }

  function causeClass(cause: string | null, inferredEnd: boolean) {
    if (!cause) return 'bg-secondary text-secondary-foreground';
    if (cause === 'system_reboot' || inferredEnd) return 'bg-violet-100 text-violet-700';
    if (cause === 'normal_shutdown') return 'bg-emerald-100 text-emerald-700';
    return 'bg-amber-100 text-amber-700';
  }
</script>

<div class="space-y-6">
  <div class="card space-y-4">
    <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div>
        <h3 class="text-lg font-semibold text-foreground">부팅 이력</h3>
        <p class="text-sm text-muted-foreground">
          death log를 세션 단위로 묶어 현재 실행 중인 세션과 미재기동 세션을 보여줍니다.
        </p>
      </div>
      <button
        type="button"
        class="inline-flex items-center justify-center rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-60"
        on:click={() => loadBootHistory(false)}
        disabled={loading || refreshing}
      >
        {refreshing ? '갱신 중...' : '새로고침'}
      </button>
    </div>

    {#if error}
      <div class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        {error}
      </div>
    {/if}

    <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
      <div class="rounded-lg border border-border bg-background p-4">
        <div class="text-sm text-muted-foreground">현재 실행 중</div>
        <div class="mt-2 text-3xl font-semibold text-foreground">{runningCount}</div>
      </div>
      <div class="rounded-lg border border-border bg-background p-4">
        <div class="text-sm text-muted-foreground">주의 필요</div>
        <div class="mt-2 text-3xl font-semibold text-foreground">{attentionCount}</div>
      </div>
      <div class="rounded-lg border border-border bg-background p-4">
        <div class="text-sm text-muted-foreground">시스템 부팅 시각</div>
        <div class="mt-2 text-sm font-medium text-foreground">{formatDateTime(systemBootAt)}</div>
        <div class="mt-1 text-xs text-muted-foreground">재시작된 세션 {restartedCount}</div>
      </div>
    </div>

    {#if loading}
      <div class="flex h-48 items-center justify-center text-sm text-muted-foreground">
        부팅 이력을 불러오는 중...
      </div>
    {:else if items.length === 0}
      <div class="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
        아직 기록된 부팅 이력이 없습니다.
      </div>
    {:else}
      <div class="overflow-hidden rounded-lg border border-border">
        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-border text-sm">
            <thead class="bg-secondary/40">
              <tr class="text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <th class="px-4 py-3">시작</th>
                <th class="px-4 py-3">종료</th>
                <th class="px-4 py-3">상태</th>
                <th class="px-4 py-3">종료 원인</th>
                <th class="px-4 py-3">업타임</th>
                <th class="px-4 py-3">재기동 간격</th>
                <th class="px-4 py-3">최근 요청</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border bg-background">
              {#each items as item}
                <tr class={item.needs_attention ? 'bg-amber-50/60' : item.current ? 'bg-emerald-50/40' : ''}>
                  <td class="px-4 py-3 align-top">
                    <div class="font-medium text-foreground">{formatDateTime(item.started_at)}</div>
                    <div class="mt-1 text-xs text-muted-foreground">PID {item.pid}</div>
                  </td>
                  <td class="px-4 py-3 align-top text-muted-foreground">
                    {formatDateTime(item.ended_at)}
                  </td>
                  <td class="px-4 py-3 align-top">
                    <div class="flex flex-wrap items-center gap-2">
                      <span class={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusClass(item.status)}`}>
                        {statusLabel(item.status)}
                      </span>
                      {#if item.current}
                        <span class="inline-flex rounded-full bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white">
                          현재
                        </span>
                      {/if}
                      {#if item.needs_attention}
                        <span class="inline-flex rounded-full bg-red-600 px-2.5 py-1 text-xs font-medium text-white">
                          주의
                        </span>
                      {/if}
                    </div>
                  </td>
                  <td class="px-4 py-3 align-top">
                    <div class="flex flex-wrap items-center gap-2">
                      <span class={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${causeClass(item.end_cause, item.inferred_end)}`}>
                        {causeLabel(item.end_cause)}
                      </span>
                      {#if item.inferred_end}
                        <span class="inline-flex rounded-full bg-violet-600 px-2.5 py-1 text-xs font-medium text-white">
                          추정
                        </span>
                      {/if}
                    </div>
                    {#if item.end_details}
                      <div class="mt-2 text-xs text-muted-foreground">{item.end_details}</div>
                    {/if}
                  </td>
                  <td class="px-4 py-3 align-top text-muted-foreground">
                    {formatDuration(item.uptime_seconds)}
                  </td>
                  <td class="px-4 py-3 align-top text-muted-foreground">
                    {formatDuration(item.restart_gap_seconds)}
                  </td>
                  <td class="px-4 py-3 align-top text-muted-foreground">
                    <div class="max-w-[240px] truncate">{item.last_request ?? '—'}</div>
                    {#if item.restarted}
                      <div class="mt-1 text-xs text-blue-700">다음 세션이 시작됨</div>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {/if}
  </div>
</div>
