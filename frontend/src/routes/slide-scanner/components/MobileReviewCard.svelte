<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { slideScannerApi, type MobileReviewItem } from '$lib/api/slide-scanner';
  import { toast } from '$lib/stores/toast';

  export let item: MobileReviewItem;
  export let busy = false;

  const dispatch = createEventDispatcher<{
    approve: { itemId: number };
    reject: { itemId: number; reason: string };
    moveToEditor: { itemId: number; fileName: string };
  }>();

  let rejectReason = '';
  let imageBroken = false;

  function formatDate(value: string): string {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleString();
  }

  function handleApprove() {
    dispatch('approve', { itemId: item.id });
  }

  function handleReject() {
    const reason = rejectReason.trim();
    if (!reason) {
      toast.warning('반려 사유를 입력하세요.');
      return;
    }
    dispatch('reject', { itemId: item.id, reason });
    rejectReason = '';
  }

  function handleMoveToEditor() {
    dispatch('moveToEditor', { itemId: item.id, fileName: item.original_filename });
  }
</script>

<article class="rounded-xl border border-border bg-card p-3">
  <div class="mb-3 overflow-hidden rounded-md border border-border bg-muted/10">
    {#if imageBroken}
      <div class="flex h-44 items-center justify-center text-xs text-muted-foreground">이미지를 불러올 수 없습니다.</div>
    {:else}
      <img
        src={slideScannerApi.getMobileReviewImageUrl(item.id)}
        alt={item.original_filename}
        class="h-44 w-full object-cover"
        onerror={() => {
          imageBroken = true;
        }}
      />
    {/if}
  </div>

  <div class="space-y-1 text-xs">
    <p class="font-medium">{item.original_filename}</p>
    <p class="text-muted-foreground">기기: {item.device_alias || item.device_serial}</p>
    <p class="text-muted-foreground">촬영시각: {formatDate(item.captured_at_utc)}</p>
    <p class="text-muted-foreground">상태: {item.approval_status} / 삭제 {item.remote_delete_status}</p>
  </div>

  <div class="mt-3 flex flex-wrap gap-2">
    <button type="button" class="btn btn-sm btn-primary" onclick={handleApprove} disabled={busy}>
      승인
    </button>
    <button type="button" class="btn btn-sm btn-outline" onclick={handleMoveToEditor} disabled={busy}>
      보정 단계로 이동
    </button>
  </div>

  <div class="mt-3 space-y-2">
    <input
      type="text"
      class="input input-sm w-full"
      placeholder="반려 사유 입력"
      bind:value={rejectReason}
      disabled={busy}
    />
    <button type="button" class="btn btn-sm btn-outline w-full" onclick={handleReject} disabled={busy}>
      반려
    </button>
  </div>
</article>
