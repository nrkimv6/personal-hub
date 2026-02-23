<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { Plus } from 'lucide-svelte';
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
  <div class="flex items-center justify-between px-6 py-4 border-b border-border bg-card">
    <h1 class="text-lg font-bold text-foreground">메모</h1>
    {#if activeTab === 'notes'}
      <button
        onclick={() => (showCreateModal = true)}
        class="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-primary-foreground bg-primary rounded-lg hover:bg-primary-hover transition-colors"
      >
        <Plus class="w-4 h-4" />
        새 메모
      </button>
    {/if}
  </div>

  <!-- 탭 -->
  <div class="flex gap-6 px-6 border-b border-border bg-card">
    {#each [['notes', '메모'], ['archive', '아카이브'], ['tags', '태그 관리']] as [id, label]}
      <button
        onclick={() => setTab(id as Tab)}
        class="relative py-3 text-sm font-medium transition-colors
          {activeTab === id
            ? 'text-primary'
            : 'text-muted-foreground hover:text-foreground'}"
      >
        {label}
        {#if activeTab === id}
          <span class="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-full"></span>
        {/if}
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

<!-- FAB (모바일) -->
{#if activeTab === 'notes'}
  <button
    onclick={() => (showCreateModal = true)}
    class="fixed bottom-6 right-6 w-14 h-14 rounded-full bg-primary text-primary-foreground shadow-modal flex items-center justify-center md:hidden z-40 hover:bg-primary-hover transition-colors"
    aria-label="새 메모"
  >
    <Plus class="w-6 h-6" />
  </button>
{/if}

<!-- 새 메모 생성 모달 -->
{#if showCreateModal}
  <NoteFormModal
    mode="create"
    onSave={handleNoteCreated}
    onClose={() => (showCreateModal = false)}
  />
{/if}
