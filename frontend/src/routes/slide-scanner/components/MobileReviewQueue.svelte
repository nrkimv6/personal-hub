<script lang="ts">
  import { createEventDispatcher, onMount } from 'svelte';
  import { slideScannerApi, type MobileReviewItem } from '$lib/api/slide-scanner';
  import { toast } from '$lib/stores/toast';
  import MobileReviewCard from './MobileReviewCard.svelte';

  export let refreshKey = 0;

  const dispatch = createEventDispatcher<{
    moveToEditor: { itemId: number; fileName: string };
  }>();

  const PAGE_SIZE = 24;
  let items: MobileReviewItem[] = [];
  let loading = false;
  let loadingMore = false;
  let actingItemId: number | null = null;
  let total = 0;
  let hasMore = false;
  let deviceFilter = '';
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let observedRefreshKey = 0;

  async function loadItems(reset: boolean) {
    if (reset) {
      loading = true;
    } else {
      loadingMore = true;
    }

    try {
      const response = await slideScannerApi.getMobileReviewItems({
        deviceId: deviceFilter.trim() || undefined,
        skip: reset ? 0 : items.length,
        limit: PAGE_SIZE
      });

      items = reset ? response.items : [...items, ...response.items];
      total = response.total;
      hasMore = response.has_more;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '승인 큐 조회 실패');
    } finally {
      loading = false;
      loadingMore = false;
    }
  }

  async function refreshQueue() {
    await loadItems(true);
  }

  async function loadMore() {
    if (!hasMore || loading || loadingMore) return;
    await loadItems(false);
  }

  async function handleApprove(event: CustomEvent<{ itemId: number }>) {
    const { itemId } = event.detail;
    actingItemId = itemId;
    try {
      await slideScannerApi.approveMobileItem(itemId);
      items = items.filter((item) => item.id !== itemId);
      total = Math.max(0, total - 1);
      toast.success('승인 처리되었습니다.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '승인 처리 실패');
    } finally {
      actingItemId = null;
    }
  }

  async function handleReject(event: CustomEvent<{ itemId: number; reason: string }>) {
    const { itemId, reason } = event.detail;
    actingItemId = itemId;
    try {
      await slideScannerApi.rejectMobileItem(itemId, reason);
      items = items.filter((item) => item.id !== itemId);
      total = Math.max(0, total - 1);
      toast.success('반려 처리되었습니다.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '반려 처리 실패');
    } finally {
      actingItemId = null;
    }
  }

  function handleMoveToEditor(event: CustomEvent<{ itemId: number; fileName: string }>) {
    dispatch('moveToEditor', event.detail);
  }

  $: if (refreshKey !== observedRefreshKey) {
    observedRefreshKey = refreshKey;
    void refreshQueue();
  }

  onMount(() => {
    void refreshQueue();
    pollTimer = setInterval(() => {
      if (loading || loadingMore || actingItemId !== null) return;
      void refreshQueue();
    }, 7000);

    return () => {
      if (pollTimer) clearInterval(pollTimer);
    };
  });
</script>

<section class="rounded-xl border border-border bg-card p-4">
  <div class="flex flex-wrap items-end justify-between gap-2">
    <div>
      <h3 class="text-sm font-semibold">모바일 승인 큐</h3>
      <p class="mt-1 text-xs text-muted-foreground">
        승인 대기 이미지를 확인하고 승인/반려 후 보정 단계로 넘깁니다.
      </p>
    </div>
    <div class="flex items-center gap-2">
      <input
        type="text"
        class="input input-sm w-40"
        placeholder="device_id 필터"
        bind:value={deviceFilter}
      />
      <button type="button" class="btn btn-sm btn-outline" onclick={refreshQueue} disabled={loading}>
        조회
      </button>
    </div>
  </div>

  <div class="mt-3 text-xs text-muted-foreground">
    총 {total}건, 현재 표시 {items.length}건
  </div>

  {#if loading}
    <p class="mt-3 text-xs text-muted-foreground">승인 큐를 불러오는 중...</p>
  {:else if items.length === 0}
    <p class="mt-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      승인 대기 항목이 없습니다.
    </p>
  {:else}
    <div class="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {#each items as item (item.id)}
        <MobileReviewCard
          {item}
          busy={actingItemId === item.id}
          on:approve={handleApprove}
          on:reject={handleReject}
          on:moveToEditor={handleMoveToEditor}
        />
      {/each}
    </div>
  {/if}

  {#if hasMore}
    <div class="mt-4 text-center">
      <button type="button" class="btn btn-sm btn-outline" onclick={loadMore} disabled={loadingMore}>
        {loadingMore ? '로딩 중...' : '더 보기'}
      </button>
    </div>
  {/if}
</section>
