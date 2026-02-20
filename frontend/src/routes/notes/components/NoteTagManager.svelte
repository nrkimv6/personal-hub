<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { TagDef } from '$lib/api/notes';

  let tags = $state<TagDef[]>([]);
  let loading = $state(false);
  let error = $state('');

  // 새 태그 폼
  let newName = $state('');
  let newColor = $state('#6b7280');
  let creating = $state(false);

  // 편집 상태
  let editId = $state<number | null>(null);
  let editName = $state('');
  let editColor = $state('');
  let saving = $state(false);

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

  async function deleteTag(id: number, name: string) {
    if (!confirm(`"${name}" 태그를 삭제하시겠습니까?\n이 태그가 달린 메모에서도 제거됩니다.`)) return;
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
  <!-- 새 태그 추가 -->
  <div class="mb-6 p-4 bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700">
    <h3 class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">새 태그 추가</h3>
    <div class="flex gap-2">
      <input
        type="text"
        bind:value={newName}
        placeholder="태그 이름..."
        class="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <input
        type="color"
        bind:value={newColor}
        class="h-10 w-10 rounded cursor-pointer border-0"
        title="색상 선택"
      />
      <button
        onclick={createTag}
        disabled={creating || !newName.trim()}
        class="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
      >추가</button>
    </div>
  </div>

  <!-- 태그 목록 -->
  {#if loading}
    <div class="text-center text-gray-400 py-8">불러오는 중...</div>
  {:else if error}
    <div class="text-center text-red-400 py-8">{error}</div>
  {:else if tags.length === 0}
    <div class="text-center text-gray-400 py-8">태그가 없습니다.</div>
  {:else}
    <table class="w-full text-sm">
      <thead>
        <tr class="text-left text-xs text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
          <th class="pb-2 font-medium">색상</th>
          <th class="pb-2 font-medium">이름</th>
          <th class="pb-2 font-medium text-center">메모 수</th>
          <th class="pb-2 font-medium text-right">액션</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-100 dark:divide-gray-700">
        {#each tags as tag}
          <tr class="py-2">
            <td class="py-3 pr-3">
              {#if editId === tag.id}
                <input type="color" bind:value={editColor} class="h-7 w-7 rounded cursor-pointer border-0" />
              {:else}
                <span class="inline-block w-5 h-5 rounded-full" style="background-color: {tag.color}"></span>
              {/if}
            </td>
            <td class="py-3 pr-3">
              {#if editId === tag.id}
                <input
                  type="text"
                  bind:value={editName}
                  class="w-full px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700"
                />
              {:else}
                <span class="font-medium text-gray-900 dark:text-white">{tag.name}</span>
              {/if}
            </td>
            <td class="py-3 text-center text-gray-500">{tag.note_count}</td>
            <td class="py-3 text-right">
              {#if editId === tag.id}
                <div class="flex gap-1 justify-end">
                  <button onclick={saveEdit} disabled={saving} class="px-3 py-1 text-xs rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">저장</button>
                  <button onclick={() => (editId = null)} class="px-3 py-1 text-xs rounded border hover:bg-gray-50 dark:hover:bg-gray-700">취소</button>
                </div>
              {:else}
                <div class="flex gap-1 justify-end">
                  <button onclick={() => startEdit(tag)} class="px-3 py-1 text-xs rounded border hover:bg-gray-50 dark:hover:bg-gray-700">수정</button>
                  <button onclick={() => deleteTag(tag.id, tag.name)} class="px-3 py-1 text-xs rounded border text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20">삭제</button>
                </div>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>
