<script lang="ts">
  import type { Snippet } from 'svelte';
  import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';

  let { children }: { children: Snippet } = $props();

  const navTabs = [
    { id: 'dashboard', label: '대시보드', href: '/instagram', exact: true },
    { id: 'posts', label: '게시물', href: '/instagram/posts' },
    { id: 'tags', label: '태그 관리', href: '/instagram/tags' }
  ];
</script>

<TabbedPageLayout
  title="Instagram"
  primaryTabs={navTabs}
  primaryUrlBased
  density="compact"
  containerClass="space-y-3 p-4 lg:p-6"
>
  {@render children()}
</TabbedPageLayout>
