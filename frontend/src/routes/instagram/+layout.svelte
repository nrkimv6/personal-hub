<script lang="ts">
  import type { Snippet } from 'svelte';
  import TabNav from '$lib/components/layout/TabNav.svelte';

  let { children }: { children: Snippet } = $props();

  const navTabs = [
    { id: 'dashboard', label: '대시보드', href: '/instagram', exact: true },
    { id: 'posts', label: '게시물', href: '/instagram/posts' },
    { id: 'tags', label: '태그 관리', href: '/instagram/tags' }
  ];
</script>

<div class="p-4">
  <h1 class="text-2xl font-bold mb-4 dark:text-white">Instagram</h1>

  <TabNav tabs={navTabs} variant="primary" urlBased />

  {@render children()}
</div>
