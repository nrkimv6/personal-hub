<script lang="ts">
  import type { Snippet } from 'svelte';
  import TabNav from '$lib/components/layout/TabNav.svelte';

  let { children }: { children: Snippet } = $props();

  const navTabs = [
    { id: 'posts', label: '게시물', href: '/collect', exact: true },
    { id: 'rules', label: '분류 규칙', href: '/collect/rules' },
    { id: 'history', label: '수집 이력', href: '/collect/history' },
    { id: 'google', label: '구글 검색', href: '/collect/google' }
  ];
</script>

<div class="p-4">
  <h1 class="text-2xl font-bold mb-4 dark:text-white">수집 관리</h1>

  <TabNav tabs={navTabs} variant="primary" urlBased />

  {@render children()}
</div>
