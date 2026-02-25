<script lang="ts">
  import TabNav from '$lib/components/layout/TabNav.svelte';

  const navTabs = [
    { id: 'dashboard', label: '대시보드', href: '/proxy', exact: true },
    { id: 'list', label: '프록시 목록', href: '/proxy/list' },
    { id: 'usage', label: '사용 이력', href: '/proxy/usage' }
  ];
</script>

<div class="p-6">
  <div class="mb-6">
    <h1 class="text-2xl font-bold text-foreground">프록시 관리</h1>
    <p class="text-muted-foreground mt-1">프록시 수집 현황 및 품질 모니터링</p>
  </div>

  <TabNav tabs={navTabs} variant="primary" urlBased />

  <slot />
</div>
