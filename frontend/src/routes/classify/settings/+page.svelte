<svelte:head><title>설정 — 이미지 분류기</title></svelte:head>

<script lang="ts">
  import TabNav from '$lib/components/layout/TabNav.svelte';
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
  <div>
    <h1 class="text-2xl font-bold tracking-tight">설정</h1>
    <p class="mt-1 text-sm text-muted-foreground">이미지 분류기 동작 방식과 태그, 규칙을 관리합니다</p>
  </div>

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
