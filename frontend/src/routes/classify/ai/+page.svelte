<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => {
    goto('/classify/dashboard?tab=ai', { replaceState: true });
  });
</script>
