<script lang="ts">
  import { page } from '$app/stores';

  const tabs = [
    { href: '/proxy', label: '대시보드', exact: true },
    { href: '/proxy/list', label: '프록시 목록', exact: false },
    { href: '/proxy/usage', label: '사용 이력', exact: false }
  ];

  function isTabActive(tab: { href: string; exact: boolean }, pathname: string): boolean {
    if (tab.exact) return pathname === tab.href;
    return pathname.startsWith(tab.href);
  }
</script>

<div class="p-6">
  <div class="mb-6">
    <h1 class="text-2xl font-bold text-foreground">프록시 관리</h1>
    <p class="text-muted-foreground mt-1">프록시 수집 현황 및 품질 모니터링</p>
  </div>

  <!-- 탭 네비게이션 -->
  <div class="border-b border-border mb-6">
    <nav class="flex gap-4">
      {#each tabs as tab}
        <a
          href={tab.href}
          class="px-4 py-2 border-b-2 font-medium text-sm transition-colors
            {isTabActive(tab, $page.url.pathname)
              ? 'border-blue-500 text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'}"
        >
          {tab.label}
        </a>
      {/each}
    </nav>
  </div>

  <slot />
</div>
