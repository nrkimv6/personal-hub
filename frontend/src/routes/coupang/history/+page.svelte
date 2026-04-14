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
      옵션 날짜+시간 기준의 전환 이력만 보여준다.
    </p>
    <PublicCoupangHistoryTab />
  </div>
{/if}
