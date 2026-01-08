<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();

  const primaryTabs = [
    { id: 'dashboard', label: '대시보드', path: '/instagram' },
    { id: 'posts', label: '게시물', path: '/instagram/posts' },
    { id: 'tags', label: '태그 관리', path: '/instagram/tags' }
  ];

  // 현재 경로에서 활성 탭 결정
  let activeTab = $derived.by(() => {
    const pathname = $page.url.pathname;
    if (pathname.startsWith('/instagram/posts')) return 'posts';
    if (pathname.startsWith('/instagram/tags')) return 'tags';
    // schedule, history, runs, crawl 페이지는 대시보드 탭에 속함
    return 'dashboard';
  });

  // 탭 변경 시 해당 경로로 이동
  function handleTabChange(tabId: string) {
    const tab = primaryTabs.find(t => t.id === tabId);
    if (tab) {
      goto(tab.path);
    }
  }
</script>

<div class="p-4">
  <h1 class="text-2xl font-bold mb-4 dark:text-white">Instagram</h1>

  <div class="border-b border-border dark:border-gray-700 mb-4">
    <nav class="flex space-x-1" aria-label="Primary Tabs">
      {#each primaryTabs as tab}
        <button
          onclick={() => handleTabChange(tab.id)}
          class="py-3 px-5 border-b-2 font-medium text-base transition-colors
            {activeTab === tab.id
              ? 'border-blue-500 text-primary dark:text-blue-400'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'}"
        >
          {tab.label}
        </button>
      {/each}
    </nav>
  </div>

  {@render children()}
</div>
