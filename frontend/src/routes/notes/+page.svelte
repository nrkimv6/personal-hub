<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { Plus } from 'lucide-svelte';
  import NoteList from './components/NoteList.svelte';
  import NoteArchiveList from './components/NoteArchiveList.svelte';
  import NoteTagManager from './components/NoteTagManager.svelte';
  import NoteFormModal from './components/NoteFormModal.svelte';
  import TabNav from '$lib/components/layout/TabNav.svelte';

  type Tab = 'notes' | 'archive' | 'tags';

  let activeTab: Tab = 'notes';
  let showCreateModal = false;
  let noteListRef: NoteList;

  const noteTabs = [
    { id: 'notes', label: '메모' },
    { id: 'archive', label: '아카이브' },
    { id: 'tags', label: '태그 관리' },
  ];

  function handleNoteCreated() {
    showCreateModal = false;
    noteListRef?.refresh();
  }

  function handleGlobalKeydown(e: KeyboardEvent) {
    const ctrl = e.ctrlKey || e.metaKey;
    const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
    const isInputFocused = tag === 'input' || tag === 'textarea';

    // Escape: 모달 닫기
    if (e.key === 'Escape' && showCreateModal) {
      showCreateModal = false;
      return;
    }

    // 입력창 포커스 중이면 나머지 글로벌 단축키 스킵
    if (isInputFocused) return;

    // Ctrl+N: 새 메모 모달 열기
    if (ctrl && e.key === 'n' && !showCreateModal) {
      e.preventDefault();
      if (activeTab === 'notes') showCreateModal = true;
      return;
    }

    // Ctrl+K: 검색 input 포커스
    if (ctrl && e.key === 'k') {
      e.preventDefault();
      const searchInput = document.querySelector<HTMLInputElement>('input[type="search"], input[placeholder*="검색"]');
      searchInput?.focus();
      return;
    }
  }

  onMount(() => {
    document.addEventListener('keydown', handleGlobalKeydown);
  });

  onDestroy(() => {
    document.removeEventListener('keydown', handleGlobalKeydown);
  });
</script>

<div class="flex flex-col h-full">
  <!-- 헤더 -->
  <div class="flex items-center justify-between px-6 py-4 border-b border-border bg-card">
    <h1 class="text-xl font-bold tracking-tight text-foreground">메모</h1>
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
  <TabNav tabs={noteTabs} bind:activeTab variant="primary" queryParam="tab" />

  <!-- 탭 콘텐츠 -->
  <div class="flex-1 overflow-hidden">
    {#if activeTab === 'notes'}
      <NoteList bind:this={noteListRef} />
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
