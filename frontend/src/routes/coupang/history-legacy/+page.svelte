<script lang="ts">
  import { goto } from '$app/navigation';
  import { isAdmin } from '$lib/stores/auth';
  import CancellationHistoryTab from '$lib/components/coupang/CancellationHistoryTab.svelte';

  $effect(() => {
    if ($isAdmin) {
      goto('/coupang?tab=cancellation-history', { replaceState: true });
    }
  });
</script>

{#if !$isAdmin}
  <div class="p-4 lg:p-6">
    <h1 class="text-2xl font-bold mb-6">취소표 발생 이력</h1>
    <CancellationHistoryTab />
  </div>
{/if}
