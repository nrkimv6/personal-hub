<script lang="ts">
  import { onMount } from 'svelte';
  import { planRecordsApi, type PlanArchiveExecutionAttempt, type PlanEvent } from '$lib/api/plan-records';

  let events: PlanEvent[] = [];
  let loading = true;
  let error = '';
  let skip = 0;
  const limit = 50;
  let hasMore = false;
  let filterType = '';
  let executionHistory: PlanArchiveExecutionAttempt[] = [];
  let executionHistoryLoading = false;
  let executionHistoryError = '';
  let executionHistoryRecordId = '';
  let executionHistoryLimit = 25;

  // 반복 뱃지용: filename_hash → recurrence_count 맵 (count >= 2인 것만)
  let recurrenceMap = new Map<string, number>();

  const EVENT_TYPES = ['created', 'archived', 'memo_updated', 'path_changed', 'missing'];

  const typeIcon: Record<string, string> = {
    created: '●',
    archived: '●',
    memo_updated: '●',
    path_changed: '●',
    missing: '●',
  };

  const typeLabel: Record<string, string> = {
    created: '생성',
    archived: '아카이브',
    memo_updated: '메모 수정',
    path_changed: '경로 변경',
    missing: '파일 없음',
  };

  // 월별 그룹화
  type MonthGroup = { month: string; events: PlanEvent[]; collapsed: boolean };
  let monthGroups: MonthGroup[] = [];

  function groupByMonth(evts: PlanEvent[]) {
    const map = new Map<string, PlanEvent[]>();
    for (const e of evts) {
      const key = e.created_at.slice(0, 7); // "YYYY-MM"
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(e);
    }
    return [...map.entries()].map(([month, evs]) => ({ month, events: evs, collapsed: false }));
  }

  async function loadEvents(append = false) {
    loading = true;
    error = '';
    try {
      const [data, records] = await Promise.all([
        planRecordsApi.listEvents({
          event_type: filterType || undefined,
          skip: append ? skip : 0,
          limit
        }),
        append ? Promise.resolve(null) : planRecordsApi.listRecords({ skip: 0, limit: 200 })
      ]);
      const allEvents = append ? [...events, ...data] : data;
      events = allEvents;
      skip = append ? skip + data.length : data.length;
      hasMore = data.length === limit;
      monthGroups = groupByMonth(events);

      // 반복 맵 갱신 (초기 로드 시만)
      if (records) {
        const map = new Map<string, number>();
        for (const r of records) {
          if ((r.recurrence_count ?? 1) >= 2) {
            map.set(r.filename_hash, r.recurrence_count);
          }
        }
        recurrenceMap = map;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : '이벤트 로드 실패';
    } finally {
      loading = false;
    }
  }

  async function loadExecutionHistory() {
    executionHistoryLoading = true;
    executionHistoryError = '';
    try {
      const recordId = Number(executionHistoryRecordId);
      const res = await planRecordsApi.getArchiveExecutionHistory({
        record_id: Number.isFinite(recordId) && recordId > 0 ? recordId : undefined,
        limit: Number(executionHistoryLimit) || 25
      });
      executionHistory = res.items ?? [];
    } catch (e) {
      executionHistory = [];
      executionHistoryError = e instanceof Error ? e.message : '실행 이력 로드 실패';
    } finally {
      executionHistoryLoading = false;
    }
  }

  function toggleMonth(group: MonthGroup) {
    group.collapsed = !group.collapsed;
    monthGroups = monthGroups; // trigger reactivity
  }

  function formatTime(iso: string) {
    const d = new Date(iso);
    return d.toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function formatMaybeTime(iso: string | null | undefined) {
    return iso ? formatTime(iso) : '-';
  }

  function getAttemptStatus(attempt: PlanArchiveExecutionAttempt) {
    return attempt.status ?? attempt.state ?? '-';
  }

  function getAttemptTime(attempt: PlanArchiveExecutionAttempt) {
    return attempt.completed_at ?? attempt.started_at ?? attempt.requested_at ?? null;
  }

  function getAttemptProfile(attempt: PlanArchiveExecutionAttempt) {
    const engine = attempt.engine;
    const profile = attempt.profile_name;
    if (engine && profile) return `${engine}/${profile}`;
    if (engine) return engine;
    if (profile) return profile;
    return '-';
  }

  function getExecutionStateClass(state: string | null | undefined) {
    switch (state) {
      case 'queued':
      case 'pending':
        return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-200';
      case 'running':
      case 'processing':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200';
      case 'failed':
        return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200';
      case 'completed':
      case 'success':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200';
      default:
        return 'bg-muted text-muted-foreground';
    }
  }

  onMount(() => {
    loadEvents();
    loadExecutionHistory();
  });
</script>

<div class="flex flex-col h-full">
  <!-- 필터 + 컨트롤 -->
  <div class="flex items-center gap-3 mb-3">
    <h2 class="text-sm font-semibold text-foreground">이벤트 타임라인</h2>
    <select
      class="text-xs bg-background border border-border text-foreground rounded px-2 py-1"
      bind:value={filterType}
      onchange={() => loadEvents()}
    >
      <option value="">전체</option>
      {#each EVENT_TYPES as t}
        <option value={t}>{typeIcon[t]} {typeLabel[t]}</option>
      {/each}
    </select>
    <button
      class="px-3 py-1 text-xs rounded bg-muted hover:bg-secondary text-muted-foreground"
      onclick={() => loadEvents()}
    >새로고침</button>
  </div>

  <div class="mb-4 rounded border border-border bg-background p-3 text-xs">
    <div class="mb-2 flex items-center justify-between gap-2 flex-wrap">
      <h3 class="font-semibold text-foreground">Archive execution history</h3>
      <div class="flex items-center gap-2">
        <input
          class="w-24 rounded border border-border bg-background px-2 py-1"
          placeholder="record id"
          bind:value={executionHistoryRecordId}
        />
        <input
          class="w-20 rounded border border-border bg-background px-2 py-1"
          type="number"
          min="1"
          max="100"
          bind:value={executionHistoryLimit}
        />
        <button
          class="rounded bg-muted px-2 py-1 text-muted-foreground hover:bg-secondary disabled:opacity-50"
          onclick={loadExecutionHistory}
          disabled={executionHistoryLoading}
        >{executionHistoryLoading ? '갱신 중...' : '갱신'}</button>
      </div>
    </div>
    {#if executionHistoryError}
      <p class="text-red-500">{executionHistoryError}</p>
    {:else if executionHistory.length === 0}
      <p class="text-muted-foreground">표시할 실행 이력이 없습니다.</p>
    {:else}
      <div class="overflow-auto">
        <table class="w-full min-w-[720px]">
          <thead>
            <tr class="border-b border-border text-left text-muted-foreground">
              <th class="pb-2 pr-3 font-medium">Attempt</th>
              <th class="pb-2 pr-3 font-medium">Record</th>
              <th class="pb-2 pr-3 font-medium">상태</th>
              <th class="pb-2 pr-3 font-medium">Profile</th>
              <th class="pb-2 pr-3 font-medium">시간</th>
              <th class="pb-2 font-medium">Error</th>
            </tr>
          </thead>
          <tbody>
            {#each executionHistory as attempt, index (attempt.id ?? `${attempt.llm_request_id ?? 'attempt'}-${index}`)}
              <tr class="border-b border-border/60">
                <td class="py-2 pr-3 font-mono">#{attempt.id ?? attempt.llm_request_id ?? '-'}</td>
                <td class="py-2 pr-3 font-mono">{attempt.record_id ?? '-'}</td>
                <td class="py-2 pr-3">
                  <span class="rounded px-2 py-0.5 {getExecutionStateClass(getAttemptStatus(attempt))}">{getAttemptStatus(attempt)}</span>
                </td>
                <td class="py-2 pr-3 font-mono">{getAttemptProfile(attempt)}</td>
                <td class="py-2 pr-3 whitespace-nowrap">{formatMaybeTime(getAttemptTime(attempt))}</td>
                <td class="py-2">
                  {#if attempt.error_message}
                    <span class="inline-block max-w-xs truncate text-red-600 dark:text-red-300" title={attempt.error_message}>{attempt.error_message}</span>
                  {:else}
                    <span class="text-muted-foreground">-</span>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>

  {#if error}
    <p class="text-sm text-red-500 mb-2">{error}</p>
  {/if}

  {#if loading && events.length === 0}
    <p class="text-sm text-muted-foreground">로드 중...</p>
  {:else if monthGroups.length === 0}
    <p class="text-sm text-muted-foreground">이벤트가 없습니다.</p>
  {:else}
    <div class="overflow-auto flex-1 space-y-4">
      {#each monthGroups as group (group.month)}
        <div>
          <button
            class="flex items-center gap-2 text-xs font-semibold text-muted-foreground mb-2 hover:text-foreground"
            onclick={() => toggleMonth(group)}
          >
            <span>{group.collapsed ? '▶' : '▼'}</span>
            <span>{group.month}</span>
            <span class="text-muted-foreground/50">({group.events.length}건)</span>
          </button>

          {#if !group.collapsed}
            <div class="space-y-1 ml-4 border-l border-border pl-4">
              {#each group.events as event (event.id)}
                <div class="flex items-start gap-3 text-xs">
                  <span class="mt-0.5">{typeIcon[event.event_type] ?? '·'}</span>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                      <span class="text-foreground font-medium">{typeLabel[event.event_type] ?? event.event_type}</span>
                      <span class="text-muted-foreground">{formatTime(event.created_at)}</span>
                      {#if event.event_type === 'archived' && event.detail?.filename_hash && recurrenceMap.has(String(event.detail.filename_hash))}
                        <span class="text-xs bg-red-100 text-red-600 rounded px-1">
                          {recurrenceMap.get(String(event.detail.filename_hash))}번째 반복
                        </span>
                      {/if}
                    </div>
                    {#if event.detail}
                      <p class="text-muted-foreground font-mono truncate mt-0.5" title={JSON.stringify(event.detail)}>
                        {#if event.detail.file_path}
                          {String(event.detail.file_path).split(/[\\/]/).pop()}
                        {:else if event.detail.to}
                          {String(event.detail.to).split(/[\\/]/).pop()}
                        {:else if event.detail.preview}
                          {String(event.detail.preview).slice(0, 60)}
                        {:else}
                          {JSON.stringify(event.detail).slice(0, 60)}
                        {/if}
                      </p>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/each}

      {#if hasMore}
        <button
          class="px-4 py-2 text-xs rounded bg-muted hover:bg-secondary text-muted-foreground mx-auto block"
          disabled={loading}
          onclick={() => loadEvents(true)}
        >
          {loading ? '로드 중...' : '더 보기 (50건)'}
        </button>
      {/if}
    </div>
  {/if}
</div>
