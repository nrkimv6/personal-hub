<script lang="ts">
  import type { Snippet } from 'svelte';
  import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';

  let { children }: { children: Snippet } = $props();

  const navTabs = [
    { id: 'posts', label: '게시물', href: '/collect', exact: true },
    { id: 'rules', label: '분류 규칙', href: '/collect/rules' },
    { id: 'history', label: '수집 이력', href: '/collect/history' },
    { id: 'google', label: '구글 검색', href: '/collect/google' },
    { id: 'follow-diff', label: '팔로우 Diff', href: '/collect/follow-diff' }
  ];
</script>

<TabbedPageLayout
  title="수집 관리"
  primaryTabs={navTabs}
  primaryUrlBased
  density="compact"
  containerClass="space-y-3 p-4 lg:p-6"
>
  {@render children()}
</TabbedPageLayout>
