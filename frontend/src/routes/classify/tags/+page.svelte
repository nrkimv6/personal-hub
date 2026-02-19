<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => {
    goto('/classify/settings?tab=tags', { replaceState: true });
  });
</script>
