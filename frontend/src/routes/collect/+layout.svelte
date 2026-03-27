<script lang="ts">
  import type { Snippet } from 'svelte';
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';

  let { children }: { children: Snippet } = $props();

  const navTabs = [
    { id: 'posts', label: '게시물', href: '/collect', exact: true },
    { id: 'rules', label: '분류 규칙', href: '/collect/rules' },
    { id: 'history', label: '수집 이력', href: '/collect/history' },
    { id: 'google', label: '구글 검색', href: '/collect/google' }
  ];
</script>

<div class="p-4 lg:p-6">
  <PageHeader title="수집 관리" />

  <TabNav tabs={navTabs} variant="primary" urlBased />

  {@render children()}
</div>
