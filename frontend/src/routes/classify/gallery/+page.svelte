<script lang="ts">
  import { Search, Tag, Trash2, Check, X } from 'lucide-svelte';

  let selectedImages = $state<number[]>([]);
  let searchQuery = $state('');
  let statusFilter = $state('all');
  let sortBy = $state('date');
  let detailImage = $state<number | null>(null);

  // Mock 이미지 데이터
  const mockImages = Array.from({ length: 24 }, (_, i) => ({
    id: i + 1,
    filename: `IMG_${String(i + 1).padStart(4, '0')}.jpg`,
    status: ['pending', 'mapped', 'ai_classified', 'approved'][i % 4] as string,
    category: ['outdoor', 'indoor', 'personal', null][i % 4] as string | null,
    size: (i + 1) * 350000 + 500000,
    thumbnail: `/api/ic/files/${i + 1}/thumbnail`
  }));

  const statusFilters = ['All', 'Pending', 'Mapped', 'AI Classified', 'Approved'];

  const filteredImages = $derived(
    mockImages.filter(img => {
      if (searchQuery && !img.filename.toLowerCase().includes(searchQuery.toLowerCase())) return false;
      if (statusFilter !== 'all' && img.status !== statusFilter.toLowerCase().replace(' ', '_')) return false;
      return true;
    })
  );

  const detailData = $derived(
    detailImage !== null ? mockImages.find(img => img.id === detailImage) ?? null : null
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
      case 'mapped': return 'bg-primary/20 text-primary';
      case 'ai_classified': return 'bg-yellow-500/20 text-yellow-700 dark:text-yellow-400';
      default: return 'bg-muted text-muted-foreground';
    }
  }

  function formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
  }
</script>

<div class="space-y-4">
  <!-- Header -->
  <div class="flex items-center gap-3">
    <h1 class="text-2xl font-bold text-foreground">Gallery</h1>
    <span class="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
      {filteredImages.length} images
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
            {img.status.replace('_', ' ')}
          </span>
        </div>
      </div>
    {/each}
  </div>
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
              {detailData.status.replace('_', ' ')}
            </span>
          </div>
          <div>
            <p class="text-[10px] text-muted-foreground">Category</p>
            <p class="text-xs font-medium text-foreground">{detailData.category ?? '—'}</p>
          </div>
        </div>
      </div>

      <!-- AI Classification -->
      <div class="rounded-lg border border-border bg-secondary/30 p-3">
        <h3 class="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">AI Classification</h3>
        <div class="space-y-2">
          {#each [{ label: 'outdoor / travel', confidence: 0.87 }, { label: 'nature / landscape', confidence: 0.65 }, { label: 'personal / activity', confidence: 0.42 }] as item}
            <div>
              <div class="flex items-center justify-between text-[10px]">
                <span class="text-foreground">{item.label}</span>
                <span class="font-medium text-muted-foreground">{Math.round(item.confidence * 100)}%</span>
              </div>
              <div class="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-primary transition-all"
                  style="width: {item.confidence * 100}%"
                ></div>
              </div>
            </div>
          {/each}
        </div>
      </div>

      <!-- Tags -->
      <div class="rounded-lg border border-border bg-secondary/30 p-3">
        <h3 class="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Tags</h3>
        <div class="flex flex-wrap gap-1.5">
          {#each ['travel', 'outdoor', '2024', 'summer'] as tag}
            <span class="flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-[10px] font-medium text-foreground">
              {tag}
              <button class="text-muted-foreground hover:text-destructive" aria-label="Remove tag">
                <X class="size-2.5" />
              </button>
            </span>
          {/each}
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
