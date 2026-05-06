<svelte:head><title>대시보드 — 이미지 분류기</title></svelte:head>

<script lang="ts">
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import PipelineTab from './PipelineTab.svelte';
  import AiClassifyTab from './AiClassifyTab.svelte';

  const subTabs = [
    { id: 'pipeline', label: '파이프라인' },
    { id: 'ai', label: 'AI 분류' }
  ];

  let activeTab = $state('pipeline');
</script>

<div class="space-y-4">
  <!-- 헤더 -->
  <PageHeader title="대시보드" />

  <!-- 서브탭 -->
  <TabNav tabs={subTabs} bind:activeTab variant="secondary" queryParam="tab" />

  <!-- 탭 콘텐츠 -->
  {#if activeTab === 'pipeline'}
    <PipelineTab />
  {:else}
    <AiClassifyTab />
  {/if}
</div>
