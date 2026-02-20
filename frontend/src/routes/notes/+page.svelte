<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import NoteList from './components/NoteList.svelte';
  import NoteArchiveList from './components/NoteArchiveList.svelte';
  import NoteTagManager from './components/NoteTagManager.svelte';
  import NoteFormModal from './components/NoteFormModal.svelte';

  type Tab = 'notes' | 'archive' | 'tags';

  let activeTab: Tab = 'notes';
  let showCreateModal = false;

  $: {
    const tabParam = $page.url.searchParams.get('tab') as Tab | null;
    activeTab = tabParam && ['notes', 'archive', 'tags'].includes(tabParam) ? tabParam : 'notes';
  }

  function setTab(tab: Tab) {
    const url = new URL(window.location.href);
    if (tab === 'notes') {
      url.searchParams.delete('tab');
    } else {
      url.searchParams.set('tab', tab);
    }
    goto(url.toString(), { replaceState: true, noScroll: true });
  }

  function handleNoteCreated() {
    showCreateModal = false;
  }
</script>

<div class="flex flex-col h-full">
  <!-- 헤더 -->
  <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
    <h1 class="text-xl font-semibold text-gray-900 dark:text-white">메모</h1>
    {#if activeTab === 'notes'}
      <button
        onclick={() => (showCreateModal = true)}
        class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
      >
        + 새 메모
      </button>
    {/if}
  </div>

  <!-- 탭 -->
  <div class="flex gap-1 px-6 pt-3 border-b border-gray-200 dark:border-gray-700">
    {#each [['notes', '메모'], ['archive', '아카이브'], ['tags', '태그 관리']] as [id, label]}
      <button
        onclick={() => setTab(id as Tab)}
        class="px-4 py-2 text-sm font-medium rounded-t-md border-b-2 transition-colors
          {activeTab === id
            ? 'border-blue-600 text-blue-600'
            : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'}"
      >
        {label}
      </button>
    {/each}
  </div>

  <!-- 탭 콘텐츠 -->
  <div class="flex-1 overflow-hidden">
    {#if activeTab === 'notes'}
      <NoteList />
    {:else if activeTab === 'archive'}
      <NoteArchiveList />
    {:else if activeTab === 'tags'}
      <NoteTagManager />
    {/if}
  </div>
</div>

<!-- 새 메모 생성 모달 -->
{#if showCreateModal}
  <NoteFormModal
    mode="create"
    onSave={handleNoteCreated}
    onClose={() => (showCreateModal = false)}
  />
{/if}
