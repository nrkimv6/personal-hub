<script lang="ts">
  import { onMount } from 'svelte';
  import { slideScannerApi, type MobileReviewItem } from '$lib/api/slide-scanner';
  import { toast } from '$lib/stores/toast';
  import MobileReviewCard from './MobileReviewCard.svelte';

  export let refreshKey = 0;
  export let onmovetoeditor: ((detail: { itemId: number; slideId: number }) => void) | undefined = undefined;

  const PAGE_SIZE = 24;
  const DEFAULT_APPROVAL_FILTER = ['PENDING', 'APPROVED'] as const;

  let items: MobileReviewItem[] = [];
  let loading = false;
  let loadingMore = false;
  let actionStages: Record<number, string> = {};
  let failureMessages: Record<number, string> = {};
  let total = 0;
  let hasMore = false;
  let deviceFilter = '';
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let observedRefreshKey = 0;

  function hasBusyAction(): boolean {
    return Object.values(actionStages).some((stage) => Boolean(stage));
  }

  function setActionStage(itemId: number, stage: string | null) {
    actionStages = {
      ...actionStages,
      [itemId]: stage ?? ''
    };
  }

  function setFailureMessage(itemId: number, message: string | null) {
    const next = { ...failureMessages };
    if (!message?.trim()) {
      delete next[itemId];
    } else {
      next[itemId] = message;
    }
    failureMessages = next;
  }

  function upsertItem(itemId: number, patch: Partial<MobileReviewItem>) {
    let found = false;
    items = items.map((item) => {
      if (item.id !== itemId) return item;
      found = true;
      return { ...item, ...patch };
    });
    if (!found) {
      void refreshQueue();
    }
  }

  function removeItem(itemId: number) {
    items = items.filter((item) => item.id !== itemId);
    total = Math.max(0, total - 1);
    setActionStage(itemId, null);
    setFailureMessage(itemId, null);
  }

  function mergeItems(currentItems: MobileReviewItem[], nextItems: MobileReviewItem[]): MobileReviewItem[] {
    if (!currentItems.length) return nextItems;
    const currentById = new Map<number, MobileReviewItem>();
    for (const current of currentItems) currentById.set(current.id, current);
    return nextItems.map((next) => {
      const existing = currentById.get(next.id);
      if (!existing) return next;
      const hasLocalError = failureMessages[next.id];
      const keepError = hasLocalError ? { error_message: existing.error_message } : {};
      return { ...next, ...keepError };
    });
  }

  async function loadItems(reset: boolean) {
    if (reset) {
      loading = true;
    } else {
      loadingMore = true;
    }

    try {
      const response = await slideScannerApi.getMobileReviewItems({
        deviceId: deviceFilter.trim() || undefined,
        approvalStatus: [...DEFAULT_APPROVAL_FILTER],
        skip: reset ? 0 : items.length,
        limit: PAGE_SIZE
      });

      const nextItems = reset ? response.items : [...items, ...response.items];
      items = reset ? mergeItems(items, nextItems) : nextItems;
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

  async function handleApprove(detail: { itemId: number }) {
    const { itemId } = detail;
    setActionStage(itemId, 'approve');
    try {
      const response = await slideScannerApi.approveMobileItem(itemId);
      upsertItem(itemId, response);
      setFailureMessage(itemId, null);
      toast.success('승인 처리되었습니다. 원격 삭제 단계로 진행하세요.');
    } catch (error) {
      const message = error instanceof Error ? error.message : '승인 처리 실패';
      setFailureMessage(itemId, message);
      toast.error(message);
    } finally {
      setActionStage(itemId, null);
    }
  }

  async function handleReject(detail: { itemId: number; reason: string }) {
    const { itemId, reason } = detail;
    setActionStage(itemId, 'reject');
    try {
      await slideScannerApi.rejectMobileItem(itemId, reason);
      removeItem(itemId);
      toast.success('반려 처리되었습니다.');
    } catch (error) {
      const message = error instanceof Error ? error.message : '반려 처리 실패';
      setFailureMessage(itemId, message);
      toast.error(message);
    } finally {
      setActionStage(itemId, null);
    }
  }

  async function handleRemoteDelete(detail: { itemId: number }) {
    const { itemId } = detail;
    setActionStage(itemId, 'remote delete');
    try {
      const response = await slideScannerApi.remoteDeleteMobileItem(itemId, false);
      upsertItem(itemId, response);
      if (response.status === 'failed') {
        const message = response.error || '원격 삭제 실패';
        setFailureMessage(itemId, message);
        toast.error(`원격 삭제 실패: ${message}`);
      } else {
        setFailureMessage(itemId, null);
        toast.success('원격 삭제 완료되었습니다.');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '원격 삭제 실패';
      setFailureMessage(itemId, message);
      toast.error(message);
    } finally {
      setActionStage(itemId, null);
    }
  }

  async function handleRetryRemoteDelete(detail: { itemId: number }) {
    const { itemId } = detail;
    setActionStage(itemId, 'remote delete retry');
    try {
      const response = await slideScannerApi.remoteDeleteMobileItem(itemId, true);
      upsertItem(itemId, response);
      if (response.status === 'failed') {
        const message = response.error || '원격 삭제 재시도 실패';
        setFailureMessage(itemId, message);
        toast.error(`원격 삭제 재시도 실패: ${message}`);
      } else {
        setFailureMessage(itemId, null);
        toast.success('원격 삭제 재시도에 성공했습니다.');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '원격 삭제 재시도 실패';
      setFailureMessage(itemId, message);
      toast.error(message);
    } finally {
      setActionStage(itemId, null);
    }
  }

  async function handleHandoff(detail: { itemId: number }) {
    const { itemId } = detail;
    setActionStage(itemId, 'handoff');
    try {
      const response = await slideScannerApi.handoffMobileItem(itemId);
      upsertItem(itemId, response);
      setFailureMessage(itemId, null);
      toast.success('handoff 완료. 에디터 열기가 활성화되었습니다.');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'handoff 실패';
      setFailureMessage(itemId, message);
      toast.error(message);
    } finally {
      setActionStage(itemId, null);
    }
  }

  function handleMoveToEditor(detail: { itemId: number; slideId: number }) {
    onmovetoeditor?.(detail);
  }

  $: if (refreshKey !== observedRefreshKey) {
    observedRefreshKey = refreshKey;
    void refreshQueue();
  }

  onMount(() => {
    void refreshQueue();
    pollTimer = setInterval(() => {
      if (loading || loadingMore || hasBusyAction()) return;
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
        승인 큐 항목을 단계별로 처리합니다. (승인 → 원격 삭제 → handoff → 에디터 열기)
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
      처리할 승인 항목이 없습니다.
    </p>
  {:else}
    <div class="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {#each items as item (item.id)}
        <MobileReviewCard
          {item}
          busy={Boolean(actionStages[item.id])}
          busyStage={actionStages[item.id] || null}
          failureMessage={failureMessages[item.id] || null}
          onapprove={handleApprove}
          onreject={handleReject}
          onremotedelete={handleRemoteDelete}
          onretryremotedelete={handleRetryRemoteDelete}
          onhandoff={handleHandoff}
          onmovetoeditor={handleMoveToEditor}
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
