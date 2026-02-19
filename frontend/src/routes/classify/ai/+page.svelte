<script lang="ts">
  import { Brain, Play, Square, AlertCircle, ChevronDown, ChevronUp, Sparkles } from 'lucide-svelte';

  let engine = $state<'claude' | 'gemini'>('claude');
  let cliPath = $state('claude');
  let modelName = $state('claude-opus-4-5');
  let workers = $state(2);
  let timeout = $state(30);
  let skipClassified = $state(true);
  let applyRules = $state(true);
  let running = $state(false);
  let progress = $state(0);
  let errorsExpanded = $state(false);
  let showSummary = $state(false);
  let targetImages = $state<'unclassified' | 'all' | 'failed'>('unclassified');

  let intervalId: ReturnType<typeof setInterval> | null = null;

  const mockResults = [
    { file: 'IMG_0001.jpg', category: 'outdoor/travel', confidence: 0.94, thumbnail: '/api/ic/files/1/thumbnail' },
    { file: 'IMG_0002.jpg', category: 'indoor/home', confidence: 0.87, thumbnail: '/api/ic/files/2/thumbnail' },
    { file: 'IMG_0003.jpg', category: 'personal/family', confidence: 0.91, thumbnail: '/api/ic/files/3/thumbnail' },
  ];

  const mockErrors = [
    { file: 'IMG_9999.jpg', error: 'Timeout after 30s' },
  ];

  const categorySummary = [
    { label: 'outdoor / travel', count: 45, pct: 38 },
    { label: 'indoor / home', count: 32, pct: 27 },
    { label: 'personal / family', count: 28, pct: 23 },
    { label: 'other', count: 14, pct: 12 },
  ];

  async function startClassification() {
    running = true;
    progress = 0;
    showSummary = false;

    intervalId = setInterval(() => {
      progress = Math.min(progress + Math.random() * 4 + 1, 100);
      if (progress >= 100) {
        if (intervalId) clearInterval(intervalId);
        intervalId = null;
        running = false;
        showSummary = true;
      }
    }, 200);
  }

  function stopClassification() {
    if (intervalId) {
      clearInterval(intervalId);
      intervalId = null;
    }
    running = false;
  }

  function getConfidenceColor(conf: number): string {
    if (conf >= 0.9) return 'text-green-600 dark:text-green-400';
    if (conf >= 0.7) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-destructive';
  }
</script>

