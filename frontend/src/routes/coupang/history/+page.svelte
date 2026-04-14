<script lang="ts">
  import { goto } from '$app/navigation';
  import { isAdmin } from '$lib/stores/auth';
  import MegabeautyHistoryTab from '$lib/components/coupang/MegabeautyHistoryTab.svelte';

  $effect(() => {
    if ($isAdmin) {
      goto('/coupang?tab=cancellation-history', { replaceState: true });
    }
  });
</script>

{#if !$isAdmin}
  <div class="p-4 lg:p-6">
    <h1 class="text-2xl font-bold mb-6">쿠팡 메가뷰티쇼 취소이력</h1>
    <MegabeautyHistoryTab />
  </div>
{/if}
