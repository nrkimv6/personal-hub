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

  const EVENT_TYPES = ['created', 'archived', 'memo_updated', 'path_changed', 'missing'];

  const typeIcon: Record<string, string> = {
    created: '🟢',
    archived: '🔵',
    memo_updated: '🟡',
    path_changed: '🟠',
    missing: '🔴',
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
      const data = await planRecordsApi.listEvents({
        event_type: filterType || undefined,
        skip: append ? skip : 0,
        limit
      });
      const allEvents = append ? [...events, ...data] : data;
      events = allEvents;
      skip = append ? skip + data.length : data.length;
      hasMore = data.length === limit;
      monthGroups = groupByMonth(events);
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
    <h2 class="text-sm font-semibold text-gray-300">이벤트 타임라인</h2>
    <select
      class="text-xs bg-gray-800 border border-gray-700 text-gray-300 rounded px-2 py-1"
      bind:value={filterType}
      on:change={() => loadEvents()}
    >
      <option value="">전체</option>
      {#each EVENT_TYPES as t}
        <option value={t}>{typeIcon[t]} {typeLabel[t]}</option>
      {/each}
    </select>
    <button
      class="px-3 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
      on:click={() => loadEvents()}
    >새로고침</button>
  </div>

  {#if error}
    <p class="text-sm text-red-400 mb-2">{error}</p>
  {/if}

  {#if loading && events.length === 0}
    <p class="text-sm text-gray-400">로드 중...</p>
  {:else if monthGroups.length === 0}
    <p class="text-sm text-gray-500">이벤트가 없습니다.</p>
  {:else}
    <div class="overflow-auto flex-1 space-y-4">
      {#each monthGroups as group (group.month)}
        <div>
          <button
            class="flex items-center gap-2 text-xs font-semibold text-gray-400 mb-2 hover:text-gray-200"
            on:click={() => toggleMonth(group)}
          >
            <span>{group.collapsed ? '▶' : '▼'}</span>
            <span>{group.month}</span>
            <span class="text-gray-600">({group.events.length}건)</span>
          </button>

          {#if !group.collapsed}
            <div class="space-y-1 ml-4 border-l border-gray-700 pl-4">
              {#each group.events as event (event.id)}
                <div class="flex items-start gap-3 text-xs">
                  <span class="mt-0.5">{typeIcon[event.event_type] ?? '⚪'}</span>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="text-gray-300 font-medium">{typeLabel[event.event_type] ?? event.event_type}</span>
                      <span class="text-gray-500">{formatTime(event.created_at)}</span>
                    </div>
                    {#if event.detail}
                      <p class="text-gray-500 font-mono truncate mt-0.5" title={JSON.stringify(event.detail)}>
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
          class="px-4 py-2 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300 mx-auto block"
          disabled={loading}
          on:click={() => loadEvents(true)}
        >
          {loading ? '로드 중...' : '더 보기 (50건)'}
        </button>
      {/if}
    </div>
  {/if}
</div>
