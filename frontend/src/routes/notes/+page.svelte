<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { Plus } from 'lucide-svelte';
  import NoteList from './components/NoteList.svelte';
  import NoteArchiveList from './components/NoteArchiveList.svelte';
  import NoteTagManager from './components/NoteTagManager.svelte';
  import NoteFormModal from './components/NoteFormModal.svelte';
  import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';

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

{#snippet headerActions()}
  {#if activeTab === 'notes'}
    <button
      onclick={() => (showCreateModal = true)}
      class="hidden items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover md:flex"
    >
      <Plus class="h-4 w-4" />
      새 메모
    </button>
  {/if}
{/snippet}

<TabbedPageLayout
  title="메모"
  subtitle="메모, 아카이브, 태그 관리를 같은 규약으로 다룹니다."
  actions={headerActions}
  primaryTabs={noteTabs}
  bind:activePrimaryTab={activeTab}
  primaryQueryParam="tab"
  density="compact"
  containerClass="flex h-full min-h-0 flex-col gap-3 p-4 lg:p-6"
  contentClass="min-h-0 flex-1 overflow-hidden"
>
  <div class="flex-1 overflow-hidden">
    {#if activeTab === 'notes'}
      <NoteList bind:this={noteListRef} />
    {:else if activeTab === 'archive'}
      <NoteArchiveList />
    {:else if activeTab === 'tags'}
      <NoteTagManager />
    {/if}
  </div>
</TabbedPageLayout>

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
