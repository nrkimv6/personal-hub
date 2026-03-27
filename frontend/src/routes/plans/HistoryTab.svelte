<script lang="ts">
  import { onMount } from 'svelte';
  import { planRecordsApi, type PlanEvent } from '$lib/api/plan-records';

  let events: PlanEvent[] = [];
  let loading = true;
  let error = '';
  let skip = 0;
  const limit = 50;
  let hasMore = false;
  let filterType = '';

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

  function toggleMonth(group: MonthGroup) {
    group.collapsed = !group.collapsed;
    monthGroups = monthGroups; // trigger reactivity
  }

  function formatTime(iso: string) {
    const d = new Date(iso);
    return d.toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  onMount(() => loadEvents());
</script>

<div class="flex flex-col h-full">
  <!-- 필터 + 컨트롤 -->
  <div class="flex items-center gap-3 mb-3">
    <h2 class="text-sm font-semibold text-foreground">이벤트 타임라인</h2>
    <select
      class="text-xs bg-background border border-border text-foreground rounded px-2 py-1"
      bind:value={filterType}
      on:change={() => loadEvents()}
    >
      <option value="">전체</option>
      {#each EVENT_TYPES as t}
        <option value={t}>{typeIcon[t]} {typeLabel[t]}</option>
      {/each}
    </select>
    <button
      class="px-3 py-1 text-xs rounded bg-muted hover:bg-secondary text-muted-foreground"
      on:click={() => loadEvents()}
    >새로고침</button>
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
            on:click={() => toggleMonth(group)}
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
          on:click={() => loadEvents(true)}
        >
          {loading ? '로드 중...' : '더 보기 (50건)'}
        </button>
      {/if}
    </div>
  {/if}
</div>
