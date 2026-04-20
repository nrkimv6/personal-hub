<script lang="ts">
  import type { ExpoCollectionStatusResponse } from '$lib/types';

  interface Props {
    status: ExpoCollectionStatusResponse | null;
    loading?: boolean;
    error?: string | null;
    draftCount?: number;
    exportPending?: boolean;
    onExport?: (() => Promise<void> | void) | undefined;
  }

  let {
    status,
    loading = false,
    error = null,
    draftCount = 0,
    exportPending = false,
    onExport,
  }: Props = $props();

  function formatDateTime(value: string | null | undefined) {
    if (!value) {
      return '기록 없음';
    }
    return new Date(value).toLocaleString('ko-KR');
  }

  function matchLabel(kind: string) {
    if (kind === 'event') return 'event 연결';
    if (kind === 'popup') return 'popup 연결';
    if (kind === 'analysis_pending') return '분석 대기';
    return '매칭 대기';
  }
</script>

<section class="rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm">
  <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
    <div>
      <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Collection</p>
      <h3 class="mt-2 text-xl font-semibold text-slate-900">수집 현황과 export 흐름</h3>
      <p class="mt-2 text-sm leading-6 text-slate-600">
        collect 이력 요약과 recent source preview를 보고, local draft를 export로 넘깁니다.
      </p>
    </div>

    <div class="flex flex-wrap gap-2">
      <button
        type="button"
        class="rounded-full bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        disabled={exportPending || draftCount === 0}
        onclick={() => onExport?.()}
      >
        {exportPending ? 'Export 중...' : `Export JSON${draftCount > 0 ? ` (${draftCount})` : ''}`}
      </button>
      {#if status?.published_status.admin_url}
        <a
          href={status.published_status.admin_url}
          target="_blank"
          rel="noreferrer"
          class="inline-flex rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-900 hover:text-slate-900"
        >
          admin-tools 열기
        </a>
      {/if}
    </div>
  </div>

  {#if loading && !status}
    <p class="mt-4 text-sm text-slate-500">collection 상태를 불러오는 중입니다.</p>
  {:else if error && !status}
    <p class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>
  {:else if status}
    <div class="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <article class="rounded-2xl bg-slate-50 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Recent Complete</p>
        <p class="mt-2 text-2xl font-semibold text-slate-900">{status.recent_completed_requests}</p>
        <p class="mt-1 text-sm text-slate-500">last 24h</p>
      </article>
      <article class="rounded-2xl bg-slate-50 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Pending</p>
        <p class="mt-2 text-2xl font-semibold text-slate-900">{status.pending_request_count}</p>
        <p class="mt-1 text-sm text-slate-500">crawl queue</p>
      </article>
      <article class="rounded-2xl bg-slate-50 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Failed</p>
        <p class="mt-2 text-2xl font-semibold text-slate-900">{status.failed_request_count}</p>
        <p class="mt-1 text-sm text-slate-500">last 24h</p>
      </article>
      <article class="rounded-2xl bg-slate-50 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Matching Pending</p>
        <p class="mt-2 text-2xl font-semibold text-slate-900">{status.matching_pending_count}</p>
        <p class="mt-1 text-sm text-slate-500">manual review</p>
      </article>
    </div>

    <div class="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div class="rounded-2xl border border-slate-200 px-4 py-4">
        <div class="flex items-center justify-between gap-3">
          <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Recent Sources</p>
          <span class="text-sm text-slate-500">last collected {formatDateTime(status.last_collected_at)}</span>
        </div>

        {#if status.recent_sources.length === 0}
          <p class="mt-4 text-sm text-slate-500">최근 source가 없습니다.</p>
        {:else}
          <ul class="mt-4 space-y-2">
            {#each status.recent_sources as source}
              <li class="rounded-2xl bg-slate-50 px-4 py-3 text-sm">
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <p class="truncate font-semibold text-slate-900">{source.title}</p>
                    <p class="mt-1 truncate text-slate-500">{source.url}</p>
                  </div>
                  <span class="rounded-full bg-white px-2 py-1 text-xs font-semibold text-slate-600">
                    {matchLabel(source.match_status)}
                  </span>
                </div>
                <p class="mt-2 text-xs text-slate-500">
                  {source.url_type} · {formatDateTime(source.collected_at)}
                </p>
              </li>
            {/each}
          </ul>
        {/if}
      </div>

      <div class="rounded-2xl border border-slate-200 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Export Sync</p>
        <p class="mt-2 text-sm font-semibold text-slate-900">
          최근 export: {formatDateTime(status.last_exported_at)}
        </p>
        <p class="mt-2 text-sm text-slate-600">
          publish 상태: {status.published_status.status}
        </p>
        <p class="mt-1 text-sm text-slate-600">
          worker: {status.worker.status} / {status.worker.current_state ?? 'idle'}
        </p>
        {#if draftCount === 0}
          <p class="mt-4 text-sm text-slate-500">
            현재 브라우저 local draft가 없어 export 버튼이 비활성화되어 있습니다.
          </p>
        {/if}
      </div>
    </div>
  {/if}
</section>
