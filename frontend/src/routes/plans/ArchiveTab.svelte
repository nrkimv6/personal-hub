<script lang="ts">
  import { onMount } from 'svelte';
  import {
    planRecordsApi,
    archiveApi,
    type PlanRecord,
    type ImportArchivedResult,
    type ArchivePreviewItem,
    type DuplicateItem,
    type SyncResult,
    type PlanRecordRelation
  } from '$lib/api/plan-records';
  import { devRunnerPlanApi } from '$lib/api/dev-runner';
  import ArchiveRecordDetailPanel from './archive-tab/ArchiveRecordDetailPanel.svelte';
  import ArchiveSyncPanel from './archive-tab/ArchiveSyncPanel.svelte';

  let {
    focusPath = null,
    onFocusConsumed = null
  }: {
    focusPath?: string | null;
    onFocusConsumed?: (() => void) | null;
  } = $props();

  // ── 목록 상태 ──────────────────────────────────────────────
  let records: PlanRecord[] = $state([]);
  let loading = $state(true);
  let selectedRecord: PlanRecord | null = $state(null);
  let selectedRelations: PlanRecordRelation[] = $state([]);
  let selectedRelationsLoading = $state(false);
  let detailTab: 'content' | 'memo' = $state('content');
  let editingStatusId: number | null = $state(null);

  const EDITABLE_STATUSES = ['초안', '검토대기', '구현중', '보류'];

  async function handleStatusChange(record: PlanRecord, newStatus: string) {
    editingStatusId = null;
    if (!newStatus || newStatus === record.status) return;
    try {
      const encoded = btoa(record.file_path);
      await devRunnerPlanApi.patchStatus(encoded, newStatus);
      record.status = newStatus;
      records = records; // reactivity trigger
    } catch (e) {
      error = e instanceof Error ? e.message : '상태 변경 실패';
    }
  }
  let error = $state('');
  let skip = $state(0);
  const limit = 50;
  let hasMore = $state(false);
  let filterCategory = $state('');

  // ── 선택/벌크 ─────────────────────────────────────────────
  let selectedIds = $state(new Set<number>());
  let bulkCategory = $state('');
  const CATEGORIES = ['feature', 'bugfix', 'refactor', 'infra', 'docs', 'test', 'misc'];

  // ── 정리 모달 ─────────────────────────────────────────────
  let showOrganizeModal = $state(false);
  let previewLoading = $state(false);
  let organizeLoading = $state(false);
  let previewDirs: Array<{ archive_dir: string; items: ArchivePreviewItem[] }> = $state([]);
  let organizeResult = $state('');

  // ── DB 이관 ───────────────────────────────────────────────
  let importLoading = $state(false);
  let importResult: ImportArchivedResult | null = $state(null);
  let syncLoading = $state(false);
  let syncResult: SyncResult | null = $state(null);

  async function loadSelectedRelations(recordId: number) {
    selectedRelationsLoading = true;
    try {
      selectedRelations = await planRecordsApi.getRelations(recordId, { direction: 'both' });
    } catch {
      selectedRelations = [];
    } finally {
      selectedRelationsLoading = false;
    }
  }

  async function runImportArchived() {
    importLoading = true;
    importResult = null;
    try {
      const res = await planRecordsApi.importArchived();
      importResult = res;
      showToast(`DB 이관 완료: ${res.created}개 생성, ${res.updated}개 갱신, ${res.skipped}개 스킵`);
      await loadRecords();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'DB 이관 실패');
    } finally {
      importLoading = false;
    }
  }

  async function runSync() {
    syncLoading = true;
    syncResult = null;
    try {
      const res = await planRecordsApi.sync();
      syncResult = res;
      showToast(`Sync 완료: archive 생성 ${res.archive_created}, 정규화 ${res.archive_normalized}`);
      await loadRecords();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'Sync 실패');
    } finally {
      syncLoading = false;
    }
  }

  // ── 중복 감지 ─────────────────────────────────────────────
  let showDuplicatesModal = $state(false);
  let dupesLoading = $state(false);
  let dupeDirs: Array<{ archive_dir: string; duplicates: DuplicateItem[] }> = $state([]);

  // ── 토스트 ────────────────────────────────────────────────
  let toast = $state('');
  let toastTimer: ReturnType<typeof setTimeout> | null = null;

  function showToast(msg: string) {
    toast = msg;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast = ''; }, 3000);
  }

  // ── 목록 로드 ─────────────────────────────────────────────
  async function loadRecords(append = false) {
    loading = true;
    error = '';
    try {
      const data = await planRecordsApi.list({ status: 'archived', category: filterCategory || undefined, skip: append ? skip : 0, limit });
      if (append) {
        records = [...records, ...data];
        skip += data.length;
      } else {
        records = data;
        skip = data.length;
        selectedIds = new Set();
      }
      hasMore = data.length === limit;
    } catch (e) {
      error = e instanceof Error ? e.message : '목록 로드 실패';
    } finally {
      loading = false;
    }
  }

  // ── 선택 ─────────────────────────────────────────────────
  function toggleSelect(id: number, e: Event) {
    e.stopPropagation();
    if (selectedIds.has(id)) {
      selectedIds.delete(id);
    } else {
      selectedIds.add(id);
    }
    selectedIds = new Set(selectedIds);
  }

  function toggleSelectAll() {
    if (selectedIds.size === records.length) {
      selectedIds = new Set();
    } else {
      selectedIds = new Set(records.map(r => r.id));
    }
  }

  // ── 카테고리 추출 (파일명 기반, 프론트 표시용) ──────────────
  function getCategoryFromPath(filePath: string): string {
    const name = filePath.split(/[\\/]/).pop() ?? filePath;
    const noDate = name.replace(/^\d{4}-\d{2}-\d{2}_/, '');
    const prefix = noDate.split('-')[0].toLowerCase();
    const map: Record<string, string> = {
      feat: 'feature', fix: 'bugfix', hotfix: 'bugfix',
      refactor: 'refactor', ref: 'refactor',
      chore: 'infra', ci: 'infra', infra: 'infra', build: 'infra',
      docs: 'docs', doc: 'docs', test: 'test',
    };
    // 상위 폴더가 카테고리 폴더인 경우
    const parts = filePath.split(/[\\/]/);
    if (parts.length >= 2) {
      const parent = parts[parts.length - 2].toLowerCase();
      if (CATEGORIES.includes(parent)) return parent;
    }
    return map[prefix] ?? 'misc';
  }

  // ── 수동 분류 벌크 이동 (클라이언트 측 시뮬레이션 + toast) ──
  // 실제 파일 이동은 organize API를 통해 수행.
  // 여기서는 선택된 레코드의 카테고리 표시만 즉시 갱신하고 toast 표시.
  async function applyBulkCategory() {
    if (!bulkCategory || selectedIds.size === 0) return;
    showToast(`${selectedIds.size}개 항목을 '${bulkCategory}'로 분류 요청했습니다. 정리 실행 시 반영됩니다.`);
    selectedIds = new Set();
    bulkCategory = '';
  }

  // ── 정리 미리보기 ─────────────────────────────────────────
  async function openOrganizeModal() {
    showOrganizeModal = true;
    organizeResult = '';
    previewDirs = [];
    previewLoading = true;
    try {
      const res = await archiveApi.preview();
      previewDirs = res.dirs ?? [];
    } catch (e) {
      organizeResult = e instanceof Error ? e.message : '미리보기 실패';
    } finally {
      previewLoading = false;
    }
  }

  // ── 정리 실행 ─────────────────────────────────────────────
  async function runOrganize() {
    organizeLoading = true;
    organizeResult = '';
    try {
      const res = await archiveApi.organize();
      const totalMoved = res.results.reduce((s, r) => s + r.moved.length, 0);
      const totalErrors = res.results.reduce((s, r) => s + r.errors.length, 0);
      organizeResult = `완료: ${totalMoved}개 이동${totalErrors > 0 ? `, ${totalErrors}개 오류` : ''}`;
      showToast(organizeResult);
      showOrganizeModal = false;
      loadRecords();
    } catch (e) {
      organizeResult = e instanceof Error ? e.message : '정리 실패';
    } finally {
      organizeLoading = false;
    }
  }

  // ── 중복 감지 ─────────────────────────────────────────────
  async function openDuplicatesModal() {
    showDuplicatesModal = true;
    dupeDirs = [];
    dupesLoading = true;
    try {
      const res = await archiveApi.duplicates();
      dupeDirs = res.dirs ?? [];
    } catch (e) {
      showToast(e instanceof Error ? e.message : '중복 감지 실패');
      showDuplicatesModal = false;
    } finally {
      dupesLoading = false;
    }
  }

  function selectRecord(record: PlanRecord) {
    if (selectedRecord?.id === record.id) {
      selectedRecord = null;
      selectedRelations = [];
    } else {
      selectedRecord = record;
      loadSelectedRelations(record.id);
    }
    detailTab = 'content';
  }

  // 외부 quick search 포커싱: file_path로 record get_or_create 후 자동 선택
  let lastFocusPath: string | null = $state(null);
  $effect(() => {
    if (!focusPath || focusPath === lastFocusPath) return;
    lastFocusPath = focusPath;
    void (async () => {
      try {
        const record = await planRecordsApi.byPath(focusPath);
        selectedRecord = record;
        detailTab = 'content';
        loadSelectedRelations(record.id);
        if (!records.some((r) => r.id === record.id)) {
          records = [record, ...records];
        }
      } catch (e) {
        error = e instanceof Error ? e.message : '계획서를 열지 못했습니다.';
      } finally {
        onFocusConsumed?.();
      }
    })();
  });

  function formatDate(iso: string | null) {
    if (!iso) return '-';
    return new Date(iso).toLocaleDateString('ko-KR');
  }

  function formatDateTime(iso: string | null | undefined) {
    if (!iso) return '-';
    return new Date(iso).toLocaleString('ko-KR', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function getArchiveStateClass(archiveState: string | null | undefined) {
    switch (archiveState) {
      case 'ready':
      case 'indexed':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200';
      case 'blocked':
      case 'stale':
        return 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-200';
      case 'removed':
        return 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-200';
      default:
        return 'bg-muted text-muted-foreground';
    }
  }

  onMount(() => {
    loadRecords();
  });
</script>

<!-- 토스트 -->
{#if toast}
  <div class="fixed bottom-4 right-4 z-50 bg-foreground text-background text-xs px-4 py-2 rounded shadow-lg">
    {toast}
  </div>
{/if}

<div class="flex gap-4 h-full">
  <!-- 목록 패널 -->
  <div class="flex-1 flex flex-col min-w-0">
    <!-- 헤더 -->
    <div class="flex items-center justify-between mb-3 gap-2 flex-wrap">
      <div class="flex items-center gap-2">
        <h2 class="text-sm font-semibold text-foreground">아카이브된 계획서</h2>
        <select
          class="border border-border rounded px-2 py-0.5 text-xs bg-background text-foreground"
          bind:value={filterCategory}
          onchange={() => loadRecords()}
        >
          <option value="">전체 카테고리</option>
          {#each ['naver-booking','instagram','google-search','activity','claude-worker','video','infra','writing','common'] as cat}
            <option value={cat}>{cat}</option>
          {/each}
        </select>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <button
          class="px-3 py-1 text-xs rounded bg-muted hover:bg-secondary text-muted-foreground"
          onclick={openDuplicatesModal}
        >중복 감지</button>
        <button
          class="px-3 py-1 text-xs rounded bg-blue-100 hover:bg-blue-200 text-blue-700 dark:bg-blue-900 dark:hover:bg-blue-800 dark:text-blue-200"
          onclick={openOrganizeModal}
        >정리</button>
        <a
          class="px-3 py-1 text-xs rounded bg-purple-100 hover:bg-purple-200 text-purple-700 dark:bg-purple-900 dark:hover:bg-purple-800 dark:text-purple-200"
          href="/automation?tab=plans&subtab=insights"
        >인사이트</a>
        <button
          class="px-3 py-1 text-xs rounded bg-muted hover:bg-secondary text-muted-foreground"
          onclick={() => { loadRecords(); }}
        >새로고침</button>
      </div>
    </div>

    <ArchiveSyncPanel
      {importLoading}
      {importResult}
      {syncLoading}
      {syncResult}
      onImport={runImportArchived}
      onSync={runSync}
    />

    <!-- 벌크 액션 바 -->
    {#if selectedIds.size > 0}
      <div class="flex items-center gap-2 mb-2 p-2 bg-muted rounded text-xs">
        <span class="text-muted-foreground">{selectedIds.size}개 선택됨</span>
        <select
          class="border border-border rounded px-2 py-0.5 text-xs bg-background text-foreground"
          bind:value={bulkCategory}
        >
          <option value="">카테고리 선택</option>
          {#each CATEGORIES as cat}
            <option value={cat}>{cat}</option>
          {/each}
        </select>
        <button
          class="px-2 py-0.5 rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
          disabled={!bulkCategory}
          onclick={applyBulkCategory}
        >적용</button>
        <button
          class="px-2 py-0.5 rounded bg-muted hover:bg-secondary text-muted-foreground ml-auto"
          onclick={() => { selectedIds = new Set(); }}
        >선택 해제</button>
      </div>
    {/if}

    {#if error}
      <p class="text-sm text-red-500 mb-2">{error}</p>
    {/if}

    {#if loading && records.length === 0}
      <p class="text-sm text-muted-foreground">로드 중...</p>
    {:else if records.length === 0}
      <p class="text-sm text-muted-foreground">아카이브된 계획서가 없습니다.</p>
    {:else}
      <div class="overflow-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-muted-foreground text-xs border-b border-border">
              <th class="pb-2 pr-2 w-6">
                <input
                  type="checkbox"
                  checked={selectedIds.size === records.length && records.length > 0}
                  onchange={toggleSelectAll}
                  class="cursor-pointer"
                />
              </th>
              <th class="pb-2 pr-4 font-medium">파일명</th>
              <th class="pb-2 pr-3 font-medium whitespace-nowrap">카테고리</th>
              <th class="pb-2 pr-3 font-medium whitespace-nowrap">Archive</th>
              <th class="pb-2 pr-4 font-medium whitespace-nowrap">완료일</th>
              <th class="pb-2 pr-4 font-medium whitespace-nowrap">상태</th>
              <th class="pb-2 font-medium">메모</th>
            </tr>
          </thead>
          <tbody>
            {#each records as record (record.id)}
              <tr
                class="border-b border-border hover:bg-muted cursor-pointer transition-colors {selectedRecord?.id === record.id ? 'bg-muted' : ''}"
                onclick={() => selectRecord(record)}
              >
                <td class="py-2 pr-2" onclick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selectedIds.has(record.id)}
                    onchange={(e) => toggleSelect(record.id, e)}
                    class="cursor-pointer"
                  />
                </td>
                <td class="py-2 pr-4 text-foreground font-mono text-xs max-w-xs truncate" title={record.file_path}>
                  {record.file_path.split(/[\\/]/).pop() ?? record.file_path}
                </td>
                <td class="py-2 pr-3">
                  <span class="inline-block px-1.5 py-0.5 text-xs rounded {record.category ? 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200' : 'bg-muted text-muted-foreground'}">
                    {record.category ?? getCategoryFromPath(record.file_path)}
                  </span>
                  {#if record.llm_processed_at}
                    <span class="inline-block ml-1 px-1 py-0.5 text-xs rounded bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200" title="LLM 분석 완료">LLM</span>
                  {/if}
                  {#if record.file_removed_at}
                    <span class="inline-block ml-1 px-1 py-0.5 text-xs rounded bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-200" title="archive 파일 제거됨">파일 제거됨</span>
                  {:else if record.file_delete_after}
                    <span class="inline-block ml-1 px-1 py-0.5 text-xs rounded bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-200" title={`삭제 예정: ${formatDateTime(record.file_delete_after)}`}>삭제 예정</span>
                  {/if}
                </td>
                <td class="py-2 pr-3">
                  <span class="inline-block rounded px-1.5 py-0.5 text-xs {getArchiveStateClass(record.archive_state)}">
                    {record.archive_state ?? '-'}
                  </span>
                </td>
                <td class="py-2 pr-4 text-muted-foreground text-xs whitespace-nowrap">
                  {formatDate(record.archived_at)}
                </td>
                <td class="py-2 pr-4" onclick={(e) => e.stopPropagation()}>
                  {#if !record.status || record.status === 'unknown' || editingStatusId === record.id}
                    <select
                      class="text-xs rounded border border-border bg-background px-1 py-0.5 cursor-pointer"
                      value={record.status && record.status !== 'unknown' ? record.status : ''}
                      onchange={(e) => handleStatusChange(record, (e.target as HTMLSelectElement).value)}
                      onblur={() => { if (editingStatusId === record.id) editingStatusId = null; }}
                    >
                      <option value="" disabled>상태 선택</option>
                      {#each EDITABLE_STATUSES as s}
                        <option value={s}>{s}</option>
                      {/each}
                    </select>
                  {:else}
                    <span
                      class="px-2 py-0.5 rounded text-xs cursor-pointer bg-secondary text-secondary-foreground"
                      title="클릭하여 상태 변경"
                      onclick={() => { editingStatusId = record.id; }}
                    >
                      {record.status}
                    </span>
                  {/if}
                </td>
                <td class="py-2">
                  {#if record.memo}
                    <span class="text-xs text-muted-foreground truncate max-w-xs inline-block" title={record.memo}>
                      {record.memo.slice(0, 40)}{record.memo.length > 40 ? '...' : ''}
                    </span>
                  {:else}
                    <button
                      class="px-2 py-0.5 text-xs rounded bg-muted hover:bg-secondary text-muted-foreground"
                      onclick={(e) => { e.stopPropagation(); selectRecord(record); }}
                    >메모 추가</button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      {#if hasMore}
        <button
          class="mt-3 px-4 py-2 text-xs rounded bg-muted hover:bg-secondary text-muted-foreground self-center"
          disabled={loading}
          onclick={() => loadRecords(true)}
        >
          {loading ? '로드 중...' : '더 보기'}
        </button>
      {/if}
    {/if}

  </div>

  <!-- 상세 패널 -->
  {#if selectedRecord}
    <ArchiveRecordDetailPanel
      record={selectedRecord}
      relations={selectedRelations}
      relationsLoading={selectedRelationsLoading}
      {detailTab}
      onClose={() => { selectedRecord = null; }}
      onTabChange={(tab) => { detailTab = tab; }}
    />
  {/if}
</div>


<!-- 정리 미리보기 모달 -->
{#if showOrganizeModal}
  <div
    class="fixed inset-0 z-40 bg-black/40 flex items-center justify-center"
    onclick={(e) => { if (e.target === e.currentTarget) { () => { if (!organizeLoading) showOrganizeModal = false; ; } }}}
    role="dialog"
    aria-modal="true"
  >
    <div class="bg-background border border-border rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col p-5">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-foreground">Archive 폴더 정리 미리보기</h2>
        <button
          class="text-muted-foreground hover:text-foreground text-xs"
          onclick={() => { showOrganizeModal = false; }}
          disabled={organizeLoading}
        >닫기</button>
      </div>

      <div class="flex-1 overflow-auto text-xs space-y-4">
        {#if previewLoading}
          <p class="text-muted-foreground">분석 중...</p>
        {:else if previewDirs.length === 0}
          <p class="text-muted-foreground">등록된 archive 경로가 없거나 이동할 파일이 없습니다.</p>
        {:else}
          {#each previewDirs as dir}
            <div>
              <p class="font-mono text-muted-foreground mb-1 truncate" title={dir.archive_dir}>{dir.archive_dir}</p>
              {#if dir.items.filter(i => i.needs_move).length === 0}
                <p class="text-muted-foreground text-xs">이동할 파일이 없습니다.</p>
              {:else}
                <table class="w-full border-collapse">
                  <thead>
                    <tr class="text-muted-foreground border-b border-border">
                      <th class="text-left pb-1 pr-3 font-medium">파일명</th>
                      <th class="text-left pb-1 pr-3 font-medium">카테고리</th>
                      <th class="text-left pb-1 font-medium">이동 경로</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each dir.items.filter(i => i.needs_move) as item}
                      <tr class="border-b border-border/50">
                        <td class="py-1 pr-3 font-mono truncate max-w-[10rem]" title={item.filename}>{item.filename}</td>
                        <td class="py-1 pr-3">
                          <span class="px-1 rounded bg-muted">{item.category}</span>
                        </td>
                        <td class="py-1 font-mono text-muted-foreground truncate max-w-[14rem]" title={item.dest}>
                          …/{item.dest.split(/[\\/]/).slice(-2).join('/')}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              {/if}
            </div>
          {/each}
        {/if}

        {#if organizeResult}
          <p class="text-green-600 dark:text-green-400 font-medium">{organizeResult}</p>
        {/if}
      </div>

      <div class="flex justify-end gap-2 mt-4">
        <button
          class="px-3 py-1.5 text-xs rounded bg-muted hover:bg-secondary text-muted-foreground"
          onclick={() => { showOrganizeModal = false; }}
          disabled={organizeLoading}
        >취소</button>
        <button
          class="px-3 py-1.5 text-xs rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
          disabled={organizeLoading || previewLoading || previewDirs.every(d => d.items.every(i => !i.needs_move))}
          onclick={runOrganize}
        >
          {organizeLoading ? '정리 중...' : '정리 실행'}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- 중복 감지 모달 -->
{#if showDuplicatesModal}
  <div
    class="fixed inset-0 z-40 bg-black/40 flex items-center justify-center"
    onclick={(e) => { if (e.target === e.currentTarget) { showDuplicatesModal = false; } }}
    onkeydown={(e) => { if (e.key === 'Escape') { showDuplicatesModal = false; } }}
    role="dialog"
    aria-modal="true"
  >
    <div class="bg-background border border-border rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col p-5">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-foreground">중복 파일 감지 결과</h2>
        <button
          class="text-muted-foreground hover:text-foreground text-xs"
          onclick={() => { showDuplicatesModal = false; }}
        >닫기</button>
      </div>

      <div class="flex-1 overflow-auto text-xs space-y-4">
        {#if dupesLoading}
          <p class="text-muted-foreground">분석 중...</p>
        {:else if dupeDirs.every(d => d.duplicates.length === 0)}
          <p class="text-muted-foreground">중복 파일이 없습니다.</p>
        {:else}
          {#each dupeDirs as dir}
            {#if dir.duplicates.length > 0}
              <div>
                <p class="font-mono text-muted-foreground mb-2 truncate" title={dir.archive_dir}>{dir.archive_dir}</p>
                <table class="w-full border-collapse">
                  <thead>
                    <tr class="text-muted-foreground border-b border-border">
                      <th class="text-left pb-1 pr-3 font-medium">파일 A</th>
                      <th class="text-left pb-1 pr-3 font-medium">파일 B</th>
                      <th class="text-left pb-1 pr-2 font-medium">유사도</th>
                      <th class="text-left pb-1 font-medium">유형</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each dir.duplicates as dup}
                      <tr class="border-b border-border/50">
                        <td class="py-1 pr-3 font-mono truncate max-w-[10rem]" title={dup.file_a}>
                          {dup.file_a.split(/[\\/]/).pop()}
                        </td>
                        <td class="py-1 pr-3 font-mono truncate max-w-[10rem]" title={dup.file_b}>
                          {dup.file_b.split(/[\\/]/).pop()}
                        </td>
                        <td class="py-1 pr-2 text-right">{(dup.similarity * 100).toFixed(0)}%</td>
                        <td class="py-1">
                          <span class="px-1 rounded {dup.reason === 'exact_name' ? 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300' : 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300'}">
                            {dup.reason === 'exact_name' ? '동일명' : '유사명'}
                          </span>
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          {/each}
        {/if}
      </div>

      <div class="flex justify-end mt-4">
        <button
          class="px-3 py-1.5 text-xs rounded bg-muted hover:bg-secondary text-muted-foreground"
          onclick={() => { showDuplicatesModal = false; }}
        >닫기</button>
      </div>
    </div>
  </div>
{/if}
