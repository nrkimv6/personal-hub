<script lang="ts">
  import { goto } from '$app/navigation';
  import { isAdmin } from '$lib/stores/auth';
  import PublicCoupangHistoryTab from '$lib/components/coupang/PublicCoupangHistoryTab.svelte';

  $effect(() => {
    if ($isAdmin) {
      goto('/coupang?tab=cancellation-history', { replaceState: true });
    }
  });
</script>

{#if !$isAdmin}
  <div class="p-4 lg:p-6">
    <h1 class="mb-6 text-2xl font-bold">쿠팡 취소표 이력</h1>
    <p class="mb-6 text-sm text-muted-foreground">
      취소표 발생과 재매진을 옵션-시간대 단위 페어 레코드로 분리해, 발견 시각 기준의 공개 이력을 보여준다.
    </p>
    <PublicCoupangHistoryTab />
  </div>
{/if}
