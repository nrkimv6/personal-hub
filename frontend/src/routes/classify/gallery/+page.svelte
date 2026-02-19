<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchWithTimeout } from '$lib/api/client';
  import { Search, Tag, Trash2, Check, X, Loader2 } from 'lucide-svelte';

  // 이미지 타입
  interface GalleryImage {
    id: number;
    filename: string;
    status: string;
    category: string | null;
    size: number;
    thumbnail: string;
  }

  let images = $state<GalleryImage[]>([]);
  let totalCount = $state(0);
  let loadingImages = $state(true);
  let loadError = $state<string | null>(null);
  let loadingMore = $state(false);

  let selectedImages = $state<number[]>([]);
  let searchQuery = $state('');
  let statusFilter = $state('all');
  let sortBy = $state('date');
  let detailImage = $state<number | null>(null);

  const PAGE_SIZE = 24;
  let currentOffset = $state(0);
  let hasMore = $state(false);

  const statusFilters = ['All', 'Pending', 'Mapped', 'AI Classified', 'Approved'];

  // API 필터 → 쿼리 파라미터 변환
  function buildQuery(offset: number): string {
    const params = new URLSearchParams();
    params.set('limit', String(PAGE_SIZE));
    params.set('skip', String(offset));
    if (statusFilter !== 'all') {
      params.set('status', statusFilter.toLowerCase().replace(' ', '_'));
    }
    if (sortBy === 'date') params.set('order_by', 'extracted_date');
    else if (sortBy === 'name') params.set('order_by', 'id');
    else if (sortBy === 'size') params.set('order_by', 'id');
    params.set('order_dir', 'desc');
    return params.toString();
  }

  // API 응답 → GalleryImage 변환
  function mapFile(f: any): GalleryImage {
    const parts = (f.file_path || '').replace(/\\/g, '/').split('/');
    const filename = parts[parts.length - 1] || `file_${f.id}`;
    return {
      id: f.id,
      filename,
      status: f.status || 'pending',
      category: f.final_category_id ? String(f.final_category_id) : null,
      size: f.file_size || 0,
      thumbnail: `/api/ic/files/${f.id}/thumbnail`,
    };
  }

  async function loadImages(reset = false) {
    if (reset) {
      loadingImages = true;
      loadError = null;
      currentOffset = 0;
      images = [];
    } else {
      loadingMore = true;
    }

    try {
      const offset = reset ? 0 : currentOffset;
      const qs = buildQuery(offset);
      const res = await fetchWithTimeout(`/api/ic/files?${qs}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const newImages = (data.files ?? []).map(mapFile);
      if (reset) {
        images = newImages;
      } else {
        images = [...images, ...newImages];
      }
      currentOffset = offset + newImages.length;
      hasMore = newImages.length === PAGE_SIZE;
      totalCount = data.total ?? images.length;
    } catch (err: any) {
      loadError = err.message;
    } finally {
      loadingImages = false;
      loadingMore = false;
    }
  }

  // 필터/정렬 변경 시 재로드
  $effect(() => {
    // statusFilter, sortBy 의존
    void statusFilter;
    void sortBy;
    loadImages(true);
  });

  onMount(() => {
    // $effect가 초기에도 실행되므로 별도 호출 불필요
  });

  // 클라이언트 사이드 검색 (이름 필터)
  let filteredImages = $derived(
    searchQuery
      ? images.filter(img => img.filename.toLowerCase().includes(searchQuery.toLowerCase()))
      : images
  );

  let detailData = $derived(
    detailImage !== null ? images.find(img => img.id === detailImage) ?? null : null
  );

  function toggleSelect(id: number) {
    if (selectedImages.includes(id)) {
      selectedImages = selectedImages.filter(x => x !== id);
    } else {
      selectedImages = [...selectedImages, id];
    }
  }

  function openDetail(id: number) {
    detailImage = id;
  }

  function getStatusBadgeClass(status: string): string {
    switch (status) {
      case 'approved': return 'bg-green-500/20 text-green-600 dark:text-green-400';
      case 'folder_mapped':
      case 'mapped': return 'bg-primary/20 text-primary';
      case 'ai_classified': return 'bg-yellow-500/20 text-yellow-700 dark:text-yellow-400';
      case 'moved': return 'bg-violet-500/20 text-violet-700';
      default: return 'bg-muted text-muted-foreground';
    }
  }

  function formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    if (bytes > 0) return `${(bytes / 1024).toFixed(0)} KB`;
    return '—';
  }
</script>

<div class="space-y-4">
  <!-- Header -->
  <div class="flex items-center gap-3">
    <h1 class="text-2xl font-bold text-foreground">Gallery</h1>
    <span class="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
      {filteredImages.length}{hasMore ? '+' : ''} images
    </span>
  </div>

  <!-- Filter Bar -->
  <div class="rounded-xl border border-border bg-card p-3">
    <div class="flex flex-wrap items-center gap-3">
      <!-- Search -->
      <div class="relative min-w-[180px] flex-1">
        <Search class="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          placeholder="Search images..."
          bind:value={searchQuery}
          class="h-8 w-full rounded-md border border-border bg-background pl-8 pr-3 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      <!-- Status Filter Buttons -->
      <div class="flex items-center gap-0.5 rounded-md border border-border bg-muted p-0.5">
        {#each statusFilters as filter}
          {@const filterKey = filter === 'All' ? 'all' : filter.toLowerCase().replace(' ', '_')}
          <button
            onclick={() => (statusFilter = filterKey)}
            class="rounded px-2.5 py-1 text-[11px] font-medium transition-all {statusFilter === filterKey
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'}"
          >
            {filter}
          </button>
        {/each}
      </div>

      <!-- Sort -->
      <select
        bind:value={sortBy}
        class="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      >
        <option value="date">Date</option>
        <option value="name">Name</option>
        <option value="size">Size</option>
      </select>
    </div>
  </div>

  <!-- Bulk Action Bar -->
  {#if selectedImages.length > 0}
    <div class="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
      <span class="text-xs font-medium text-primary">{selectedImages.length} images selected</span>
      <div class="mx-1 h-4 w-px bg-border"></div>
      <button class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent">
        <Tag class="size-3" />
        Assign Category
      </button>
      <button class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent">
        <Check class="size-3" />
        Approve
      </button>
      <button class="flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/10">
        <Trash2 class="size-3" />
        Delete
      </button>
      <button
        onclick={() => (selectedImages = [])}
        class="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <X class="size-3" />
        Deselect All
      </button>
    </div>
  {/if}

  <!-- Loading State -->
  {#if loadingImages}
    <div class="flex items-center justify-center py-16 text-sm text-muted-foreground gap-2">
      <Loader2 class="size-4 animate-spin" />
      Loading images...
    </div>
  {:else if loadError}
    <div class="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
      <p class="text-sm font-medium text-destructive mb-2">Failed to load images</p>
      <p class="text-xs text-muted-foreground mb-3">{loadError}</p>
      <button
        onclick={() => loadImages(true)}
        class="inline-flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90"
      >
        Retry
      </button>
    </div>
  {:else if filteredImages.length === 0}
    <!-- Empty State -->
    <div class="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div class="rounded-xl bg-muted p-4">
        <Search class="size-8 text-muted-foreground" />
      </div>
      <p class="text-sm font-medium text-foreground">이미지가 없습니다</p>
      <p class="text-xs text-muted-foreground">
        {statusFilter !== 'all' ? '다른 필터를 선택해보세요.' : '먼저 스캔을 실행해주세요.'}
      </p>
    </div>
  {:else}
    <!-- Image Grid -->
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
      {#each filteredImages as img (img.id)}
        {@const isSelected = selectedImages.includes(img.id)}
        <div
          role="button"
          tabindex="0"
          class="group relative aspect-square cursor-pointer overflow-hidden rounded-lg border bg-muted transition-all {isSelected
            ? 'ring-2 ring-primary'
            : 'hover:ring-1 hover:ring-primary/50'}"
          onclick={() => openDetail(img.id)}
          onkeydown={(e) => e.key === 'Enter' && openDetail(img.id)}
        >
          <!-- Thumbnail -->
          <img
            src={img.thumbnail}
            alt={img.filename}
            class="absolute inset-0 h-full w-full object-cover transition-transform group-hover:scale-105"
            onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
          />

          <!-- Fallback -->
          <div class="flex h-full w-full items-center justify-center text-[10px] text-muted-foreground/50">
            {img.id}
          </div>

          <!-- Select Checkbox -->
          <button
            class="absolute left-1.5 top-1.5 z-10 flex size-5 items-center justify-center rounded border border-white/50 bg-black/40 opacity-0 transition-all group-hover:opacity-100 {isSelected
              ? '!opacity-100 border-primary bg-primary text-white'
              : ''}"
            onclick={(e) => { e.stopPropagation(); toggleSelect(img.id); }}
            aria-label="Select image"
          >
            {#if isSelected}
              <Check class="size-3" />
            {/if}
          </button>

          <!-- Bottom Gradient Overlay -->
          <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent p-1.5 pt-5">
            <p class="truncate text-[10px] font-medium text-white">{img.filename}</p>
            <span class="mt-0.5 inline-block rounded px-1 py-0.5 text-[9px] font-medium capitalize {getStatusBadgeClass(img.status)}">
              {img.status.replace(/_/g, ' ')}
            </span>
          </div>
        </div>
      {/each}
    </div>

    <!-- Load More -->
    {#if hasMore}
      <div class="flex justify-center pt-2">
        <button
          onclick={() => loadImages(false)}
          disabled={loadingMore}
          class="inline-flex items-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-50 transition-colors"
        >
          {#if loadingMore}
            <Loader2 class="size-4 animate-spin" />
            Loading...
          {:else}
            Load More
          {/if}
        </button>
      </div>
    {/if}
  {/if}
</div>

<!-- Detail Sheet -->
{#if detailImage !== null && detailData !== null}
  <!-- Backdrop -->
  <div
    role="button"
    tabindex="-1"
    class="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
    onclick={() => (detailImage = null)}
    onkeydown={(e) => e.key === 'Escape' && (detailImage = null)}
  ></div>

  <!-- Side Panel -->
  <div class="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-border bg-card shadow-2xl">
    <!-- Header -->
    <div class="flex items-center justify-between border-b border-border px-4 py-3">
      <h2 class="text-sm font-semibold text-foreground">Image Detail</h2>
      <button
        onclick={() => (detailImage = null)}
        class="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <X class="size-4" />
      </button>
    </div>

    <div class="flex-1 space-y-4 overflow-y-auto p-4">
      <!-- Preview -->
      <div class="relative aspect-video w-full overflow-hidden rounded-lg bg-muted">
        <img
          src={detailData.thumbnail}
          alt={detailData.filename}
          class="h-full w-full object-contain"
          onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
        />
        <div class="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground/50">
          {detailData.filename}
        </div>
      </div>

      <!-- Metadata -->
      <div class="rounded-lg border border-border bg-secondary/30 p-3">
        <h3 class="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Metadata</h3>
        <div class="grid grid-cols-2 gap-2">
          <div>
            <p class="text-[10px] text-muted-foreground">Filename</p>
            <p class="truncate text-xs font-medium text-foreground">{detailData.filename}</p>
          </div>
          <div>
            <p class="text-[10px] text-muted-foreground">Size</p>
            <p class="text-xs font-medium text-foreground">{formatSize(detailData.size)}</p>
          </div>
          <div>
            <p class="text-[10px] text-muted-foreground">Status</p>
            <span class="inline-block rounded px-1.5 py-0.5 text-[10px] font-medium capitalize {getStatusBadgeClass(detailData.status)}">
              {detailData.status.replace(/_/g, ' ')}
            </span>
          </div>
          <div>
            <p class="text-[10px] text-muted-foreground">Category ID</p>
            <p class="text-xs font-medium text-foreground">{detailData.category ?? '—'}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <div class="flex items-center gap-2 border-t border-border p-3">
      <button class="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90">
        <Check class="size-3" />
        Approve
      </button>
      <button
        onclick={() => (detailImage = null)}
        class="rounded-md border border-border bg-card px-3 py-2 text-xs font-medium text-foreground hover:bg-accent"
      >
        Close
      </button>
    </div>
  </div>
{/if}
