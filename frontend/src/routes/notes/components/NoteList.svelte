<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { Note, TagDef } from '$lib/api/notes';
  import { Search, X, ChevronLeft, ChevronRight, FileText, CheckSquare, Trash2, Archive, Tag, Star, ArrowUpDown } from 'lucide-svelte';
  import { flattenNavEntries } from '$lib/navigation';
  import NoteCard from './NoteCard.svelte';
  import NoteDetailModal from './NoteDetailModal.svelte';
  import NoteFormModal from './NoteFormModal.svelte';
  import BulkTagModal from './BulkTagModal.svelte';

  let notes = $state<Note[]>([]);
  let tags = $state<TagDef[]>([]);
  let total = $state(0);
  let pages = $state(1);
  let loading = $state(false);
  let error = $state('');

  let search = $state('');
  let selectedTags = $state<string[]>([]);
  let tagMode = $state<'or' | 'and'>('or');
  let dateFrom = $state('');
  let dateTo = $state('');
  let sortBy = $state('created_at');
  let sortOrder = $state<'asc' | 'desc'>('desc');
  let page = $state(1);
  let starredFilter = $state<boolean | undefined>(undefined);
  let linkedMenuFilter = $state<string | undefined>(undefined);

  const menuItems = flattenNavEntries();

  let openNote = $state<Note | null>(null);
  let editNote = $state<Note | null>(null);

  // 선택 모드
  let selectMode = $state(false);
  let selectedIds = $state<Set<number>>(new Set());
  let showBulkTagModal = $state(false);

  let searchTimer: ReturnType<typeof setTimeout>;

  function getTodayRange(): { from: string; to: string } {
    const d = new Date();
    const date = d.toISOString().split('T')[0];
    return { from: `${date}T00:00:00`, to: `${date}T23:59:59` };
  }

  function getWeekRange(): { from: string; to: string } {
    const d = new Date();
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1);
    const mon = new Date(d.setDate(diff));
    const sun = new Date(mon);
    sun.setDate(mon.getDate() + 6);
    return {
      from: `${mon.toISOString().split('T')[0]}T00:00:00`,
      to: `${sun.toISOString().split('T')[0]}T23:59:59`,
    };
  }

  function getMonthRange(): { from: string; to: string } {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const lastDay = new Date(year, d.getMonth() + 1, 0).getDate();
    return {
      from: `${year}-${month}-01T00:00:00`,
      to: `${year}-${month}-${lastDay}T23:59:59`,
    };
  }

  function setDatePreset(preset: 'today' | 'week' | 'month' | 'all') {
    if (preset === 'all') {
      dateFrom = '';
      dateTo = '';
    } else if (preset === 'today') {
      const r = getTodayRange();
      dateFrom = r.from;
      dateTo = r.to;
    } else if (preset === 'week') {
      const r = getWeekRange();
      dateFrom = r.from;
      dateTo = r.to;
    } else if (preset === 'month') {
      const r = getMonthRange();
      dateFrom = r.from;
      dateTo = r.to;
    }
    page = 1;
    load();
  }

  async function load(silent = false) {
    if (!silent) loading = true;
    error = '';
    try {
      const [res, tagRes] = await Promise.all([
        notesApi.list({
          search: search || undefined,
          tags: selectedTags.length ? selectedTags.join(',') : undefined,
          tag_mode: tagMode,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          sort: sortBy,
          order: sortOrder,
          page,
          starred: starredFilter,
          linked_menu_id: linkedMenuFilter,
        }),
        notesApi.listTags(),
      ]);
      notes = res.items;
      total = res.total;
      pages = res.pages;
      tags = tagRes;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function onSearchInput() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { page = 1; load(); }, 400);
  }

  function toggleTagSelection(tagName: string) {
    if (selectedTags.includes(tagName)) {
      selectedTags = selectedTags.filter(t => t !== tagName);
    } else {
      selectedTags = [...selectedTags, tagName];
    }
    page = 1;
    load();
  }

  function clearTags() {
    selectedTags = [];
    page = 1;
    load();
  }

  function toggleSortOrder() {
    sortOrder = sortOrder === 'desc' ? 'asc' : 'desc';
    page = 1;
    load();
  }

  /** @deprecated 하위호환 — 단일 태그 선택 */
  function selectTag(tagName: string) {
    selectedTags = tagName ? [tagName] : [];
    page = 1;
    load();
  }

  function toggleSelectMode() {
    selectMode = !selectMode;
    selectedIds = new Set();
  }

  function toggleSelect(id: number) {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selectedIds = next;
  }

  function selectAll() {
    selectedIds = new Set(notes.map(n => n.id));
  }

  function clearSelection() {
    selectedIds = new Set();
  }

  async function handleBulkDelete() {
    if (!selectedIds.size) return;
    if (!confirm(`선택한 ${selectedIds.size}개 메모를 삭제하시겠습니까?`)) return;
    await notesApi.bulkDelete([...selectedIds]);
    selectedIds = new Set();
    load();
  }

  async function handleBulkArchive() {
    if (!selectedIds.size) return;
    await notesApi.bulkArchive([...selectedIds]);
    selectedIds = new Set();
    load();
  }

  async function handleBulkStar() {
    if (!selectedIds.size) return;
    await notesApi.bulkStar([...selectedIds], true);
    selectedIds = new Set();
    load();
  }

  export function refresh() {
    return load(true);
  }

  onMount(load);
