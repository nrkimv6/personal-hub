<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => {
    goto('/classify/duplicates?tab=similar', { replaceState: true });
  });
</script>
