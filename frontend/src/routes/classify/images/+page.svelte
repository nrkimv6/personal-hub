<svelte:head><title>이미지 — 이미지 분류기</title></svelte:head>

<script lang="ts">
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import GalleryTab from './GalleryTab.svelte';
  import ClustersTab from './ClustersTab.svelte';
  import ReviewTab from './ReviewTab.svelte';
  import HistoryTab from './HistoryTab.svelte';

  const subTabs = [
    { id: 'gallery', label: '갤러리' },
    { id: 'clusters', label: '클러스터' },
    { id: 'review', label: '검토' },
    { id: 'history', label: '이력' }
  ];

  let activeTab = $state('gallery');
</script>

<div class="space-y-4">
  <!-- 헤더 -->
  <PageHeader title="이미지" subtitle="이미지를 갤러리, 클러스터, 검토, 이력으로 관리합니다" />

  <!-- 서브탭 -->
  <TabNav tabs={subTabs} bind:activeTab variant="secondary" queryParam="tab" />

  <!-- 탭 콘텐츠 -->
  {#if activeTab === 'gallery'}
    <GalleryTab />
  {:else if activeTab === 'clusters'}
    <ClustersTab />
  {:else if activeTab === 'review'}
    <ReviewTab />
  {:else}
    <HistoryTab />
  {/if}
</div>
