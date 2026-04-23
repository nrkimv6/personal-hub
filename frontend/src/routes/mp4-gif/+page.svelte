<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { AlertTriangle, Download, Loader2, Upload } from 'lucide-svelte';

  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import {
    createTask,
    getHealth,
    getResultUrl,
    getTask,
    type Mp4GifHealthResponse,
    type Mp4GifTaskStatus,
    type Mp4GifTaskStatusResponse
  } from '$lib/api/mp4-gif';
  import { toast } from '$lib/stores/toast';

  let selectedFile: File | null = null;
  let fps = 10;
  let tasks: Mp4GifTaskStatusResponse[] = [];
  let loading = false;
  let errorMessage = '';
  let health: Mp4GifHealthResponse | null = null;
  let dragActive = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  // trim preview state (기존 let 패턴 유지 — runes 미사용)
  let videoSrc: string | null = null;
  let videoEl: HTMLVideoElement | undefined = undefined;
  let startSeconds: number | null = null;
  let endSeconds: number | null = null;
  let trimErrorMessage: string = '';

  function formatTrimSeconds(seconds: number): string {
    return `${seconds.toFixed(1)}s`;
  }

  const STATUS_LABELS: Record<Mp4GifTaskStatus, string> = {
    queued: '대기 중',
    running: '변환 중',
    completed: '완료',
    failed: '실패'
  };

  const STATUS_CLASSES: Record<Mp4GifTaskStatus, string> = {
    queued: 'bg-muted text-muted-foreground',
    running: 'bg-primary/10 text-primary',
    completed: 'bg-success/10 text-success',
    failed: 'bg-destructive/10 text-destructive'
  };

  const hasActiveTasks = () => tasks.some((task) => task.status === 'queued' || task.status === 'running');

  function parseError(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }

  async function refreshHealth() {
    try {
      health = await getHealth();
    } catch (error) {
      health = null;
      errorMessage = parseError(error);
    }
  }

  async function pollTasks() {
    const activeTaskIds = tasks
      .filter((task) => task.status === 'queued' || task.status === 'running')
      .map((task) => task.task_id);
    if (activeTaskIds.length === 0) {
      clearPolling();
      return;
    }

    try {
      const updatedTasks = await Promise.all(activeTaskIds.map((taskId) => getTask(taskId)));
      for (const updatedTask of updatedTasks) {
        tasks = tasks.map((task) => (task.task_id === updatedTask.task_id ? updatedTask : task));
      }
      if (!hasActiveTasks()) {
        clearPolling();
      }
    } catch (error) {
      clearPolling();
      errorMessage = parseError(error);
      toast.error(errorMessage);
    }
  }

  function startPolling() {
    if (pollTimer !== null) return;
    pollTimer = setInterval(() => {
      void pollTasks();
    }, 1000);
  }

  function clearPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function setSelectedFile(file: File | null) {
    if (videoSrc) {
      URL.revokeObjectURL(videoSrc);
      videoSrc = null;
    }
    selectedFile = file;
    errorMessage = '';
    startSeconds = null;
    endSeconds = null;
    trimErrorMessage = '';
    if (file) {
      videoSrc = URL.createObjectURL(file);
    }
  }

  function handleFileInput(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    setSelectedFile(target.files?.[0] ?? null);
  }

  function handleDragOver(event: DragEvent) {
    event.preventDefault();
    dragActive = true;
  }

  function handleDragLeave(event: DragEvent) {
    event.preventDefault();
    dragActive = false;
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    dragActive = false;
    const file = event.dataTransfer?.files?.[0] ?? null;
    setSelectedFile(file);
  }

  function previewUrl(task: Mp4GifTaskStatusResponse): string {
    const stamp = task.completed_at ?? task.task_id;
    return `${getResultUrl(task.task_id)}?t=${encodeURIComponent(stamp)}`;
  }

  async function handleSubmit() {
    if (!selectedFile || loading) return;
    if (fps < 1) {
      toast.warning('fps는 1 이상이어야 합니다.');
      return;
    }

    loading = true;
    errorMessage = '';
    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('fps', String(fps));
      if (startSeconds !== null) {
        formData.append('start_seconds', startSeconds.toFixed(3));
        if (endSeconds !== null && endSeconds > startSeconds && !trimErrorMessage) {
          formData.append('duration_seconds', (endSeconds - startSeconds).toFixed(3));
        }
      }

      const accepted = await createTask(formData);
      const initialTask = await getTask(accepted.task_id);
      tasks = [initialTask, ...tasks.filter((task) => task.task_id !== initialTask.task_id)];
      startPolling();
      toast.success('변환 작업을 시작했습니다.');
      setSelectedFile(null);
    } catch (error) {
      errorMessage = parseError(error);
      toast.error(errorMessage);
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void refreshHealth();
  });

  onDestroy(() => {
    clearPolling();
    if (videoSrc) {
      URL.revokeObjectURL(videoSrc);
    }
  });
