<script lang="ts">
  import { onMount } from 'svelte';
  import {
    slideScannerApi,
    type MobileSyncDevice,
    type MobileSyncStatusResponse
  } from '$lib/api/slide-scanner';
  import { toast } from '$lib/stores/toast';

  export let onsynccompleted: (() => void) | undefined = undefined;

  let devices: MobileSyncDevice[] = [];
  let syncStatus: MobileSyncStatusResponse | null = null;
  let loadingDevices = false;
  let loadingStatus = false;
  let runningSync = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let lastFinishedAt = '';
  let wasRunning = false;

  function toNumber(value: unknown): number | null {
    if (typeof value === 'number') return value;
    if (typeof value === 'string') {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  }

  function formatIsoDate(value: string | null | undefined): string {
    if (!value) return '-';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleString();
  }

  async function loadDevices() {
    loadingDevices = true;
    try {
      const response = await slideScannerApi.getMobileDevices();
      devices = response.devices;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '디바이스 조회 실패');
    } finally {
      loadingDevices = false;
    }
  }

  async function loadSyncStatus() {
    loadingStatus = true;
    try {
      const response = await slideScannerApi.getMobileSyncStatus();
      syncStatus = response;

      const nowRunning = Boolean(response.is_running);
      const nowFinishedAt = response.last_finished_at ?? '';
      if (wasRunning && !nowRunning && nowFinishedAt && nowFinishedAt !== lastFinishedAt) {
        lastFinishedAt = nowFinishedAt;
        onsynccompleted?.();
      }
      wasRunning = nowRunning;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '동기화 상태 조회 실패');
    } finally {
      loadingStatus = false;
    }
  }

  async function refreshPanel() {
    await Promise.all([loadDevices(), loadSyncStatus()]);
  }

  async function runSync() {
    runningSync = true;
    try {
      const response = await slideScannerApi.runMobileSync({ background: true });
      if (response.status === 'already_running') {
        toast.warning('이미 동기화가 실행 중입니다.');
      } else if (response.status === 'started') {
        toast.success('모바일 동기화를 시작했습니다.');
      } else {
        toast.info('동기화 요청을 보냈습니다.');
      }
      await loadSyncStatus();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '동기화 시작 실패');
    } finally {
      runningSync = false;
    }
  }

  $: lastResult = (syncStatus?.last_result ?? null) as Record<string, unknown> | null;
  $: insertedCount = toNumber(lastResult?.inserted) ?? 0;
  $: skippedCount = toNumber(lastResult?.skipped) ?? 0;
  $: failedCount = toNumber(lastResult?.failed) ?? 0;
  $: pulledCount = toNumber(lastResult?.pulled) ?? 0;

  onMount(() => {
    void refreshPanel();
    pollTimer = setInterval(() => {
      void loadSyncStatus();
    }, 3000);

    return () => {
      if (pollTimer) clearInterval(pollTimer);
    };
  });
</script>

<section class="rounded-xl border border-border bg-card p-4">
  <div class="flex flex-wrap items-center justify-between gap-2">
    <div>
      <h3 class="text-sm font-semibold">모바일 동기화</h3>
      <p class="mt-1 text-xs text-muted-foreground">
        연결된 안드로이드 기기의 이미지 파일을 PC inbox로 동기화합니다.
      </p>
    </div>
    <div class="flex items-center gap-2">
      <button
        type="button"
        class="btn btn-outline btn-sm"
        onclick={refreshPanel}
        disabled={loadingDevices || loadingStatus}
      >
        새로고침
      </button>
      <button
        type="button"
        class="btn btn-primary btn-sm"
        onclick={runSync}
        disabled={runningSync || Boolean(syncStatus?.is_running)}
      >
        {#if runningSync || syncStatus?.is_running}
          동기화 요청 중...
        {:else}
          동기화 실행
        {/if}
      </button>
    </div>
  </div>

  <div class="mt-3 grid gap-2 text-xs md:grid-cols-3">
    <div class="rounded-md border border-border bg-muted/30 px-3 py-2">
      <p class="text-muted-foreground">상태</p>
      <p class="font-medium">{syncStatus?.is_running ? 'RUNNING' : 'IDLE'}</p>
    </div>
    <div class="rounded-md border border-border bg-muted/30 px-3 py-2">
      <p class="text-muted-foreground">최근 시작</p>
      <p class="font-medium">{formatIsoDate(syncStatus?.last_started_at)}</p>
    </div>
    <div class="rounded-md border border-border bg-muted/30 px-3 py-2">
      <p class="text-muted-foreground">최근 완료</p>
      <p class="font-medium">{formatIsoDate(syncStatus?.last_finished_at)}</p>
    </div>
  </div>

  {#if lastResult}
    <div class="mt-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-xs">
      <p class="font-medium">최근 실행 결과</p>
      <p class="mt-1 text-muted-foreground">
        pulled {pulledCount} | inserted {insertedCount} | skipped {skippedCount} | failed {failedCount}
      </p>
    </div>
  {/if}

  {#if syncStatus?.last_error}
    <p class="mt-3 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
      {syncStatus.last_error}
    </p>
  {/if}

  <div class="mt-4 space-y-2">
    <div class="flex items-center justify-between">
      <h4 class="text-xs font-semibold">연결 기기</h4>
      <span class="text-xs text-muted-foreground">{devices.length}대</span>
    </div>

    {#if loadingDevices}
      <p class="text-xs text-muted-foreground">기기 상태 조회 중...</p>
    {:else if devices.length === 0}
      <p class="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        연결된 기기가 없습니다.
      </p>
    {:else}
      <div class="space-y-2">
        {#each devices as device}
          <div class="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 px-3 py-2 text-xs">
            <div>
              <p class="font-medium">
                {device.alias || device.model || 'Unknown Device'}
              </p>
              <p class="text-muted-foreground">{device.serial}</p>
            </div>
            <div class="text-right">
              <p class={device.is_online ? 'font-medium text-emerald-600' : 'font-medium text-amber-600'}>
                {device.is_online ? 'ONLINE' : device.state}
              </p>
              {#if device.model}
                <p class="text-muted-foreground">{device.model}</p>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</section>
