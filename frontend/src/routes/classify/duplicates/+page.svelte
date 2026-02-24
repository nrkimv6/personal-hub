<svelte:head><title>중복/유사 — 이미지 분류기</title></svelte:head>

<script lang="ts">
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import DuplicatesTab from './DuplicatesTab.svelte';
  import SimilarTab from './SimilarTab.svelte';

  const subTabs = [
    { id: 'duplicates', label: '중복 제거' },
    { id: 'similar', label: '유사 분류' }
  ];

  let activeTab = $state('duplicates');
</script>

<div class="space-y-4">
  <!-- 헤더 -->
  <PageHeader title="중복/유사" subtitle="중복 이미지 제거와 유사 이미지 분류를 관리합니다" />

  <!-- 서브탭 -->
  <TabNav tabs={subTabs} bind:activeTab variant="secondary" queryParam="tab" />

  <!-- 탭 콘텐츠 -->
  {#if activeTab === 'duplicates'}
    <DuplicatesTab />
  {:else}
    <SimilarTab />
  {/if}
</div>
