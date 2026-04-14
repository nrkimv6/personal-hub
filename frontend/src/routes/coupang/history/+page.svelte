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
    <PublicCoupangHistoryTab />
  </div>
{/if}
