<script lang="ts">
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();
</script>

<div class="p-4 lg:p-6">
  {@render children()}
</div>
