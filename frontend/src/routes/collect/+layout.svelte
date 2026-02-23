<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();

  const tabs = [
    { id: 'posts', label: '게시물', path: '/collect' },
    { id: 'rules', label: '분류 규칙', path: '/collect/rules' },
    { id: 'history', label: '크롤링 이력', path: '/collect/history' },
    { id: 'schedule', label: '스케줄 설정', path: '/collect/schedule' },
    { id: 'google', label: '구글 검색', path: '/collect/google' }
  ];

  // 현재 경로에서 활성 탭 결정
  let activeTab = $derived.by(() => {
    const pathname = $page.url.pathname;
    if (pathname.startsWith('/collect/google')) return 'google';
    if (pathname.startsWith('/collect/rules')) return 'rules';
    if (pathname.startsWith('/collect/history')) return 'history';
    if (pathname.startsWith('/collect/schedule')) return 'schedule';
    return 'posts';
  });

  // 탭 변경 시 해당 경로로 이동
  function handleTabChange(tabId: string) {
    const tab = tabs.find(t => t.id === tabId);
    if (tab) {
      goto(tab.path);
    }
  }
</script>

<div class="p-4">
  <h1 class="text-2xl font-bold mb-4 dark:text-white">수집 관리</h1>

  <div class="border-b border-border dark:border-gray-700 mb-4">
    <nav class="flex space-x-1" aria-label="Collect Tabs">
      {#each tabs as tab}
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
