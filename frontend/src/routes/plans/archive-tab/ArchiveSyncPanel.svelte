<script lang="ts">
  import type { ImportArchivedResult, SyncResult } from '$lib/api/plan-records';

  let {
    importLoading,
    importResult,
    syncLoading,
    syncResult,
    onImport,
    onSync,
  }: {
    importLoading: boolean;
    importResult: ImportArchivedResult | null;
    syncLoading: boolean;
    syncResult: SyncResult | null;
    onImport: () => void;
    onSync: () => void;
  } = $props();
</script>

<div class="mb-3 flex flex-wrap items-center gap-2">
  <button
    class="px-3 py-1 text-xs rounded bg-emerald-100 hover:bg-emerald-200 text-emerald-700 dark:bg-emerald-900 dark:hover:bg-emerald-800 dark:text-emerald-200 disabled:opacity-50"
    onclick={onSync}
    disabled={syncLoading}
    title="등록된 경로를 스캔해 파일↔DB를 동기화합니다. archive 경로 파일에 archived_at을 자동 설정합니다."
  >{syncLoading ? '동기화 중...' : '파일/DB 동기화'}</button>
  <button
    class="px-3 py-1 text-xs rounded bg-green-100 hover:bg-green-200 text-green-700 dark:bg-green-900 dark:hover:bg-green-800 dark:text-green-200 disabled:opacity-50"
    onclick={onImport}
    disabled={importLoading}
    title="archive 경로의 파일을 DB에 일괄 등록합니다 (DB 이관). 이미 등록된 레코드는 category만 업데이트합니다."
  >{importLoading ? '이관 중...' : 'DB 이관'}</button>
  <span class="text-xs text-muted-foreground">
    <a href="/scheduler/plan-archive" class="text-primary underline hover:no-underline">Plan Archive 운영 →</a>
  </span>
  {#if importResult}
    <span class="text-xs text-muted-foreground">이관: {importResult.created}생성 {importResult.updated}갱신 {importResult.skipped}스킵</span>
  {/if}
  {#if syncResult}
    <span class="text-xs text-muted-foreground">sync: archive {syncResult.archive_created}생성 {syncResult.archive_normalized}정규화</span>
  {/if}
</div>