<div class="space-y-6">
  <!-- Header -->
  <div class="flex items-start gap-3">
    <div class="flex size-10 items-center justify-center rounded-xl bg-primary/10">
      <Brain class="size-5 text-primary" />
    </div>
    <div>
      <h1 class="text-2xl font-bold text-foreground">AI Classification</h1>
      <p class="text-sm text-muted-foreground">Automatically classify images using AI models</p>
    </div>
  </div>

  <!-- Settings Grid -->
  <div class="grid gap-6 lg:grid-cols-2">
    <!-- AI Engine Settings -->
    <div class="rounded-xl border border-border bg-card p-4 space-y-4">
      <h2 class="text-sm font-semibold text-foreground">AI Engine Settings</h2>

      <!-- Engine Selector -->
      <div class="space-y-1.5">
        <p class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Engine</p>
        <div class="flex rounded-lg border border-border bg-muted p-0.5">
          <button
            onclick={() => { engine = 'claude'; modelName = 'claude-opus-4-5'; cliPath = 'claude'; }}
            class="flex flex-1 items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-all {engine === 'claude'
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'}"
          >
            <Sparkles class="size-3.5" />
            Claude
          </button>
          <button
            onclick={() => { engine = 'gemini'; modelName = 'gemini-1.5-pro'; cliPath = 'gemini'; }}
            class="flex flex-1 items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-all {engine === 'gemini'
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'}"
          >
            <Brain class="size-3.5" />
            Gemini
          </button>
        </div>
      </div>

      <!-- CLI Path -->
      <div class="space-y-1.5">
        <label for="cli-path" class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">CLI Path</label>
        <input
          id="cli-path"
          type="text"
          bind:value={cliPath}
          class="h-9 w-full rounded-md border border-border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          placeholder="claude"
        />
      </div>

      <!-- Model Name -->
      <div class="space-y-1.5">
        <label for="model-name" class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Model Name</label>
        <input
          id="model-name"
          type="text"
          bind:value={modelName}
          class="h-9 w-full rounded-md border border-border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          placeholder="claude-opus-4-5"
        />
      </div>

      <!-- Workers & Timeout -->
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label for="workers-count" class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Workers</label>
          <input
            id="workers-count"
            type="number"
            bind:value={workers}
            min="1"
            max="8"
            class="h-9 w-full rounded-md border border-border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <div class="space-y-1.5">
          <label for="timeout-sec" class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Timeout (s)</label>
          <input
            id="timeout-sec"
            type="number"
            bind:value={timeout}
            min="5"
            max="300"
            class="h-9 w-full rounded-md border border-border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>
    </div>

    <!-- Batch Processing -->
    <div class="rounded-xl border border-border bg-card p-4 space-y-4">
      <h2 class="text-sm font-semibold text-foreground">Batch Processing</h2>

      <!-- Target Images -->
      <div class="space-y-1.5">
        <label class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Target Images</label>
        <div class="flex gap-2">
          {#each [{ key: 'unclassified', label: 'Unclassified' }, { key: 'all', label: 'All' }, { key: 'failed', label: 'Failed' }] as opt}
            <button
              onclick={() => (targetImages = opt.key as typeof targetImages)}
              class="flex-1 rounded-md border px-2 py-1.5 text-xs font-medium transition-all {targetImages === opt.key
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border bg-secondary/30 text-muted-foreground hover:text-foreground'}"
            >
              {opt.label}
            </button>
          {/each}
        </div>
      </div>

      <!-- Skip already classified -->
      <div class="flex items-center justify-between rounded-lg border border-border bg-secondary/50 px-3 py-2.5">
        <div>
          <div class="text-xs font-medium text-foreground">Skip already classified</div>
          <div class="text-[10px] text-muted-foreground">Don't re-process images with existing classification</div>
        </div>
        <input
          type="checkbox"
          bind:checked={skipClassified}
          class="h-4 w-4 rounded accent-primary"
        />
      </div>

      <!-- Apply rules after AI -->
      <div class="flex items-center justify-between rounded-lg border border-border bg-secondary/50 px-3 py-2.5">
        <div>
          <div class="text-xs font-medium text-foreground">Apply rules after AI</div>
          <div class="text-[10px] text-muted-foreground">Run classification rules on AI results</div>
        </div>
        <input
          type="checkbox"
          bind:checked={applyRules}
          class="h-4 w-4 rounded accent-primary"
        />
      </div>
    </div>
  </div>

  <!-- Execution Card -->
  <div class="rounded-xl border border-border bg-card p-4 space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-sm font-semibold text-foreground">Execution</h2>
      {#if running}
        <span class="flex items-center gap-1.5 text-xs text-primary">
          <span class="relative flex size-2">
            <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75"></span>
            <span class="relative inline-flex size-2 rounded-full bg-primary"></span>
          </span>
          Running...
        </span>
      {/if}
    </div>

    <!-- Start / Stop Button -->
    <div class="flex gap-2">
      {#if !running}
        <button
          onclick={startClassification}
          class="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Play class="size-4" />
          Start Classification
        </button>
      {:else}
        <button
          onclick={stopClassification}
          class="flex items-center gap-2 rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 transition-colors"
        >
          <Square class="size-4" />
          Stop
        </button>
      {/if}
    </div>

    <!-- Progress Bar -->
    {#if running}
      <div class="space-y-1.5">
        <div class="flex items-center justify-between text-xs text-muted-foreground">
          <span>Processing...</span>
          <span>{Math.round(progress)}%</span>
        </div>
        <div class="h-2.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            class="h-full rounded-full bg-primary transition-all duration-300"
            style="width: {progress}%"
          ></div>
        </div>
      </div>
    {/if}

    <!-- Live Results -->
    {#if mockResults.length > 0}
      <div>
        <p class="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Live Results</p>
        <div class="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border">
          {#each mockResults as result}
            <div class="flex items-center gap-3 px-3 py-2">
              <div class="size-8 flex-shrink-0 overflow-hidden rounded bg-muted">
                <img
                  src={result.thumbnail}
                  alt={result.file}
                  class="h-full w-full object-cover"
                  onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              </div>
              <div class="min-w-0 flex-1">
                <p class="truncate text-[11px] font-medium text-foreground">{result.file}</p>
                <p class="text-[10px] text-muted-foreground">{result.category}</p>
              </div>
              <span class="flex-shrink-0 text-xs font-semibold {getConfidenceColor(result.confidence)}">
                {Math.round(result.confidence * 100)}%
              </span>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Errors -->
    {#if mockErrors.length > 0}
      <div class="rounded-lg border border-destructive/30 bg-destructive/5">
        <button
          onclick={() => (errorsExpanded = !errorsExpanded)}
          class="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-destructive"
        >
          <span class="flex items-center gap-2">
            <AlertCircle class="size-3.5" />
            {mockErrors.length} error{mockErrors.length > 1 ? 's' : ''}
          </span>
          {#if errorsExpanded}
            <ChevronUp class="size-3.5" />
          {:else}
            <ChevronDown class="size-3.5" />
          {/if}
        </button>
        {#if errorsExpanded}
          <div class="border-t border-destructive/20 px-3 py-2 space-y-1">
            {#each mockErrors as err}
              <div class="flex items-center justify-between text-[10px]">
                <span class="font-medium text-foreground">{err.file}</span>
                <span class="text-destructive">{err.error}</span>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Summary -->
    {#if showSummary}
      <div class="rounded-lg border border-border bg-secondary/30 p-3 space-y-3">
        <p class="text-xs font-semibold text-foreground">Classification Complete</p>
        <div class="space-y-2">
          {#each categorySummary as cat}
            <div>
              <div class="flex items-center justify-between text-[10px]">
                <span class="text-foreground">{cat.label}</span>
                <span class="font-medium text-muted-foreground">{cat.count} ({cat.pct}%)</span>
              </div>
              <div class="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-primary"
                  style="width: {cat.pct}%"
                ></div>
              </div>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  </div>
</div>