</script>

<div class="flex flex-col h-full overflow-hidden">
  <!-- 필터 바 -->
  <div class="flex flex-col gap-3 p-4 border-b border-border">
    <!-- 검색 input + 선택 모드 토글 -->
    <div class="flex gap-2">
      <div class="relative flex-1">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <input
          type="search"
          bind:value={search}
          oninput={onSearchInput}
          placeholder="제목·내용 검색..."
          class="w-full pl-9 pr-8 py-2 text-sm rounded-lg border border-border bg-card text-foreground
            focus:outline-none focus:ring-2 focus:ring-ring/30"
        />
        {#if search}
          <button
            onclick={() => { search = ''; page = 1; load(); }}
            class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          ><X class="w-3.5 h-3.5" /></button>
        {/if}
      </div>
      <!-- 선택 모드 토글 버튼 -->
      <button
        onclick={toggleSelectMode}
        class="flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg border transition-colors
          {selectMode
            ? 'bg-primary text-primary-foreground border-primary'
            : 'bg-card text-muted-foreground border-border hover:border-primary/50'}"
      >
        <CheckSquare class="w-3.5 h-3.5" />
        선택
      </button>
    </div>

    <!-- 선택 모드 상태 바 -->
    {#if selectMode}
      <div class="flex items-center gap-2 text-xs text-muted-foreground">
        <button onclick={selectAll} class="hover:text-foreground transition-colors">전체 선택</button>
        <span>·</span>
        <button onclick={clearSelection} class="hover:text-foreground transition-colors">선택 해제</button>
        <span class="ml-auto font-medium text-foreground">{selectedIds.size}개 선택됨</span>
      </div>
    {/if}

    <!-- 날짜 범위 필터 -->
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-xs text-muted-foreground shrink-0">날짜:</span>
      {#each [['오늘', 'today'], ['이번 주', 'week'], ['이번 달', 'month'], ['전체', 'all']] as [label, preset]}
        <button
          onclick={() => setDatePreset(preset as any)}
          class="px-2.5 py-1 text-xs rounded-md border transition-colors
            {(preset === 'all' && !dateFrom && !dateTo) ||
             (preset !== 'all' && dateFrom)
              ? 'bg-primary/10 text-primary border-primary/30'
              : 'bg-card text-muted-foreground border-border hover:border-primary/30'}"
        >{label}</button>
      {/each}
      <input
        type="date"
        bind:value={dateFrom}
        onchange={() => { page = 1; load(); }}
        class="text-xs px-2 py-1 rounded-md border border-border bg-card text-foreground
          focus:outline-none focus:ring-1 focus:ring-ring/30"
      />
      <span class="text-xs text-muted-foreground">~</span>
      <input
        type="date"
        bind:value={dateTo}
        onchange={() => { page = 1; load(); }}
        class="text-xs px-2 py-1 rounded-md border border-border bg-card text-foreground
          focus:outline-none focus:ring-1 focus:ring-ring/30"
      />
    </div>

    <!-- 태그 pill 필터 + AND/OR 토글 -->
    <div class="flex flex-wrap gap-1.5 items-center">
      <button
        onclick={clearTags}
        class="px-3 py-1.5 text-xs rounded-full border transition-colors
          {selectedTags.length === 0
            ? 'bg-primary text-primary-foreground border-primary'
            : 'bg-card text-muted-foreground border-border hover:border-primary/50'}"
      >All</button>
      {#each tags as tag}
        <button
          onclick={() => toggleTagSelection(tag.name)}
          class="flex items-center gap-1 px-3 py-1.5 text-xs rounded-full border transition-colors
            {selectedTags.includes(tag.name)
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-card text-muted-foreground border-border hover:border-primary/50'}"
        >
          <span
            class="w-2 h-2 rounded-full shrink-0"
            style="background-color: {tag.color}"
          ></span>
          {tag.name}
        </button>
      {/each}
      {#if selectedTags.length > 1}
        <button
          onclick={() => { tagMode = tagMode === 'or' ? 'and' : 'or'; page = 1; load(); }}
          class="ml-1 px-2.5 py-1 text-xs rounded-md border font-medium transition-colors
            bg-amber-500/10 text-amber-700 border-amber-300 hover:bg-amber-500/20"
        >{tagMode.toUpperCase()}</button>
      {/if}
    </div>

    <!-- 별표 필터 -->
    <div class="flex items-center gap-2">
      <button
        onclick={() => { starredFilter = starredFilter === true ? undefined : true; page = 1; load(); }}
        class="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-colors
          {starredFilter === true
            ? 'bg-yellow-100 text-yellow-700 border-yellow-300 dark:bg-yellow-900/20 dark:text-yellow-400 dark:border-yellow-700'
            : 'bg-card text-muted-foreground border-border hover:border-yellow-400/50'}"
      >
        <Star class="w-3.5 h-3.5 {starredFilter === true ? 'fill-current' : ''}" />
        즐겨찾기
      </button>
    </div>

    <!-- 메뉴 필터 -->
    <div class="flex items-center gap-2">
      <span class="text-xs text-muted-foreground shrink-0">메뉴:</span>
      <select
        bind:value={linkedMenuFilter}
        onchange={() => { page = 1; load(); }}
        class="text-xs px-2 py-1 rounded-md border border-border bg-card text-foreground
          focus:outline-none focus:ring-1 focus:ring-ring/30"
      >
        <option value={undefined}>전체</option>
        {#each (() => {
          const groups: { category: string | null; items: typeof menuItems }[] = [];
          let currentCat: string | null = undefined as unknown as string | null;
          for (const item of menuItems) {
            const cat = item.category ?? null;
            if (cat !== currentCat) { groups.push({ category: cat, items: [item] }); currentCat = cat; }
            else { groups[groups.length - 1].items.push(item); }
          }
          return groups;
        })() as group}
          {#if group.category}
            <optgroup label={group.category}>
              {#each group.items as item}
                <option value={item.id}>{item.icon} {item.label}</option>
              {/each}
            </optgroup>
          {:else}
            {#each group.items as item}
              <option value={item.id}>{item.icon} {item.label}</option>
            {/each}
          {/if}
        {/each}
      </select>
      {#if linkedMenuFilter}
        <button
          onclick={() => { linkedMenuFilter = undefined; page = 1; load(); }}
          class="text-xs text-muted-foreground hover:text-foreground transition-colors"
        ><X class="w-3.5 h-3.5" /></button>
      {/if}
    </div>

    <!-- 정렬 옵션 -->
    <div class="flex items-center gap-2">
      <span class="text-xs text-muted-foreground">정렬:</span>
      <select
        bind:value={sortBy}
        onchange={() => { page = 1; load(); }}
        class="text-xs px-2 py-1 rounded-md border border-border bg-card text-foreground
          focus:outline-none focus:ring-1 focus:ring-ring/30"
      >
        <option value="created_at">생성일</option>
        <option value="updated_at">수정일</option>
        <option value="title">제목</option>
      </select>
      <button
        onclick={toggleSortOrder}
        class="flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-border
          bg-card text-muted-foreground hover:border-primary/50 transition-colors"
      >
        <ArrowUpDown class="w-3 h-3" />
        {sortOrder === 'desc' ? '내림차순' : '오름차순'}
      </button>
    </div>
  </div>

  <!-- 목록 -->
  <div class="flex-1 overflow-y-auto p-4">
    {#if loading}
      <!-- skeleton shimmer -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {#each Array(6) as _}
          <div class="rounded-lg border border-border p-4 space-y-2">
            <div class="animate-skeleton-shimmer h-4 w-3/4 rounded"></div>
            <div class="animate-skeleton-shimmer h-3 w-full rounded"></div>
            <div class="animate-skeleton-shimmer h-3 w-5/6 rounded"></div>
            <div class="animate-skeleton-shimmer h-3 w-1/4 rounded mt-4"></div>
          </div>
        {/each}
      </div>
    {:else if error}
      <div class="flex flex-col items-center justify-center py-16 gap-3">
        <X class="w-10 h-10 text-destructive/50" />
        <p class="text-destructive text-sm">{error}</p>
        <button
          onclick={load}
          class="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary-hover transition-colors"
        >다시 시도</button>
      </div>
    {:else if notes.length === 0}
      <div class="flex flex-col items-center justify-center py-16 gap-3">
        <div class="w-14 h-14 bg-muted rounded-2xl flex items-center justify-center">
          <FileText class="w-7 h-7 text-muted-foreground" />
        </div>
        <p class="text-foreground font-medium text-sm">No notes yet</p>
        <p class="text-muted-foreground text-xs">
          {selectedTags.length > 0 ? `선택한 태그에 해당하는 메모가 없습니다.` : '새 메모를 추가해보세요.'}
        </p>
      </div>
    {:else}
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {#each notes as note (note.id)}
          <div class="animate-fade-in">
            <NoteCard
              {note}
              {selectMode}
              selected={selectedIds.has(note.id)}
              onToggleSelect={toggleSelect}
              onOpen={(n) => (openNote = n)}
              onEdit={(n) => (editNote = n)}
              onRefresh={load}
            />
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- 페이지네이션 -->
  {#if pages > 1}
    <div class="flex items-center justify-center gap-2 p-3 border-t border-border">
      <button
        onclick={() => { page--; load(); }}
        disabled={page <= 1}
        class="p-2 rounded-lg hover:bg-muted disabled:opacity-40 transition-colors"
      ><ChevronLeft class="w-4 h-4" /></button>
      <span class="text-xs text-muted-foreground">{page} / {pages} (총 {total}개)</span>
      <button
        onclick={() => { page++; load(); }}
        disabled={page >= pages}
        class="p-2 rounded-lg hover:bg-muted disabled:opacity-40 transition-colors"
      ><ChevronRight class="w-4 h-4" /></button>
    </div>
  {/if}

  <!-- 하단 고정 벌크 액션 바 -->
  {#if selectMode && selectedIds.size > 0}
    <div class="fixed bottom-6 left-1/2 -translate-x-1/2 z-50
      flex items-center gap-2 px-4 py-3 rounded-2xl shadow-lg
      bg-card border border-border">
      <button
        onclick={handleBulkDelete}
        class="flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg
          bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors"
      >
        <Trash2 class="w-3.5 h-3.5" />
        삭제
      </button>
      <button
        onclick={handleBulkArchive}
        class="flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg
          bg-orange-500/10 text-orange-600 hover:bg-orange-500/20 transition-colors"
      >
        <Archive class="w-3.5 h-3.5" />
        아카이브
      </button>
      <button
        onclick={() => (showBulkTagModal = true)}
        class="flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg
          bg-blue-500/10 text-blue-600 hover:bg-blue-500/20 transition-colors"
      >
        <Tag class="w-3.5 h-3.5" />
        태그
      </button>
      <button
        onclick={handleBulkStar}
        class="flex items-center gap-1.5 px-3 py-2 text-xs rounded-lg
          bg-yellow-500/10 text-yellow-600 hover:bg-yellow-500/20 transition-colors"
      >
        <Star class="w-3.5 h-3.5" />
        별표
      </button>
    </div>
  {/if}
</div>

<!-- 상세 모달 -->
{#if openNote}
  <NoteDetailModal
    note={openNote}
    onClose={() => (openNote = null)}
    onEdit={(n) => { openNote = null; editNote = n; }}
    onRefresh={load}
  />
{/if}

<!-- 수정 모달 -->
{#if editNote}
  <NoteFormModal
    mode="edit"
    note={editNote}
    onSave={() => { editNote = null; load(); }}
    onClose={() => (editNote = null)}
  />
{/if}

<!-- 벌크 태그 모달 -->
{#if showBulkTagModal}
  <BulkTagModal
    noteIds={[...selectedIds]}
    onApply={() => { showBulkTagModal = false; selectedIds = new Set(); load(); }}
    onClose={() => (showBulkTagModal = false)}
  />
{/if}
