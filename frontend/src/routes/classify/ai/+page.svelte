<svelte:head><title>AI 분류 — Image Classifier</title></svelte:head>

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { fetchWithTimeout } from '$lib/api/client';
  import { Brain, Play, Square, AlertCircle, ChevronDown, ChevronUp, Sparkles, Loader2 } from 'lucide-svelte';

  // 분류 설정
  let engine = $state<'claude' | 'gemini'>('claude');
  let cliPath = $state('claude');
  let modelName = $state('claude-opus-4-5');
  let workers = $state(2);
  let timeout = $state(30);
  let skipClassified = $state(true);
  let applyRules = $state(true);
  let targetImages = $state<'unclassified' | 'all' | 'failed'>('unclassified');

  // 실행 상태
  let running = $state(false);
  let progress = $state(0);
  let processedCount = $state(0);
  let totalCount = $state(0);
  let currentFile = $state<string | null>(null);
  let errorsExpanded = $state(false);
  let showSummary = $state(false);
  let startError = $state<string | null>(null);

  // 결과 / 에러
  interface ClassifyResult {
    file: string;
    category: string;
    confidence: number;
    thumbnail: string;
  }

  interface ClassifyError {
    file: string;
    error: string;
  }

  let results = $state<ClassifyResult[]>([]);
  let errors = $state<ClassifyError[]>([]);

  let pollingId: ReturnType<typeof setInterval> | null = null;

  // 분류 시작
  async function startClassification() {
    startError = null;
    running = true;
    progress = 0;
    processedCount = 0;
    totalCount = 0;
    currentFile = null;
    showSummary = false;
    results = [];
    errors = [];

    try {
      const model = engine === 'claude' ? 'claude_cli' : 'gemini_cli';
      const res = await fetchWithTimeout('/api/ic/classify/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, batch_size: workers }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }

      // 폴링 시작
      startPolling();
    } catch (err: any) {
      startError = err.message;
      running = false;
    }
  }

  // 분류 중지
  async function stopClassification() {
    try {
      await fetchWithTimeout('/api/ic/classify/stop', { method: 'POST' });
    } catch {
      // 무시
    }
    stopPolling();
    running = false;
  }

  // 상태 폴링 (2초 간격)
  function startPolling() {
    if (pollingId) clearInterval(pollingId);
    pollingId = setInterval(pollStatus, 2000);
  }

  function stopPolling() {
    if (pollingId) {
      clearInterval(pollingId);
      pollingId = null;
    }
  }

  async function pollStatus() {
    try {
      const res = await fetchWithTimeout('/api/ic/classify/status');
      if (!res.ok) return;
      const data = await res.json();

      running = data.running ?? false;
      totalCount = data.total ?? 0;
      processedCount = data.processed ?? 0;
      currentFile = data.current_file ?? null;
      progress = totalCount > 0 ? Math.round((processedCount / totalCount) * 100) : 0;

      // 분류 완료
      if (!running && totalCount > 0) {
        stopPolling();
        showSummary = true;
        await loadResults();
      }
    } catch {
      // 폴링 실패 무시
    }
  }

  // 분류 완료 후 결과 로드
  async function loadResults() {
    try {
      const res = await fetchWithTimeout('/api/ic/files?status=ai_classified&limit=50&order_by=id&order_dir=desc');
      if (!res.ok) return;
      const data = await res.json();
      results = (data.files ?? []).slice(0, 20).map((f: any) => {
        const parts = (f.file_path || '').replace(/\\/g, '/').split('/');
        return {
          file: parts[parts.length - 1] || `file_${f.id}`,
          category: f.final_category_id ? `category ${f.final_category_id}` : '—',
          confidence: f.ai_confidence ?? 0,
          thumbnail: `/api/ic/files/${f.id}/thumbnail`,
        };
      });
    } catch {
      // 무시
    }

    // 에러 파일 로드
    try {
      const errRes = await fetchWithTimeout('/api/ic/files?status=error&limit=20');
      if (errRes.ok) {
        const errData = await errRes.json();
        errors = (errData.files ?? []).map((f: any) => {
          const parts = (f.file_path || '').replace(/\\/g, '/').split('/');
          return {
            file: parts[parts.length - 1] || `file_${f.id}`,
            error: '분류 실패',
          };
        });
      }
    } catch {
      // 무시
    }
  }

  // 초기 상태 확인 (이미 실행 중일 수 있음)
  async function checkInitialStatus() {
    try {
      const res = await fetchWithTimeout('/api/ic/classify/status');
      if (!res.ok) return;
      const data = await res.json();
      if (data.running) {
        running = true;
        totalCount = data.total ?? 0;
        processedCount = data.processed ?? 0;
        progress = totalCount > 0 ? Math.round((processedCount / totalCount) * 100) : 0;
        startPolling();
      }
    } catch {
      // 무시
    }
  }

  onMount(() => {
    checkInitialStatus();
  });

  onDestroy(() => {
    stopPolling();
  });

  function getConfidenceColor(conf: number): string {
    if (conf >= 0.9) return 'text-green-600 dark:text-green-400';
    if (conf >= 0.7) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-destructive';
  }
</script>

<div class="space-y-6">
  <!-- 헤더 -->
  <div class="flex items-center justify-between">
    <div>
      <div class="flex items-center gap-2">
        <Brain class="size-5 text-primary" />
        <h1 class="text-2xl font-bold tracking-tight">AI 분류</h1>
      </div>
      <p class="mt-1 text-sm text-muted-foreground">AI 모델로 이미지를 자동 분류합니다</p>
    </div>
  </div>

  <!-- Settings Grid -->
  <div class="grid gap-6 lg:grid-cols-2">
    <!-- AI Engine Settings -->
    <div class="rounded-xl border border-border bg-card p-4 space-y-4">
      <h2 class="text-sm font-semibold text-foreground">AI 엔진 설정</h2>

      <!-- Engine Selector -->
      <div class="space-y-1.5">
        <p class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">엔진</p>
        <div class="flex rounded-lg border border-border bg-muted p-0.5">
          <button
            onclick={() => { engine = 'claude'; modelName = 'claude-opus-4-5'; cliPath = 'claude'; }}
            disabled={running}
            class="flex flex-1 items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-all disabled:opacity-50 {engine === 'claude'
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'}"
          >
            <Sparkles class="size-3.5" />
            Claude
          </button>
          <button
            onclick={() => { engine = 'gemini'; modelName = 'gemini-1.5-pro'; cliPath = 'gemini'; }}
            disabled={running}
            class="flex flex-1 items-center justify-center gap-2 rounded-md py-1.5 text-xs font-medium transition-all disabled:opacity-50 {engine === 'gemini'
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
          disabled={running}
          class="h-9 w-full rounded-md border border-border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
          placeholder="claude"
        />
      </div>

      <!-- Model Name -->
      <div class="space-y-1.5">
        <label for="model-name" class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">모델 이름</label>
        <input
          id="model-name"
          type="text"
          bind:value={modelName}
          disabled={running}
          class="h-9 w-full rounded-md border border-border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
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
            disabled={running}
            class="h-9 w-full rounded-md border border-border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
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
            disabled={running}
            class="h-9 w-full rounded-md border border-border bg-background px-3 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
          />
        </div>
      </div>
    </div>

    <!-- Batch Processing -->
    <div class="rounded-xl border border-border bg-card p-4 space-y-4">
      <h2 class="text-sm font-semibold text-foreground">배치 처리</h2>

      <!-- Target Images -->
      <div class="space-y-1.5">
        <label class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">대상 이미지</label>
        <div class="flex gap-2">
          {#each [{ key: 'unclassified', label: '미분류' }, { key: 'all', label: '전체' }, { key: 'failed', label: '실패' }] as opt}
            <button
              onclick={() => (targetImages = opt.key as typeof targetImages)}
              disabled={running}
              class="flex-1 rounded-md border px-2 py-1.5 text-xs font-medium transition-all disabled:opacity-50 {targetImages === opt.key
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
          <div class="text-xs font-medium text-foreground">이미 분류된 이미지 제외</div>
          <div class="text-[10px] text-muted-foreground">기존 분류가 있는 이미지를 재처리하지 않습니다</div>
        </div>
        <input
          type="checkbox"
          bind:checked={skipClassified}
          disabled={running}
          class="h-4 w-4 rounded accent-primary disabled:opacity-50"
        />
      </div>

      <!-- Apply rules after AI -->
      <div class="flex items-center justify-between rounded-lg border border-border bg-secondary/50 px-3 py-2.5">
        <div>
          <div class="text-xs font-medium text-foreground">AI 후 규칙 적용</div>
          <div class="text-[10px] text-muted-foreground">AI 결과에 분류 규칙을 실행합니다</div>
        </div>
        <input
          type="checkbox"
          bind:checked={applyRules}
          disabled={running}
          class="h-4 w-4 rounded accent-primary disabled:opacity-50"
        />
      </div>
    </div>
  </div>

  <!-- Execution Card -->
  <div class="rounded-xl border border-border bg-card p-4 space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-sm font-semibold text-foreground">실행</h2>
      {#if running}
        <span class="flex items-center gap-1.5 text-xs text-primary">
          <span class="relative flex size-2">
            <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75"></span>
            <span class="relative inline-flex size-2 rounded-full bg-primary"></span>
          </span>
          실행 중... ({processedCount}/{totalCount})
        </span>
      {/if}
    </div>

    <!-- Start Error -->
    {#if startError}
      <div class="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-xs text-destructive">
        {startError}
      </div>
    {/if}

    <!-- Start / Stop Button -->
    <div class="flex gap-2">
      {#if !running}
        <button
          onclick={startClassification}
          class="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Play class="size-4" />
          분류 시작
        </button>
      {:else}
        <button
          onclick={stopClassification}
          class="flex items-center gap-2 rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 transition-colors"
        >
          <Square class="size-4" />
          중지
        </button>
      {/if}
    </div>

    <!-- Progress Bar -->
    {#if running}
      <div class="space-y-1.5">
        <div class="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {currentFile
              ? (currentFile.split('/').pop()?.split('\\').pop() ?? '처리 중...')
              : '처리 중...'}
          </span>
          <span>{progress}%</span>
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
    {#if results.length > 0}
      <div>
        <p class="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">최근 분류 결과</p>
        <div class="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border">
          {#each results as result (result.file)}
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
              {#if result.confidence > 0}
                <span class="flex-shrink-0 text-xs font-semibold {getConfidenceColor(result.confidence)}">
                  {Math.round(result.confidence * 100)}%
                </span>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Errors -->
    {#if errors.length > 0}
      <div class="rounded-lg border border-destructive/30 bg-destructive/5">
        <button
          onclick={() => (errorsExpanded = !errorsExpanded)}
          class="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-destructive"
        >
          <span class="flex items-center gap-2">
            <AlertCircle class="size-3.5" />
            오류 {errors.length}건
          </span>
          {#if errorsExpanded}
            <ChevronUp class="size-3.5" />
          {:else}
            <ChevronDown class="size-3.5" />
          {/if}
        </button>
        {#if errorsExpanded}
          <div class="border-t border-destructive/20 px-3 py-2 space-y-1">
            {#each errors as err}
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
    {#if showSummary && !running}
      <div class="rounded-lg border border-border bg-secondary/30 p-3 space-y-2">
        <p class="text-xs font-semibold text-foreground">
          분류 완료 — {processedCount}/{totalCount}개 처리됨
        </p>
        <p class="text-xs text-muted-foreground">결과를 갤러리에서 확인하세요.</p>
      </div>
    {/if}
  </div>
</div>
