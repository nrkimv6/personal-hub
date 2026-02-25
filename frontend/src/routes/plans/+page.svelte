<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';

  onMount(() => {
    // /plans?tab=archive → /automation?tab=plans&subtab=archive 매핑
    const tabParam = $page.url.searchParams.get('tab');
    const url = new URL('/automation', window.location.origin);
    url.searchParams.set('tab', 'plans');
    if (tabParam && ['archive', 'history'].includes(tabParam)) {
      url.searchParams.set('subtab', tabParam);
    }
    goto(url.toString(), { replaceState: true });
  });
</script>
