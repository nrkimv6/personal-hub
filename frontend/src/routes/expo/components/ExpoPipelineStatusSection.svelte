<script lang="ts">
  import type { ExpoPipelineStatusResponse } from '$lib/types';

  interface Props {
    status: ExpoPipelineStatusResponse | null;
    loading?: boolean;
    error?: string | null;
  }

  let { status, loading = false, error = null }: Props = $props();

  function formatDateTime(value: string | null | undefined) {
    if (!value) {
      return '기록 없음';
    }
    return new Date(value).toLocaleString('ko-KR');
  }

  function statusTone(kind: string) {
    if (kind === 'healthy' || kind === 'published') return 'bg-emerald-100 text-emerald-700';
    if (kind === 'warning' || kind === 'draft') return 'bg-amber-100 text-amber-700';
    return 'bg-slate-100 text-slate-600';
  }
</script>

<section class="rounded-[28px] border border-slate-200 bg-white/96 p-5 shadow-sm">
  <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
    <div>
      <p class="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Pipeline</p>
      <h3 class="mt-2 text-xl font-semibold text-slate-900">소스 파이프라인 상태</h3>
      <p class="mt-2 text-sm leading-6 text-slate-600">
        booth seed, 이벤트/팝업 집계, 최근 export, worker heartbeat를 한 표면에서 봅니다.
      </p>
    </div>

    {#if status}
      <div class="flex flex-wrap gap-2">
        <span class={`rounded-full px-3 py-1 text-xs font-semibold ${statusTone(status.worker.status)}`}>
          Worker {status.worker.status}
        </span>
        <span class={`rounded-full px-3 py-1 text-xs font-semibold ${statusTone(status.published_status.status)}`}>
          Publish {status.published_status.status}
        </span>
      </div>
    {/if}
  </div>

  {#if loading && !status}
    <p class="mt-4 text-sm text-slate-500">pipeline 상태를 불러오는 중입니다.</p>
  {:else if error && !status}
    <p class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>
  {:else if status}
    <div class="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <article class="rounded-2xl bg-slate-50 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Booth Seeds</p>
        <p class="mt-2 text-2xl font-semibold text-slate-900">{status.booth_seed_count}</p>
        <p class="mt-1 text-sm text-slate-500">time slots {status.time_slot_count}</p>
      </article>
      <article class="rounded-2xl bg-slate-50 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Events</p>
        <p class="mt-2 text-2xl font-semibold text-slate-900">{status.event_count}</p>
        <p class="mt-1 text-sm text-slate-500">source data rows</p>
      </article>
      <article class="rounded-2xl bg-slate-50 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Popups</p>
        <p class="mt-2 text-2xl font-semibold text-slate-900">{status.popup_count}</p>
        <p class="mt-1 text-sm text-slate-500">source data rows</p>
      </article>
      <article class="rounded-2xl bg-slate-50 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Last Export</p>
        <p class="mt-2 text-lg font-semibold text-slate-900">{formatDateTime(status.last_exported_at)}</p>
        <p class="mt-1 text-sm text-slate-500">booths {status.last_export_booth_count}</p>
      </article>
    </div>

    <div class="mt-4 grid gap-3 lg:grid-cols-2">
      <div class="rounded-2xl border border-slate-200 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Worker Detail</p>
        <p class="mt-2 text-sm font-semibold text-slate-900">{status.worker.message}</p>
        <p class="mt-2 text-sm text-slate-600">state: {status.worker.current_state ?? 'idle'}</p>
        <p class="mt-1 text-sm text-slate-600">
          last heartbeat: {formatDateTime(status.worker.last_heartbeat)}
        </p>
      </div>
      <div class="rounded-2xl border border-slate-200 px-4 py-4">
        <p class="text-xs uppercase tracking-[0.18em] text-slate-500">Publish Sync</p>
        <p class="mt-2 text-sm font-semibold text-slate-900">{status.published_status.status}</p>
        <p class="mt-2 text-sm text-slate-600">
          checked: {formatDateTime(status.published_status.checked_at)}
        </p>
        <p class="mt-1 text-sm text-slate-600">
          last published: {formatDateTime(status.published_status.last_published_at)}
        </p>
      </div>
    </div>
  {/if}
</section>
