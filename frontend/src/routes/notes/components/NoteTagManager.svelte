<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { TagDef } from '$lib/api/notes';
  import { Trash2, Pencil, Check, X, Plus, Tag as TagIcon } from 'lucide-svelte';

  let tags = $state<TagDef[]>([]);
  let loading = $state(false);
  let error = $state('');

  // 새 태그 폼
  let showCreateForm = $state(false);
  let newName = $state('');
  let newColor = $state('#6b7280');
  let creating = $state(false);

  // 편집 상태
  let editId = $state<number | null>(null);
  let editName = $state('');
  let editColor = $state('');
  let saving = $state(false);

  // 삭제 확인
  let deleteConfirmId = $state<number | null>(null);
  let deleteTimer: ReturnType<typeof setTimeout>;

  async function load() {
    loading = true;
    error = '';
    try {
      tags = await notesApi.listTags();
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function createTag() {
    if (!newName.trim()) return;
    creating = true;
    try {
      await notesApi.createTag({ name: newName.trim(), color: newColor });
      newName = '';
      newColor = '#6b7280';
      showCreateForm = false;
      load();
    } catch (e: any) {
      alert(e.message);
    } finally {
      creating = false;
    }
  }

  function startEdit(tag: TagDef) {
    editId = tag.id;
    editName = tag.name;
    editColor = tag.color;
  }

  async function saveEdit() {
    if (!editId) return;
    saving = true;
    try {
      await notesApi.updateTag(editId, { name: editName.trim(), color: editColor });
      editId = null;
      load();
    } catch (e: any) {
      alert(e.message);
    } finally {
      saving = false;
    }
  }

  function requestDelete(id: number) {
    deleteConfirmId = id;
    clearTimeout(deleteTimer);
    deleteTimer = setTimeout(() => (deleteConfirmId = null), 3000);
  }

  async function confirmDelete(id: number) {
    clearTimeout(deleteTimer);
    deleteConfirmId = null;
    try {
      await notesApi.deleteTag(id);
      load();
    } catch (e: any) {
      alert(e.message);
    }
  }

  onMount(load);
</script>

<div class="p-6 overflow-y-auto h-full">
  <!-- 헤더 행 -->
  <div class="flex items-center justify-between mb-4">
    <span class="text-xs text-muted-foreground">태그 {tags.length}개</span>
    <button
      onclick={() => { showCreateForm = !showCreateForm; }}
      class="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary-hover transition-colors"
    ><Plus class="w-4 h-4" /> New Tag</button>
  </div>

  <!-- 생성 폼 (inline row) -->
  {#if showCreateForm}
    <div class="flex gap-2 items-center mb-4 p-3 bg-card border border-primary/20 rounded-lg">
      <input
        type="color"
        bind:value={newColor}
        class="h-8 w-8 rounded cursor-pointer border-0 flex-shrink-0"
        title="색상 선택"
      />
      <input
        type="text"
        bind:value={newName}
        placeholder="태그 이름..."
        class="flex-1 px-3 py-1.5 text-sm rounded-lg border border-border bg-background text-foreground
          focus:outline-none focus:ring-2 focus:ring-ring/30"
        onkeydown={(e) => e.key === 'Enter' && createTag()}
      />
      <button
        onclick={createTag}
        disabled={creating || !newName.trim()}
        class="p-1.5 rounded-lg text-success hover:bg-success-light disabled:opacity-50 transition-colors"
        title="추가"
      ><Check class="w-4 h-4" /></button>
      <button
        onclick={() => { showCreateForm = false; newName = ''; }}
        class="p-1.5 rounded-lg text-muted-foreground hover:bg-muted transition-colors"
        title="취소"
      ><X class="w-4 h-4" /></button>
    </div>
  {/if}

  <!-- 태그 목록 -->
  {#if loading}
    <div class="space-y-2">
      {#each Array(3) as _}
        <div class="animate-skeleton-shimmer h-10 rounded-lg"></div>
      {/each}
    </div>
  {:else if error}
    <div class="text-center text-destructive text-sm py-8">{error}</div>
  {:else if tags.length === 0}
    <div class="flex flex-col items-center justify-center py-16 gap-3">
      <div class="w-14 h-14 bg-muted rounded-2xl flex items-center justify-center">
        <TagIcon class="w-7 h-7 text-muted-foreground" />
      </div>
      <p class="text-foreground font-medium text-sm">No tags</p>
      <p class="text-muted-foreground text-xs">태그를 추가하여 메모를 분류하세요.</p>
    </div>
  {:else}
    <div class="bg-card border border-border rounded-lg overflow-hidden">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-border">
            <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground">색상</th>
            <th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground">이름</th>
            <th class="px-4 py-3 text-center text-xs font-medium text-muted-foreground">메모</th>
            <th class="px-4 py-3 text-right text-xs font-medium text-muted-foreground">액션</th>
          </tr>
        </thead>
        <tbody>
          {#each tags as tag}
            <tr
              class="border-b border-border last:border-0 hover:bg-muted/30 transition-colors
                {tag.note_count === 0 ? 'opacity-50' : ''}"
            >
              <td class="px-4 py-3">
                {#if editId === tag.id}
                  <input type="color" bind:value={editColor} class="h-7 w-7 rounded cursor-pointer border-0" />
                {:else}
                  <span class="inline-block w-4 h-4 rounded-full" style="background-color: {tag.color}"></span>
                {/if}
              </td>
              <td class="px-4 py-3">
                {#if editId === tag.id}
                  <input
                    type="text"
                    bind:value={editName}
                    class="w-full px-2 py-1 text-sm rounded border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-ring/30"
                  />
                {:else}
                  <span class="font-medium text-foreground">{tag.name}</span>
                {/if}
              </td>
              <td class="px-4 py-3 text-center text-muted-foreground text-xs">{tag.note_count}</td>
              <td class="px-4 py-3">
                <div class="flex gap-1 justify-end">
                  {#if editId === tag.id}
                    <button
                      onclick={saveEdit}
                      disabled={saving}
                      class="p-1 rounded hover:bg-muted text-success disabled:opacity-50 transition-colors"
                      title="저장"
                    ><Check class="w-4 h-4" /></button>
                    <button
                      onclick={() => (editId = null)}
                      class="p-1 rounded hover:bg-muted text-muted-foreground transition-colors"
                      title="취소"
                    ><X class="w-4 h-4" /></button>
                  {:else if deleteConfirmId === tag.id}
                    <button
                      onclick={() => confirmDelete(tag.id)}
                      class="px-2 py-0.5 text-xs rounded bg-destructive/20 text-destructive border border-destructive/30 hover:bg-destructive/30"
                    >Delete</button>
                    <button
                      onclick={() => (deleteConfirmId = null)}
                      class="px-2 py-0.5 text-xs rounded bg-muted text-muted-foreground"
                    >Cancel</button>
                  {:else}
                    <button
                      onclick={() => startEdit(tag)}
                      class="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                      title="수정"
                    ><Pencil class="w-4 h-4" /></button>
                    <button
                      onclick={() => requestDelete(tag.id)}
                      class="p-1 rounded hover:bg-muted text-muted-foreground hover:text-destructive transition-colors"
                      title="삭제"
                    ><Trash2 class="w-4 h-4" /></button>
                  {/if}
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