</script>

<svelte:head>
  <title>MP4 → GIF | 모니터링 시스템</title>
</svelte:head>

<div class="flex h-full flex-col gap-6 p-6">
  <PageHeader
    title="MP4 → GIF"
    subtitle="MP4 파일을 업로드하고 비동기 변환 상태를 확인한 뒤 GIF를 내려받습니다."
  />

  {#if health && !health.ffmpeg_ok}
    <div class="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
      <div class="flex items-start gap-2">
        <AlertTriangle size={18} class="mt-0.5 shrink-0" />
        <div>
          <div class="font-semibold">ffmpeg를 찾지 못했습니다</div>
          <div>{health.error_message}</div>
        </div>
      </div>
    </div>
  {/if}

  {#if errorMessage}
    <div class="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
      {errorMessage}
    </div>
  {/if}

  <section class="grid gap-6 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
    <div class="rounded-2xl border border-border bg-card p-5 shadow-sm">
      <h2 class="text-base font-semibold">업로드</h2>
      <p class="mt-1 text-sm text-muted-foreground">
        기본 변환 옵션은 `fps`만 제공하며, 결과는 작업 완료 후 목록에 추가됩니다.
      </p>

      <div
        class={`mt-4 rounded-2xl border-2 border-dashed p-6 text-center transition ${
          dragActive ? 'border-primary bg-primary/5' : 'border-border'
        }`}
        ondragover={handleDragOver}
        ondragleave={handleDragLeave}
        ondrop={handleDrop}
      >
        <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Upload size={22} />
        </div>
        <div class="mt-3 text-sm font-medium">MP4 파일을 끌어놓거나 직접 선택하세요</div>
        <div class="mt-1 text-xs text-muted-foreground">
          최대 {health?.max_upload_mb ?? 100}MB, 결과는 GIF로 생성됩니다.
        </div>

        <label class="mt-4 inline-flex cursor-pointer items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">
          파일 선택
          <input class="hidden" type="file" accept=".mp4,video/mp4" onchange={handleFileInput} />
        </label>

        {#if selectedFile}
          <div class="mt-3 rounded-lg bg-muted px-3 py-2 text-left text-sm">
            <div class="font-medium">{selectedFile.name}</div>
            <div class="text-xs text-muted-foreground">
              {(selectedFile.size / 1024 / 1024).toFixed(1)} MB
            </div>
          </div>
        {/if}
      </div>

      {#if videoSrc}
        <div class="mt-4">
          <video
            bind:this={videoEl}
            src={videoSrc}
            controls
            class="w-full rounded-xl border border-border bg-black"
            style="max-height:220px"
          ></video>

          <div class="mt-3 space-y-2">
            <!-- 시작점 -->
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted/40 disabled:opacity-40"
                onclick={() => {
                  if (!videoEl) return;
                  startSeconds = Math.round(videoEl.currentTime * 1000) / 1000;
                  endSeconds = null;
                  trimErrorMessage = '';
                }}
                disabled={!videoEl}
              >
                시작점 지정
              </button>
              {#if startSeconds !== null}
                <span class="text-xs text-muted-foreground">시작: {formatTrimSeconds(startSeconds)}</span>
                <button
                  type="button"
                  class="text-xs text-muted-foreground hover:text-destructive"
                  onclick={() => { startSeconds = null; endSeconds = null; trimErrorMessage = ''; }}
                >✕</button>
              {/if}
            </div>

            <!-- 종료점 -->
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted/40 disabled:opacity-40"
                onclick={() => {
                  if (!videoEl || startSeconds === null) return;
                  const t = Math.round(videoEl.currentTime * 1000) / 1000;
                  endSeconds = t;
                  trimErrorMessage = t <= startSeconds ? '종료점은 시작점보다 뒤여야 합니다.' : '';
                }}
                disabled={startSeconds === null || !videoEl}
              >
                종료점 지정
              </button>
              {#if endSeconds !== null}
                <span class="text-xs text-muted-foreground">종료: {formatTrimSeconds(endSeconds)}</span>
                <button
                  type="button"
                  class="text-xs text-muted-foreground hover:text-destructive"
                  onclick={() => { endSeconds = null; trimErrorMessage = ''; }}
                >✕</button>
              {/if}
            </div>

            {#if trimErrorMessage}
              <div class="text-xs text-destructive">{trimErrorMessage}</div>
            {/if}
          </div>
        </div>
      {/if}

      <div class="mt-4">
        <label class="mb-2 block text-sm font-medium" for="fps">FPS</label>
        <input
          id="fps"
          class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
          type="number"
          min="1"
          step="1"
          bind:value={fps}
        />
      </div>

      <button
        class="mt-4 inline-flex w-full items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
        onclick={handleSubmit}
        disabled={!selectedFile || loading || (health !== null && !health.ffmpeg_ok)}
      >
        {#if loading}
          <Loader2 size={16} class="mr-2 animate-spin" />
        {/if}
        변환 시작
      </button>
    </div>

    <div class="rounded-2xl border border-border bg-card p-5 shadow-sm">
      <div class="flex items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold">결과</h2>
          <p class="mt-1 text-sm text-muted-foreground">
            queued / running / completed / failed 상태를 자동으로 갱신합니다.
          </p>
        </div>
      </div>

      {#if tasks.length === 0}
        <div class="mt-4 rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
          아직 시작한 변환 작업이 없습니다.
        </div>
      {:else}
        <div class="mt-4 space-y-4">
          {#each tasks as task (task.task_id)}
            <article class="rounded-xl border border-border p-4">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="truncate text-sm font-semibold">{task.source_name}</div>
                  <div class="mt-1 text-xs text-muted-foreground">fps {task.fps}
                    {#if task.start_seconds != null && task.duration_seconds != null}
                      &nbsp;·&nbsp;구간: {formatTrimSeconds(task.start_seconds)} ~ {formatTrimSeconds(task.start_seconds + task.duration_seconds)}
                    {:else if task.start_seconds != null}
                      &nbsp;·&nbsp;시작: {formatTrimSeconds(task.start_seconds)} 이후
                    {/if}
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  {#if task.status === 'running'}
                    <Loader2 size={16} class="animate-spin text-primary" />
                  {/if}
                  <span class={`rounded-full px-3 py-1 text-xs font-medium ${STATUS_CLASSES[task.status]}`}>
                    {STATUS_LABELS[task.status]}
                  </span>
                </div>
              </div>

              <div class="mt-3 text-xs text-muted-foreground">
                생성 {new Date(task.created_at).toLocaleString('ko-KR')}
              </div>

              {#if task.status === 'completed'}
                <div class="mt-4 overflow-hidden rounded-xl border border-border bg-muted/20">
                  <img class="max-h-[360px] w-full object-contain" src={previewUrl(task)} alt={task.source_name} />
                </div>
                <div class="mt-4">
                  <a
                    class="inline-flex items-center rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted/40"
                    href={getResultUrl(task.task_id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Download size={16} class="mr-2" />
                    GIF 다운로드
                  </a>
                </div>
              {:else if task.status === 'failed'}
                <div class="mt-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  {task.error_message ?? '변환에 실패했습니다.'}
                </div>
              {/if}
            </article>
          {/each}
        </div>
      {/if}
    </div>
  </section>
</div>
