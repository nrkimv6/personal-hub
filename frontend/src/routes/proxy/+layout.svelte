<script lang="ts">
  import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';

  const navTabs = [
    { id: 'dashboard', label: '대시보드', href: '/proxy', exact: true },
    { id: 'list', label: '프록시 목록', href: '/proxy/list' },
    { id: 'usage', label: '사용 이력', href: '/proxy/usage' }
  ];
</script>

<TabbedPageLayout
  title="프록시 관리"
  subtitle="프록시 수집 현황 및 품질 모니터링"
  primaryTabs={navTabs}
  primaryUrlBased
  density="compact"
  containerClass="space-y-3 p-4 lg:p-6"
>
  <slot />
</TabbedPageLayout>
