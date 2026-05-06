<svelte:head><title>설정 — 이미지 분류기</title></svelte:head>

<script lang="ts">
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import GeneralTab from './GeneralTab.svelte';
  import TagsTab from './TagsTab.svelte';
  import RulesTab from './RulesTab.svelte';

  const subTabs = [
    { id: 'general', label: '일반' },
    { id: 'tags', label: '태그' },
    { id: 'rules', label: '규칙' }
  ];

  let activeTab = $state('general');
</script>

<div class="space-y-4">
  <!-- 헤더 -->
  <PageHeader title="설정" />

  <!-- 서브탭 -->
  <TabNav tabs={subTabs} bind:activeTab variant="secondary" queryParam="tab" />

  <!-- 탭 콘텐츠 -->
  {#if activeTab === 'general'}
    <GeneralTab />
  {:else if activeTab === 'tags'}
    <TagsTab />
  {:else}
    <RulesTab />
  {/if}
</div>
