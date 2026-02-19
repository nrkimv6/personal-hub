<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => {
    goto('/classify/images?tab=history', { replaceState: true });
  });
</script>
