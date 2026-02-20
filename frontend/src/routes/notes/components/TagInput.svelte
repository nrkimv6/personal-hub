<script lang="ts">
  import { notesApi } from '$lib/api/notes';
  import type { TagDef } from '$lib/api/notes';

  interface Props {
    selectedTagIds: number[];
    allTags: TagDef[];
    onChange: (ids: number[]) => void;
    onTagsRefresh: () => void;
  }

  let { selectedTagIds, allTags, onChange, onTagsRefresh }: Props = $props();

  let query = $state('');
  let showDropdown = $state(false);
  let creating = $state(false);

  let filteredTags = $derived(
    allTags.filter(
      (t) =>
        t.name.toLowerCase().includes(query.toLowerCase()) &&
        !selectedTagIds.includes(t.id)
    )
  );

  let selectedTags = $derived(allTags.filter((t) => selectedTagIds.includes(t.id)));

  function selectTag(tag: TagDef) {
    onChange([...selectedTagIds, tag.id]);
    query = '';
    showDropdown = false;
  }

  function removeTag(id: number) {
    onChange(selectedTagIds.filter((i) => i !== id));
  }

  async function createAndSelect() {
    if (!query.trim()) return;
    creating = true;
    try {
      const newTag = await notesApi.createTag({ name: query.trim() });
      onTagsRefresh();
      onChange([...selectedTagIds, newTag.id]);
      query = '';
      showDropdown = false;
    } catch (e: any) {
      alert(e.message);
    } finally {
      creating = false;
    }
  }
</script>

<div class="relative">
  <!-- 선택된 태그 배지 -->
  {#if selectedTags.length > 0}
    <div class="flex flex-wrap gap-1 mb-2">
      {#each selectedTags as tag}
        <span class="flex items-center gap-1 px-2 py-0.5 text-xs rounded-full text-white" style="background-color: {tag.color}">
          {tag.name}
          <button onclick={() => removeTag(tag.id)} class="hover:opacity-70 leading-none">✕</button>
        </span>
      {/each}
    </div>
  {/if}

  <!-- 입력 -->
  <input
    type="text"
    bind:value={query}
    onfocus={() => (showDropdown = true)}
    onblur={() => setTimeout(() => (showDropdown = false), 150)}
    oninput={() => (showDropdown = true)}
    placeholder="태그 검색 또는 새로 만들기..."
    class="w-full px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
  />

  <!-- 드롭다운 -->
  {#if showDropdown}
    <div class="absolute z-10 w-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg max-h-40 overflow-y-auto">
      {#each filteredTags as tag}
        <button
          onclick={() => selectTag(tag)}
          class="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-700 text-left"
        >
          <span class="w-3 h-3 rounded-full" style="background-color: {tag.color}"></span>
          {tag.name}
        </button>
      {/each}
      {#if query.trim() && !allTags.some((t) => t.name === query.trim())}
        <button
          onclick={createAndSelect}
          disabled={creating}
          class="w-full px-3 py-2 text-sm text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 text-left"
        >
          + "{query.trim()}" 태그 만들기
        </button>
      {/if}
      {#if filteredTags.length === 0 && !query.trim()}
        <p class="px-3 py-2 text-xs text-gray-400">사용 가능한 태그 없음</p>
      {/if}
    </div>
  {/if}
</div>
