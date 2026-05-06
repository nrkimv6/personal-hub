<script lang="ts">
  import { onMount } from 'svelte';
  import { formatLLMBlockReason, llmApi, type LLMProfileConfig, type LLMRequest, type LLMScheduleProfilePolicyItem } from '$lib/api';
  import {
    planRecordsApi,
    archiveApi,
    type PlanRecord,
    type ImportArchivedResult,
    type ArchivePreviewItem,
    type DuplicateItem,
    type PlanArchiveHealth,
    type PlanArchiveRetrievalQuery,
    type PlanArchiveRetrievalResult,
    type PlanArchiveMetricsResponse,
    type PlanArchiveIndexResponse,
    type PlanArchiveExecutionAttempt,
    type PlanArchiveSelectedProfile
  } from '$lib/api/plan-records';
  import { devRunnerPlanApi } from '$lib/api/dev-runner';
  import MemoEditor from './MemoEditor.svelte';
  import PlanViewer from './PlanViewer.svelte';

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
  let detailTab: 'content' | 'memo' | 'analyze' | 'history' = $state('content');
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

  async function runImportArchived() {
    importLoading = true;
    importResult = null;
    try {
      const res = await planRecordsApi.importArchived();
      importResult = res;
      showToast(`DB 이관 완료: ${res.created}개 생성, ${res.updated}개 갱신, ${res.skipped}개 스킵`);
      loadRecords();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'DB 이관 실패');
    } finally {
      importLoading = false;
    }
  }

  // LLM 처리 현황 (서버 health + Plan Archive 요청 목록)
  let archiveHealth: PlanArchiveHealth | null = $state(null);
  let archiveHealthLoading = $state(false);
  let archiveQueueLoading = $state(false);
  let archiveQueueError = $state('');
  let archiveRequests: LLMRequest[] = $state([]);
  let archiveQueuePage = $state(1);
  let archiveQueueTotal = $state(0);
  let archiveQueuePages = $state(1);
  const archiveQueuePageSize = 50;
  let archiveQueueStatus = $state('pending,processing,failed');
  let archiveQueueProvider = $state('');
  let archiveProfiles: LLMProfileConfig[] = $state([]);
  let archiveProfilePolicies: LLMScheduleProfilePolicyItem[] = $state([]);
  let selectedArchiveProfileKeys = $state(new Set<string>());
  let archiveExecutionLoading = $state(false);
  let archiveExecutionError = $state('');
  let archiveExecutionResult = $state('');
  let selectedExecutionHistory: PlanArchiveExecutionAttempt[] = $state([]);
  let selectedExecutionHistoryLoading = $state(false);
  let selectedExecutionHistoryError = $state('');

  // ── Retrieval MVP 표면 ───────────────────────────────────
  let retrievalQ = $state('');
  let retrievalPath = $state('');
  let retrievalRepoKey = $state('');
  let retrievalCategory = $state('');
  let retrievalTags = $state('');
  let retrievalIntent = $state('');
  let retrievalScope = $state('');
  let retrievalDateFrom = $state('');
  let retrievalDateTo = $state('');
  let retrievalRelationType = $state('');
  let retrievalLimit = $state(10);
  let retrievalLoading = $state(false);
  let retrievalError = $state('');
  let retrievalResults: PlanArchiveRetrievalResult[] = $state([]);
  let retrievalTotal = $state(0);
  let metricsLoading = $state(false);
  let metricsError = $state('');
  let retrievalMetrics: PlanArchiveMetricsResponse | null = $state(null);
  let indexLimit = $state(100);
  let indexForce = $state(false);
  let indexSince = $state('');
  let indexLoading = $state(false);
  let indexError = $state('');
  let indexResult: PlanArchiveIndexResponse | null = $state(null);
  let crossRepoIndexLoading = $state(false);
  let crossRepoIndexResult: PlanArchiveCrossRepoIndexResponse | null = $state(null);

  // ── 수동 분석 preview/apply ───────────────────────────────
  let analyzeProvider = $state('codex');
  let analyzeModel = $state('gpt-5.2');
  let analyzeTimeout = $state(120);
  let analyzeLoading = $state(false);
  let analyzeResult: PlanArchiveAnalyzeResponse | null = $state(null);
  let analyzeError = $state('');
  let confirmingApply = $state(false);

  async function loadArchiveHealth() {
    archiveHealthLoading = true;
    try {
      archiveHealth = await planRecordsApi.getArchiveHealth();
    } catch (e) {
      archiveHealth = null;
    } finally {
      archiveHealthLoading = false;
    }
  }

  async function loadArchiveQueue(page = archiveQueuePage) {
    archiveQueueLoading = true;
    archiveQueueError = '';
    try {
      const res = await llmApi.list({
        caller_type: 'plan_archive_analyze',
        status: archiveQueueStatus || undefined,
        page,
        page_size: archiveQueuePageSize,
      });
      archiveRequests = archiveQueueProvider
        ? res.items.filter((request) => (request.provider || 'claude') === archiveQueueProvider)
        : res.items;
      archiveQueuePage = res.page;
      archiveQueueTotal = archiveQueueProvider ? archiveRequests.length : res.total;
      archiveQueuePages = archiveQueueProvider ? 1 : res.pages;
    } catch (e) {
      archiveQueueError = e instanceof Error ? e.message : 'LLM 요청 목록 로드 실패';
    } finally {
      archiveQueueLoading = false;
    }
  }

  async function refreshArchiveSurfaces() {
    await Promise.all([loadArchiveHealth(), loadArchiveQueue(1)]);
  }

  function profileKey(profile: PlanArchiveSelectedProfile) {
    return `${profile.engine}:${profile.profile_name}`;
  }

  function parseProfileKey(key: string): PlanArchiveSelectedProfile {
    const [engine, ...rest] = key.split(':');
    return { engine, profile_name: rest.join(':') };
  }

  function getArchiveProfileChoices(): PlanArchiveSelectedProfile[] {
    const policyChoices = archiveProfilePolicies
      .filter((policy) => policy.enabled && (!policy.target_type || policy.target_type === 'plan_archive_analyze'))
      .sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0))
      .map((policy) => ({ engine: policy.engine, profile_name: policy.profile_name }));
    const profileChoices = archiveProfiles
      .filter((profile) => profile.enabled !== false)
      .sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0))
      .map((profile) => ({ engine: profile.engine, profile_name: profile.name }));
    const seen = new Set<string>();
    const choices: PlanArchiveSelectedProfile[] = [];
    for (const choice of [...policyChoices, ...profileChoices]) {
      const key = profileKey(choice);
      if (seen.has(key)) continue;
      seen.add(key);
      choices.push(choice);
    }
    return choices;
  }

  async function loadArchiveExecutionProfiles() {
    try {
      const [profilesResponse, policyResponse] = await Promise.all([
        llmApi.listProfiles(),
        llmApi.listScheduleProfilePolicies()
      ]);
      archiveProfiles = profilesResponse.profiles ?? [];
      archiveProfilePolicies = policyResponse.policies ?? [];
      if (selectedArchiveProfileKeys.size === 0) {
        selectedArchiveProfileKeys = new Set(getArchiveProfileChoices().map(profileKey));
      }
    } catch {
      archiveProfiles = [];
      archiveProfilePolicies = [];
    }
  }

  function toggleArchiveProfile(profile: PlanArchiveSelectedProfile) {
    const key = profileKey(profile);
    if (selectedArchiveProfileKeys.has(key)) {
      selectedArchiveProfileKeys.delete(key);
    } else {
      selectedArchiveProfileKeys.add(key);
    }
    selectedArchiveProfileKeys = new Set(selectedArchiveProfileKeys);
  }

  function getSelectedArchiveProfiles(): PlanArchiveSelectedProfile[] {
    return [...selectedArchiveProfileKeys].map(parseProfileKey).filter((profile) => profile.engine && profile.profile_name);
  }

  async function runArchiveExecutions() {
    archiveExecutionLoading = true;
    archiveExecutionError = '';
    archiveExecutionResult = '';
    try {
      const selectedProfiles = getSelectedArchiveProfiles();
      const result = await planRecordsApi.runArchiveExecutions({
        record_ids: selectedIds.size > 0 ? [...selectedIds] : undefined,
        selected_profiles: selectedProfiles.length > 0 ? selectedProfiles : undefined
      });
      const queued = Number(result.queued ?? result.updated ?? result.request_ids?.length ?? result.attempts?.length ?? 0);
      const skipped = Number(result.skipped ?? 0);
      archiveExecutionResult = `queued ${queued}${skipped ? `, skipped ${skipped}` : ''}`;
      showToast(`Archive 실행 요청: ${archiveExecutionResult}`);
      await Promise.all([loadRecords(), refreshArchiveSurfaces()]);
      if (selectedRecord) await loadSelectedExecutionHistory(selectedRecord.id);
    } catch (e) {
      archiveExecutionError = e instanceof Error ? e.message : 'archive 실행 요청 실패';
    } finally {
      archiveExecutionLoading = false;
    }
  }

  async function syncArchiveExecutions() {
    archiveExecutionLoading = true;
    archiveExecutionError = '';
    archiveExecutionResult = '';
    try {
      const result = await planRecordsApi.syncArchiveExecutions();
      archiveExecutionResult = `sync updated ${Number(result.updated ?? result.records?.length ?? 0)}`;
      showToast(`Archive 실행 동기화: ${archiveExecutionResult}`);
      await Promise.all([loadRecords(), refreshArchiveSurfaces()]);
      if (selectedRecord) await loadSelectedExecutionHistory(selectedRecord.id);
    } catch (e) {
      archiveExecutionError = e instanceof Error ? e.message : 'archive 실행 동기화 실패';
    } finally {
      archiveExecutionLoading = false;
    }
  }

  async function loadSelectedExecutionHistory(recordId: number) {
    selectedExecutionHistoryLoading = true;
    selectedExecutionHistoryError = '';
    try {
      const result = await planRecordsApi.getArchiveExecutionHistory({ record_id: recordId, limit: 20 });
      selectedExecutionHistory = result.items ?? [];
    } catch (e) {
      selectedExecutionHistory = [];
      selectedExecutionHistoryError = e instanceof Error ? e.message : '실행 이력 로드 실패';
    } finally {
      selectedExecutionHistoryLoading = false;
    }
  }

  function openSelectedExecutionHistory() {
    const record = selectedRecord;
    if (!record) return;
    detailTab = 'history';
    void loadSelectedExecutionHistory(record.id);
  }

  function refreshSelectedExecutionHistory() {
    const record = selectedRecord;
    if (!record) return;
    void loadSelectedExecutionHistory(record.id);
  }

  function buildRetrievalFilters(includeLimit = true): PlanArchiveRetrievalQuery {
    const tags = retrievalTags
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean);
    const payload: PlanArchiveRetrievalQuery = {};
    if (retrievalQ.trim()) payload.q = retrievalQ.trim();
    if (retrievalDateFrom) payload.date_from = retrievalDateFrom;
    if (retrievalDateTo) payload.date_to = retrievalDateTo;
    if (retrievalCategory.trim()) payload.category = retrievalCategory.trim();
    if (tags.length > 0) payload.tags = tags;
    if (retrievalIntent.trim()) payload.intent = retrievalIntent.trim();
    if (retrievalScope.trim()) payload.scope = retrievalScope.trim();
    if (retrievalPath.trim()) payload.path = retrievalPath.trim();
    if (retrievalRepoKey.trim()) payload.repo_key = retrievalRepoKey.trim();
    if (retrievalRelationType.trim()) payload.relation_type = retrievalRelationType.trim();
    if (includeLimit) {
      const limitValue = Number(retrievalLimit);
      payload.limit = Number.isFinite(limitValue) ? limitValue : 10;
    }
    return payload;
  }

  async function runRetrievalSearch() {
    retrievalLoading = true;
    retrievalError = '';
    try {
      const res = await planRecordsApi.searchArchiveRetrieval(buildRetrievalFilters());
      retrievalResults = res.results ?? [];
      retrievalTotal = res.total ?? retrievalResults.length;
      void loadRetrievalMetrics();
    } catch (e) {
      retrievalResults = [];
      retrievalTotal = 0;
      retrievalError = e instanceof Error ? e.message : 'retrieval 검색 실패';
    } finally {
      retrievalLoading = false;
    }
  }

  async function loadRetrievalMetrics() {
    metricsLoading = true;
    metricsError = '';
    try {
      retrievalMetrics = await planRecordsApi.getArchiveRetrievalMetrics(buildRetrievalFilters(false));
    } catch (e) {
      retrievalMetrics = null;
      metricsError = e instanceof Error ? e.message : 'retrieval metrics 로드 실패';
    } finally {
      metricsLoading = false;
    }
  }

  async function runArchiveIndex(apply = false) {
    if (apply && indexResult?.dry_run !== true) {
      showToast('dry-run 결과 확인 후 apply를 실행할 수 있습니다.');
      return;
    }
    indexLoading = true;
    indexError = '';
    try {
      indexResult = await planRecordsApi.indexArchiveRecords({
        limit: Number(indexLimit),
        force: indexForce,
        since: indexSince || undefined,
        apply,
      });
      showToast(
        `${indexResult.dry_run ? 'Index dry-run' : 'Index apply'}: indexed ${indexResult.indexed}, failed ${indexResult.failed}, skipped ${indexResult.skipped}`
      );
      if (!indexResult.dry_run) {
        await loadRetrievalMetrics();
      }
    } catch (e) {
      indexError = e instanceof Error ? e.message : 'archive index 실행 실패';
    } finally {
      indexLoading = false;
    }
  }

  async function runCrossRepoIndex(apply = false) {
    if (!selectedRecord) return;
    crossRepoIndexLoading = true;
    try {
      crossRepoIndexResult = await planRecordsApi.indexCrossRepoArchive({
        record_id: selectedRecord.id,
        max_commits: 30,
        apply,
      });
      showToast(
        `Cross-repo ${crossRepoIndexResult.dry_run ? 'dry-run' : 'apply'}: repos ${crossRepoIndexResult.repos}, indexed ${crossRepoIndexResult.indexed}`
      );
      if (apply) await loadRetrievalMetrics();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'cross-repo index 실패');
    } finally {
      crossRepoIndexLoading = false;
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
    selectedRecord = selectedRecord?.id === record.id ? null : record;
    detailTab = 'content';
    analyzeResult = null;
    analyzeError = '';
    confirmingApply = false;
    selectedExecutionHistory = [];
    selectedExecutionHistoryError = '';
    if (selectedRecord) {
      void loadSelectedExecutionHistory(record.id);
    }
  }

  async function runManualAnalyze(mode: 'preview' | 'apply') {
    if (!selectedRecord) return;
    analyzeLoading = true;
    analyzeError = '';
    confirmingApply = false;
    try {
      const result = await planRecordsApi.analyzeRecord(selectedRecord.id, {
        mode,
        provider: analyzeProvider || undefined,
        model: analyzeModel || undefined,
        timeout_seconds: Number(analyzeTimeout),
      });
      analyzeResult = result;
      if (result.saved) {
        await loadRecords();
        selectedRecord = records.find((record) => record.id === result.record_id) ?? selectedRecord;
      }
      showToast(result.saved ? 'DB 저장 완료' : result.success ? '분석 완료' : (result.error || '분석 실패'));
    } catch (e) {
      analyzeError = e instanceof Error ? e.message : '분석 요청 실패';
    } finally {
      analyzeLoading = false;
    }
  }

  async function copyAnalyzeResult() {
    if (!analyzeResult) return;
    await navigator.clipboard.writeText(JSON.stringify(analyzeResult.result, null, 2));
    showToast('분석 결과를 복사했습니다.');
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

  function formatScore(score: number | undefined) {
    return typeof score === 'number' && Number.isFinite(score) ? score.toFixed(2) : '-';
  }

  function formatRate(rate: number | undefined) {
    const value = typeof rate === 'number' && Number.isFinite(rate) ? rate : 0;
    return `${(value <= 1 ? value * 100 : value).toFixed(0)}%`;
  }

  function getPlanValue(plan: PlanArchiveRetrievalResult['plan'], key: string) {
    if (!plan || typeof plan !== 'object') return undefined;
    return (plan as Record<string, unknown>)[key];
  }

  function getResultPlanTitle(result: PlanArchiveRetrievalResult) {
    const title = getPlanValue(result.plan, 'title');
    if (typeof title === 'string' && title.trim()) return title;
    const path = getPlanValue(result.plan, 'file_path');
    if (typeof path === 'string' && path.trim()) {
      return path.split(/[\\/]/).pop() ?? path;
    }
    const id = getPlanValue(result.plan, 'id');
    return typeof id === 'number' ? `Plan #${id}` : 'Untitled plan';
  }

  function getResultPlanPath(result: PlanArchiveRetrievalResult) {
    const path = getPlanValue(result.plan, 'file_path');
    return typeof path === 'string' ? path : '';
  }

  function getScoreDetails(result: PlanArchiveRetrievalResult) {
    return Object.entries(result.score_detail ?? {})
      .slice(0, 4)
      .map(([key, value]) => `${key} ${typeof value === 'number' ? formatScore(value) : String(value)}`);
  }

  function getStatusClass(status: string) {
    switch (status) {
      case 'pending':
        return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-200';
      case 'processing':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200';
      case 'failed':
        return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200';
      case 'completed':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200';
      default:
        return 'bg-muted text-muted-foreground';
    }
  }

  function getExecutionStateClass(state: string | null | undefined) {
    switch (state) {
      case 'queued':
      case 'pending':
        return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-200';
      case 'running':
      case 'processing':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200';
      case 'failed':
        return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200';
      case 'completed':
      case 'success':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200';
      default:
        return 'bg-muted text-muted-foreground';
    }
  }

  function getArchiveStateClass(state: string | null | undefined) {
    switch (state) {
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

  function getAttemptStatus(attempt: PlanArchiveExecutionAttempt | null | undefined) {
    return attempt?.status ?? attempt?.state ?? '-';
  }

  function getAttemptTime(attempt: PlanArchiveExecutionAttempt | null | undefined) {
    return attempt?.completed_at ?? attempt?.started_at ?? attempt?.requested_at ?? null;
  }

  function getAttemptProfile(attempt: PlanArchiveExecutionAttempt | null | undefined) {
    const engine = attempt?.engine;
    const profile = attempt?.profile_name;
    if (engine && profile) return `${engine}/${profile}`;
    if (engine) return engine;
    if (profile) return profile;
    return '-';
  }

  function getRequestProfile(request: LLMRequest) {
    const cliOptions = request.cli_options as Record<string, unknown> | undefined;
    const profile = cliOptions?.profile ?? cliOptions?.engine_profile ?? cliOptions?.profile_name;
    return typeof profile === 'string' && profile.trim() ? profile : 'inherit';
  }

  function getErrorSummary(message: string | null | undefined) {
    if (!message) return '-';
    return message.length > 80 ? `${message.slice(0, 80)}...` : message;
  }

  function getRequestReason(request: LLMRequest) {
    return request.pending_block_reason
      ? formatLLMBlockReason(request.pending_block_reason)
      : getErrorSummary(request.error_message);
  }

  onMount(() => {
    loadRecords();
    refreshArchiveSurfaces();
    loadArchiveExecutionProfiles();
    loadRetrievalMetrics();
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
        {#if archiveHealth}
          <span class="text-xs text-muted-foreground">
            LLM: {archiveHealth.llm_processed}/{archiveHealth.archived_total}
            {#if archiveHealth.real_unprocessed > 0}
              <span class="text-yellow-600 dark:text-yellow-400">(실제 미처리 {archiveHealth.real_unprocessed})</span>
            {/if}
          </span>
        {/if}
        <button
          class="px-3 py-1 text-xs rounded bg-green-100 hover:bg-green-200 text-green-700 dark:bg-green-900 dark:hover:bg-green-800 dark:text-green-200 disabled:opacity-50"
          onclick={runImportArchived}
          disabled={importLoading}
        >{importLoading ? 'DB 이관 중...' : 'DB 이관'}</button>
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
          onclick={() => { loadRecords(); refreshArchiveSurfaces(); }}
        >새로고침</button>
      </div>
    </div>

    <!-- Plan Archive health 패널 -->
    <div class="mb-3 grid gap-3 rounded border border-border bg-background p-3 text-xs lg:grid-cols-[1.3fr_1fr]">
      <div>
        <div class="mb-2 flex items-center justify-between gap-2">
          <h3 class="font-semibold text-foreground">Plan Archive LLM health</h3>
          {#if archiveHealthLoading}
            <span class="text-muted-foreground">갱신 중...</span>
          {/if}
        </div>
        {#if archiveHealth}
          <div class="grid gap-2 sm:grid-cols-4">
            <div class="rounded bg-muted px-2 py-2">
              <div class="text-muted-foreground">Archived</div>
              <div class="font-semibold text-foreground">{archiveHealth.archived_total}</div>
            </div>
            <div class="rounded bg-muted px-2 py-2">
              <div class="text-muted-foreground">Processed</div>
              <div class="font-semibold text-foreground">{archiveHealth.llm_processed}</div>
            </div>
            <div class="rounded bg-muted px-2 py-2">
              <div class="text-muted-foreground">Unprocessed</div>
              <div class="font-semibold text-foreground">{archiveHealth.llm_unprocessed}</div>
            </div>
            <div class="rounded bg-muted px-2 py-2">
              <div class="text-muted-foreground">Real backlog</div>
              <div class="font-semibold text-foreground">{archiveHealth.real_unprocessed}</div>
            </div>
          </div>
          <div class="mt-3 grid gap-2 md:grid-cols-3">
            <div class="rounded border border-border p-2">
              <div class="text-muted-foreground">Retrieval DB</div>
              <div class="mt-1 font-medium {archiveHealth.retrieval_db_readiness.ok ? 'text-green-700' : 'text-red-700'}">
                {archiveHealth.retrieval_db_readiness.ok ? 'ready' : 'missing tables'}
              </div>
              {#if !archiveHealth.retrieval_db_readiness.ok}
                <div class="mt-1 break-words text-red-700">
                  {archiveHealth.retrieval_db_readiness.missing_tables.join(', ')}
                </div>
              {/if}
            </div>
            <div class="rounded border border-border p-2">
              <div class="text-muted-foreground">스케줄</div>
              <div class="mt-1 font-medium {archiveHealth.plan_archive_schedule?.enabled ? 'text-green-700' : 'text-amber-700'}">
                {archiveHealth.plan_archive_schedule?.enabled ? '활성' : '비활성'}
              </div>
              {#if !archiveHealth.plan_archive_schedule?.enabled && archiveHealth.real_unprocessed > 0}
                <p class="mt-1 text-amber-700">비활성 때문에 backlog가 쌓일 수 있습니다.</p>
              {/if}
            </div>
            <div class="rounded border border-border p-2">
              <div class="text-muted-foreground">마지막 실행</div>
              <div class="mt-1">성공 {formatDateTime(archiveHealth.plan_archive_schedule?.last_success)}</div>
              <div>실패 {formatDateTime(archiveHealth.plan_archive_schedule?.last_failure)}</div>
              {#if !archiveHealth.plan_archive_schedule?.last_success && !archiveHealth.plan_archive_schedule?.last_failure}
                <div class="text-muted-foreground">실행 이력이 없습니다.</div>
              {/if}
            </div>
            <div class="rounded border border-border p-2">
              <div class="text-muted-foreground">노후/실패</div>
              <div class="mt-1">Oldest {formatDateTime(archiveHealth.oldest_unprocessed_at)}</div>
              <div>Failed request {archiveHealth.failed_requests}</div>
              {#if archiveHealth.latest_failed_request}
                <div class="mt-1 truncate" title={archiveHealth.latest_failed_request.error_message ?? ''}>
                  #{archiveHealth.latest_failed_request.id} {formatDateTime(archiveHealth.latest_failed_request.requested_at)}
                  {getErrorSummary(archiveHealth.latest_failed_request.error_message)}
                </div>
              {/if}
            </div>
          </div>
        {:else}
          <p class="text-muted-foreground">Health API 결과를 불러오지 못했습니다.</p>
        {/if}
      </div>
      <div class="rounded border border-border p-2">
        <div class="font-semibold text-foreground">큐 신뢰 경계</div>
        <p class="mt-1 text-muted-foreground">
          pending_or_processing_requests는 현재 활성 LLMRequest 수입니다. archive 미처리 수나 전체 Plan Archive backlog 수와 다릅니다.
        </p>
        {#if archiveHealth}
          <div class="mt-2 flex flex-wrap gap-2">
            <span class="rounded bg-muted px-2 py-1">active {archiveHealth.pending_or_processing_requests}</span>
            <span class="rounded {archiveHealth.failed_requests > 0 ? 'bg-red-100 text-red-700' : 'bg-muted text-muted-foreground'} px-2 py-1">failed {archiveHealth.failed_requests}</span>
            <span class="rounded bg-muted px-2 py-1">temp excluded {archiveHealth.temp_pytest_unprocessed}/{archiveHealth.temp_pytest_total}</span>
            <span class="rounded {archiveHealth.file_retention_due > 0 ? 'bg-amber-100 text-amber-700' : 'bg-muted text-muted-foreground'} px-2 py-1">delete due {archiveHealth.file_retention_due}</span>
            <span class="rounded bg-muted px-2 py-1">scheduled {archiveHealth.file_retention_scheduled}</span>
            <span class="rounded bg-muted px-2 py-1">removed {archiveHealth.file_removed}</span>
          </div>
          <div class="mt-2 text-muted-foreground">oldest delete {formatDateTime(archiveHealth.oldest_file_delete_after)}</div>
        {/if}
      </div>
    </div>

    <!-- Plan Archive 실행 제어 -->
    <div class="mb-3 rounded border border-border bg-background p-3 text-xs">
      <div class="mb-2 flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h3 class="font-semibold text-foreground">Archive execution control</h3>
          <p class="mt-0.5 text-muted-foreground">선택 항목이 있으면 선택 레코드만 실행하고, 없으면 서버 정책 대상에 맡깁니다.</p>
        </div>
        <div class="flex items-center gap-2">
          <button
            class="rounded bg-muted px-2 py-1 text-muted-foreground hover:bg-secondary disabled:opacity-50"
            onclick={syncArchiveExecutions}
            disabled={archiveExecutionLoading}
          >Sync</button>
          <button
            class="rounded bg-primary px-3 py-1 text-primary-foreground hover:opacity-90 disabled:opacity-50"
            onclick={runArchiveExecutions}
            disabled={archiveExecutionLoading || getArchiveProfileChoices().length === 0 || selectedArchiveProfileKeys.size === 0}
          >{archiveExecutionLoading ? 'Running...' : selectedIds.size > 0 ? `Run ${selectedIds.size}` : 'Run backlog'}</button>
        </div>
      </div>
      <div class="flex flex-wrap gap-2">
        {#each getArchiveProfileChoices() as profile (profileKey(profile))}
          <label class="inline-flex items-center gap-1 rounded border border-border bg-muted px-2 py-1 text-muted-foreground">
            <input
              type="checkbox"
              checked={selectedArchiveProfileKeys.has(profileKey(profile))}
              onchange={() => toggleArchiveProfile(profile)}
            />
            <span class="font-mono">{profile.engine}/{profile.profile_name}</span>
          </label>
        {/each}
        {#if getArchiveProfileChoices().length === 0}
          <span class="rounded bg-muted px-2 py-1 text-muted-foreground">사용 가능한 profile policy가 없습니다.</span>
        {:else if selectedArchiveProfileKeys.size === 0}
          <span class="rounded bg-amber-100 px-2 py-1 text-amber-700 dark:bg-amber-900 dark:text-amber-200">profile을 하나 이상 선택하세요.</span>
        {/if}
      </div>
      {#if archiveExecutionError}
        <p class="mt-2 rounded border border-red-300 bg-red-50 px-2 py-1 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{archiveExecutionError}</p>
      {:else if archiveExecutionResult}
        <p class="mt-2 text-muted-foreground">{archiveExecutionResult}</p>
      {/if}
    </div>

    <!-- Plan Archive LLM 요청 목록 -->
    <div class="mb-3 rounded border border-border bg-background p-3 text-xs">
      <div class="mb-2 flex items-center justify-between gap-2 flex-wrap">
        <h3 class="font-semibold text-foreground">Plan Archive LLM 요청</h3>
        <a class="text-primary hover:text-primary-hover" href="/llm?caller_type=plan_archive_analyze">전체 LLM 큐 보기</a>
      </div>
      <div class="mb-2 flex items-center gap-2 flex-wrap">
        <select
          class="border border-border rounded px-2 py-1 bg-background text-foreground"
          bind:value={archiveQueueStatus}
          onchange={() => loadArchiveQueue(1)}
        >
          <option value="pending,processing,failed">대기/처리중/실패</option>
          <option value="pending">대기</option>
          <option value="processing">처리중</option>
          <option value="failed">실패</option>
          <option value="completed">완료</option>
        </select>
        <select
          class="border border-border rounded px-2 py-1 bg-background text-foreground"
          bind:value={archiveQueueProvider}
          onchange={() => loadArchiveQueue(1)}
        >
          <option value="">provider 전체</option>
          <option value="claude">Claude</option>
          <option value="gemini">Gemini</option>
          <option value="codex">Codex</option>
        </select>
        <button
          class="px-2 py-1 rounded bg-muted hover:bg-secondary text-muted-foreground"
          onclick={() => loadArchiveQueue(archiveQueuePage)}
          disabled={archiveQueueLoading}
        >{archiveQueueLoading ? '갱신 중...' : '요청 갱신'}</button>
      </div>
      {#if archiveQueueError}
        <p class="text-red-500 mb-2">{archiveQueueError}</p>
      {:else if archiveRequests.length === 0}
        <p class="text-muted-foreground">표시할 Plan Archive LLM 요청이 없습니다.</p>
      {:else}
        <div class="overflow-auto">
          <table class="w-full min-w-[780px]">
            <thead>
              <tr class="text-left text-muted-foreground border-b border-border">
                <th class="pb-2 pr-3 font-medium">ID</th>
                <th class="pb-2 pr-3 font-medium">caller</th>
                <th class="pb-2 pr-3 font-medium">상태</th>
                <th class="pb-2 pr-3 font-medium">요청</th>
                <th class="pb-2 pr-3 font-medium">provider/model</th>
                <th class="pb-2 pr-3 font-medium">profile</th>
                <th class="pb-2 font-medium">error/retry</th>
              </tr>
            </thead>
            <tbody>
              {#each archiveRequests as request (request.id)}
                <tr class="border-b border-border/60">
                  <td class="py-2 pr-3 font-mono">#{request.id}</td>
                  <td class="py-2 pr-3">
                    <div class="font-mono max-w-[12rem] truncate" title={request.caller_id}>{request.caller_id}</div>
                    <div class="text-muted-foreground">{request.caller_type}</div>
                  </td>
                  <td class="py-2 pr-3">
                    <span class="rounded px-2 py-1 {getStatusClass(request.status)}">{request.status}</span>
                  </td>
                  <td class="py-2 pr-3 whitespace-nowrap">{formatDateTime(request.requested_at)}</td>
                  <td class="py-2 pr-3">{request.provider || 'claude'} / {request.model || 'inherit'}</td>
                  <td class="py-2 pr-3">
                    {getRequestProfile(request)}
                    <div class="text-muted-foreground">policy detail: /llm</div>
                  </td>
                  <td class="py-2" title={request.pending_block_reason ? formatLLMBlockReason(request.pending_block_reason) : (request.error_message ?? '')}>
                    <div>{getRequestReason(request)}</div>
                    {#if request.status === 'failed'}
                      <button
                        class="mt-1 text-primary hover:text-primary-hover"
                        onclick={async () => { await llmApi.retry(request.id); await refreshArchiveSurfaces(); }}
                      >재시도</button>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div class="mt-2 flex items-center justify-between">
          <span class="text-muted-foreground">전체 {archiveQueueTotal}개, {archiveQueuePage}/{archiveQueuePages}</span>
          <div class="flex gap-2">
            <button
              class="px-2 py-1 rounded bg-muted hover:bg-secondary text-muted-foreground disabled:opacity-50"
              disabled={archiveQueuePage <= 1 || archiveQueueLoading}
              onclick={() => loadArchiveQueue(archiveQueuePage - 1)}
            >이전</button>
            <button
              class="px-2 py-1 rounded bg-muted hover:bg-secondary text-muted-foreground disabled:opacity-50"
              disabled={archiveQueuePage >= archiveQueuePages || archiveQueueLoading}
              onclick={() => loadArchiveQueue(archiveQueuePage + 1)}
            >다음</button>
          </div>
        </div>
      {/if}
    </div>

    <!-- Plan Archive retrieval MVP -->
    <div class="mb-3 rounded border border-border bg-background p-3 text-xs">
      <div class="mb-3 flex items-center justify-between gap-2 flex-wrap">
        <h3 class="font-semibold text-foreground">Plan Archive retrieval</h3>
        <div class="flex items-center gap-2">
          {#if retrievalLoading || metricsLoading}
            <span class="text-muted-foreground">조회 중...</span>
          {/if}
          <button
            class="px-2 py-1 rounded bg-muted hover:bg-secondary text-muted-foreground disabled:opacity-50"
            onclick={loadRetrievalMetrics}
            disabled={metricsLoading}
          >metrics 갱신</button>
        </div>
      </div>

      <form
        class="grid gap-2 lg:grid-cols-[1.2fr_1fr_0.7fr_0.7fr_0.7fr_auto]"
        onsubmit={(e) => { e.preventDefault(); runRetrievalSearch(); }}
      >
        <input
          class="border border-border rounded px-2 py-1 bg-background text-foreground"
          placeholder="키워드, 파일명, 함수명"
          bind:value={retrievalQ}
        />
        <input
          class="border border-border rounded px-2 py-1 bg-background text-foreground font-mono"
          placeholder="파일 경로 filter"
          bind:value={retrievalPath}
        />
        <input
          class="border border-border rounded px-2 py-1 bg-background text-foreground font-mono"
          placeholder="repo_key"
          bind:value={retrievalRepoKey}
        />
        <input
          class="border border-border rounded px-2 py-1 bg-background text-foreground"
          placeholder="category"
          bind:value={retrievalCategory}
        />
        <input
          class="border border-border rounded px-2 py-1 bg-background text-foreground"
          placeholder="tags comma"
          bind:value={retrievalTags}
        />
        <button
          type="submit"
          class="px-3 py-1 rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
          disabled={retrievalLoading}
        >{retrievalLoading ? '검색 중...' : 'retrieval 검색'}</button>
        <input
          class="border border-border rounded px-2 py-1 bg-background text-foreground"
          placeholder="intent"
          bind:value={retrievalIntent}
        />
        <input
          class="border border-border rounded px-2 py-1 bg-background text-foreground"
          placeholder="scope"
          bind:value={retrievalScope}
        />
        <input
          class="border border-border rounded px-2 py-1 bg-background text-foreground"
          placeholder="relation_type"
          bind:value={retrievalRelationType}
        />
        <div class="grid grid-cols-2 gap-2">
          <input
            class="border border-border rounded px-2 py-1 bg-background text-foreground"
            type="date"
            aria-label="retrieval date from"
            bind:value={retrievalDateFrom}
          />
          <input
            class="border border-border rounded px-2 py-1 bg-background text-foreground"
            type="date"
            aria-label="retrieval date to"
            bind:value={retrievalDateTo}
          />
        </div>
        <input
          class="border border-border rounded px-2 py-1 bg-background text-foreground"
          type="number"
          min="1"
          max="100"
          aria-label="retrieval result limit"
          bind:value={retrievalLimit}
        />
      </form>

      <div class="mt-3 grid gap-3 xl:grid-cols-[1fr_1fr]">
        <div class="rounded border border-border p-2">
          <div class="mb-2 flex items-center justify-between gap-2">
            <h4 class="font-semibold text-foreground">검색 결과</h4>
            <span class="text-muted-foreground">total {retrievalTotal}</span>
          </div>
          {#if retrievalError}
            <p class="text-red-500">{retrievalError}</p>
          {:else if retrievalResults.length === 0}
            <p class="text-muted-foreground">검색 실행 후 evidence chunk와 source id가 표시됩니다.</p>
          {:else}
            <div class="space-y-3">
              {#each retrievalResults as result, i}
                <div class="border-b border-border/60 pb-3 last:border-0 last:pb-0">
                  <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0">
                      <div class="font-medium text-foreground truncate" title={getResultPlanTitle(result)}>
                        {i + 1}. {getResultPlanTitle(result)}
                      </div>
                      {#if getResultPlanPath(result)}
                        <div class="font-mono text-muted-foreground truncate" title={getResultPlanPath(result)}>
                          {getResultPlanPath(result)}
                        </div>
                      {/if}
                    </div>
                    <span class="rounded bg-muted px-2 py-1 font-mono text-muted-foreground">score {formatScore(result.score)}</span>
                  </div>
                  {#if getScoreDetails(result).length > 0}
                    <div class="mt-1 flex flex-wrap gap-1 text-muted-foreground">
                      {#each getScoreDetails(result) as detail}
                        <span class="rounded bg-muted px-1.5 py-0.5">{detail}</span>
                      {/each}
                    </div>
                  {/if}
                  {#if result.chunks?.length > 0}
                    <div class="mt-2 space-y-1">
                      {#each result.chunks.slice(0, 2) as chunk}
                        <div class="rounded bg-muted px-2 py-1">
                          <div class="mb-1 flex items-center gap-2 text-muted-foreground">
                            <span class="font-mono">chunk #{chunk.id}</span>
                            {#if chunk.section_type}<span>{chunk.section_type}</span>{/if}
                            {#if chunk.heading}<span class="truncate">{chunk.heading}</span>{/if}
                            {#if chunk.score != null}<span class="ml-auto font-mono">{formatScore(chunk.score)}</span>{/if}
                          </div>
                          <p class="line-clamp-2 text-foreground">{chunk.snippet || chunk.text}</p>
                        </div>
                      {/each}
                    </div>
                  {/if}
                  {#if result.file_refs?.length > 0}
                    <div class="mt-2 flex flex-wrap gap-1">
                      {#each result.file_refs.slice(0, 4) as ref}
                        <span
                          class="rounded px-1.5 py-0.5 font-mono {ref.source_type === 'git_changed' || ref.source_type === 'downstream_sync' ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200' : 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200'}"
                          title={ref.commit_sha ? `${ref.path} @ ${ref.commit_sha}` : ref.path}
                        >#{ref.id} {ref.repo_key || 'monitor-page'} · {ref.source_type}: {ref.path}</span>
                      {/each}
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          {/if}
        </div>

        <div class="grid gap-3">
          <div class="rounded border border-border p-2">
            <div class="mb-2 flex items-center justify-between gap-2">
              <h4 class="font-semibold text-foreground">후속 통계</h4>
              {#if retrievalMetrics}
                <span class="text-muted-foreground">plans {retrievalMetrics.total_plans ?? 0}</span>
              {/if}
            </div>
            {#if metricsError}
              <p class="text-red-500">{metricsError}</p>
            {:else if !retrievalMetrics}
              <p class="text-muted-foreground">metrics API 결과를 기다리는 중입니다.</p>
            {:else}
              <div class="grid gap-2 sm:grid-cols-5">
                <div class="rounded bg-muted px-2 py-2">
                  <div class="text-muted-foreground">7d follow-up</div>
                  <div class="font-semibold text-foreground">{formatRate(retrievalMetrics.followup_rates?.days_7)}</div>
                </div>
                <div class="rounded bg-muted px-2 py-2">
                  <div class="text-muted-foreground">14d follow-up</div>
                  <div class="font-semibold text-foreground">{formatRate(retrievalMetrics.followup_rates?.days_14)}</div>
                </div>
                <div class="rounded bg-muted px-2 py-2">
                  <div class="text-muted-foreground">30d follow-up</div>
                  <div class="font-semibold text-foreground">{formatRate(retrievalMetrics.followup_rates?.days_30)}</div>
                </div>
                <div class="rounded bg-muted px-2 py-2">
                  <div class="text-muted-foreground">chain max</div>
                  <div class="font-semibold text-foreground">{retrievalMetrics.chain_depth_max ?? 0}</div>
                </div>
                <div class="rounded bg-muted px-2 py-2">
                  <div class="text-muted-foreground">cross-repo plans</div>
                  <div class="font-semibold text-foreground">{retrievalMetrics.cross_repo_plan_count ?? 0}</div>
                </div>
              </div>

              <div class="mt-3 grid gap-3 lg:grid-cols-2">
                <div>
                  <div class="mb-1 font-medium text-foreground">Top file refs</div>
                  {#if (retrievalMetrics.top_file_refs ?? []).length === 0}
                    <p class="text-muted-foreground">file ref 집계가 없습니다.</p>
                  {:else}
                    <div class="space-y-1">
                      {#each (retrievalMetrics.top_file_refs ?? []).slice(0, 5) as ref}
                        <div class="rounded bg-muted px-2 py-1">
                          <div class="font-mono truncate" title={ref.path}>{ref.repo_key || 'monitor-page'} · {ref.path}</div>
                          <div class="text-muted-foreground">total {ref.count} / mentioned {ref.mentioned_count} / changed {ref.changed_count}</div>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
                <div>
                  <div class="mb-1 font-medium text-foreground">누락 후보 파일군</div>
                  {#if (retrievalMetrics.missing_file_candidates ?? []).length === 0}
                    <p class="text-muted-foreground">누락 후보가 없습니다.</p>
                  {:else}
                    <div class="space-y-1">
                      {#each (retrievalMetrics.missing_file_candidates ?? []).slice(0, 5) as candidate}
                        <div class="rounded bg-muted px-2 py-1">
                          <div class="font-medium">{candidate.module || 'unknown'} <span class="text-muted-foreground">({candidate.count})</span></div>
                          <div class="font-mono text-muted-foreground truncate" title={(candidate.paths ?? []).join(', ')}>
                            {(candidate.paths ?? []).slice(0, 3).join(', ')}
                          </div>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
              </div>

              {#if Object.keys(retrievalMetrics.relation_counts ?? {}).length > 0}
                <div class="mt-3 flex flex-wrap gap-1">
                  {#each Object.entries(retrievalMetrics.relation_counts ?? {}) as [type, count]}
                    <span class="rounded bg-muted px-1.5 py-0.5">{type} {count}</span>
                  {/each}
                </div>
              {/if}
              {#if Object.keys(retrievalMetrics.repo_counts ?? {}).length > 0}
                <div class="mt-3">
                  <div class="mb-1 font-medium text-foreground">Repo evidence</div>
                  <div class="flex flex-wrap gap-1">
                    {#each Object.entries(retrievalMetrics.repo_counts ?? {}) as [repoKey, count]}
                      <span class="rounded bg-muted px-1.5 py-0.5 font-mono">{repoKey} {count}</span>
                    {/each}
                  </div>
                </div>
              {/if}
              {#if (retrievalMetrics.downstream_sync_missing_candidates ?? []).length > 0}
                <div class="mt-3 rounded border border-yellow-300 bg-yellow-50 px-2 py-2 text-yellow-800 dark:border-yellow-800 dark:bg-yellow-950 dark:text-yellow-200">
                  <div class="mb-1 font-medium">Downstream sync evidence 후보</div>
                  <div class="space-y-1">
                    {#each (retrievalMetrics.downstream_sync_missing_candidates ?? []).slice(0, 4) as candidate}
                      <div class="font-mono truncate" title={candidate.path}>
                        {candidate.repo_key} · {candidate.path} ({candidate.count})
                      </div>
                    {/each}
                  </div>
                </div>
              {/if}
            {/if}
          </div>

          <div class="rounded border border-border p-2">
            <div class="mb-2 flex items-center justify-between gap-2">
              <h4 class="font-semibold text-foreground">Archive index</h4>
              {#if indexResult}
                <span class="text-muted-foreground">{indexResult.dry_run ? 'dry-run' : 'applied'}</span>
              {/if}
            </div>
            <div class="grid gap-2 sm:grid-cols-[0.8fr_0.8fr_auto_auto]">
              <input
                class="border border-border rounded px-2 py-1 bg-background text-foreground"
                type="number"
                min="1"
                aria-label="archive index limit"
                bind:value={indexLimit}
              />
              <input
                class="border border-border rounded px-2 py-1 bg-background text-foreground"
                type="date"
                aria-label="archive index since"
                bind:value={indexSince}
              />
              <label class="flex items-center gap-1 text-muted-foreground">
                <input type="checkbox" bind:checked={indexForce} />
                force
              </label>
              <div class="flex gap-2">
                <button
                  class="px-2 py-1 rounded bg-muted hover:bg-secondary text-muted-foreground disabled:opacity-50"
                  onclick={() => runArchiveIndex(false)}
                  disabled={indexLoading}
                >dry-run</button>
                <button
                  class="px-2 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
                  onclick={() => runArchiveIndex(true)}
                  disabled={indexLoading || indexResult?.dry_run !== true}
                >apply index</button>
              </div>
            </div>
            {#if indexError}
              <p class="mt-2 text-red-500">{indexError}</p>
            {/if}
            {#if indexResult}
              <div class="mt-2 flex flex-wrap gap-2 text-muted-foreground">
                <span class="rounded bg-muted px-2 py-1">indexed {indexResult.indexed}</span>
                <span class="rounded bg-muted px-2 py-1">failed {indexResult.failed}</span>
                <span class="rounded bg-muted px-2 py-1">skipped {indexResult.skipped}</span>
                {#if indexResult.run_id != null}
                  <span class="rounded bg-muted px-2 py-1">run #{indexResult.run_id}</span>
                {/if}
              </div>
              {#if (indexResult.errors ?? []).length > 0}
                <div class="mt-2 text-red-500">
                  {#each (indexResult.errors ?? []).slice(0, 3) as item}
                    <div>{item}</div>
                  {/each}
                </div>
              {/if}
            {/if}
            <div class="mt-3 border-t border-border pt-3">
              <div class="mb-2 flex items-center justify-between gap-2">
                <div>
                  <div class="font-medium text-foreground">Cross-repo index</div>
                  <div class="text-muted-foreground">
                    {#if selectedRecord}
                      #{selectedRecord.id} {selectedRecord.title || selectedRecord.file_path}
                    {:else}
                      레코드를 선택하면 repo evidence를 색인할 수 있습니다.
                    {/if}
                  </div>
                </div>
                <div class="flex gap-2">
                  <button
                    class="px-2 py-1 rounded bg-muted hover:bg-secondary text-muted-foreground disabled:opacity-50"
                    onclick={() => runCrossRepoIndex(false)}
                    disabled={crossRepoIndexLoading || !selectedRecord}
                  >cross dry-run</button>
                  <button
                    class="px-2 py-1 rounded bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
                    onclick={() => runCrossRepoIndex(true)}
                    disabled={crossRepoIndexLoading || !selectedRecord || crossRepoIndexResult?.dry_run !== true}
                  >apply cross</button>
                </div>
              </div>
              {#if crossRepoIndexResult}
                <div class="flex flex-wrap gap-2 text-muted-foreground">
                  <span class="rounded bg-muted px-2 py-1">{crossRepoIndexResult.dry_run ? 'dry-run' : 'applied'}</span>
                  <span class="rounded bg-muted px-2 py-1">repos {crossRepoIndexResult.repos}</span>
                  <span class="rounded bg-muted px-2 py-1">indexed {crossRepoIndexResult.indexed}</span>
                  <span class="rounded bg-muted px-2 py-1">failed {crossRepoIndexResult.failed}</span>
                  <span class="rounded bg-muted px-2 py-1">skipped {crossRepoIndexResult.skipped}</span>
                </div>
                {#if (crossRepoIndexResult.errors ?? []).length > 0}
                  <div class="mt-2 text-red-500">
                    {#each (crossRepoIndexResult.errors ?? []).slice(0, 3) as item}
                      <div>{item}</div>
                    {/each}
                  </div>
                {/if}
              {/if}
            </div>
          </div>
        </div>
      </div>
    </div>

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
              <th class="pb-2 pr-3 font-medium whitespace-nowrap">Execution</th>
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
                <td class="py-2 pr-3 text-xs">
                  <span class="inline-block rounded px-1.5 py-0.5 {getExecutionStateClass(record.execution_state)}">
                    {record.execution_state ?? getAttemptStatus(record.latest_attempt)}
                  </span>
                  {#if record.latest_attempt}
                    <div class="mt-0.5 text-muted-foreground">
                      {getAttemptProfile(record.latest_attempt)} · {formatDateTime(getAttemptTime(record.latest_attempt))}
                    </div>
                  {:else if record.next_available_at}
                    <div class="mt-0.5 text-muted-foreground">next {formatDateTime(record.next_available_at)}</div>
                  {/if}
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
    <div class="w-80 flex-shrink-0 border-l border-border pl-4 flex flex-col gap-2">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-semibold text-foreground truncate">
          {selectedRecord.file_path.split(/[\\/]/).pop()}
        </h3>
        <button
          class="text-muted-foreground hover:text-foreground text-xs"
          onclick={() => { selectedRecord = null; }}
        >닫기</button>
      </div>
      <p class="text-xs text-muted-foreground">완료일: {formatDate(selectedRecord.archived_at)}</p>
      <p class="text-xs text-muted-foreground">
        카테고리: <span class="font-medium">{getCategoryFromPath(selectedRecord.file_path)}</span>
      </p>
      <!-- 탭 버튼 -->
      <div class="flex gap-1 border-b border-border pb-1">
        <button
          class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'content' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
          onclick={() => { detailTab = 'content'; }}
        >내용</button>
        <button
          class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'memo' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
          onclick={() => { detailTab = 'memo'; }}
        >메모</button>
        <button
          class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'analyze' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
          onclick={() => { detailTab = 'analyze'; }}
        >분석</button>
        <button
          class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'history' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
          onclick={openSelectedExecutionHistory}
        >실행</button>
      </div>
      <div class="flex-1 overflow-auto">
        {#if detailTab === 'content'}
          <PlanViewer filePath={selectedRecord.file_path} recordId={selectedRecord.id} />
        {:else if detailTab === 'memo'}
          <MemoEditor filePath={selectedRecord.file_path} />
        {:else if detailTab === 'analyze'}
          <div class="space-y-3 text-xs">
            <div class="rounded border border-border p-3">
              <div class="grid gap-2">
                <label class="grid gap-1">
                  <span class="text-muted-foreground">provider</span>
                  <select class="rounded border border-border bg-background px-2 py-1" bind:value={analyzeProvider}>
                    <option value="codex">codex</option>
                    <option value="claude">claude</option>
                    <option value="gemini">gemini</option>
                  </select>
                </label>
                <label class="grid gap-1">
                  <span class="text-muted-foreground">model</span>
                  <input
                    class="rounded border border-border bg-background px-2 py-1"
                    list="plan-archive-analyze-models"
                    placeholder="gpt-5.5 / gemini-3.1-pro-preview / claude-opus-4-6"
                    bind:value={analyzeModel}
                  />
                  <datalist id="plan-archive-analyze-models">
                    <option value="gpt-5.5"></option>
                    <option value="gpt-5.2"></option>
                    <option value="gemini-3.1-pro-preview"></option>
                    <option value="gemini-3-flash-preview"></option>
                    <option value="claude-opus-4-6"></option>
                  </datalist>
                </label>
                <label class="grid gap-1">
                  <span class="text-muted-foreground">timeout</span>
                  <input class="rounded border border-border bg-background px-2 py-1" type="number" min="1" max="3600" bind:value={analyzeTimeout} />
                </label>
              </div>
              <div class="mt-3 flex flex-wrap gap-2">
                <button
                  class="rounded bg-blue-600 px-3 py-1 text-white disabled:opacity-50"
                  disabled={analyzeLoading}
                  onclick={() => runManualAnalyze('preview')}
                >{analyzeLoading ? '실행 중...' : 'Preview'}</button>
                <button
                  class="rounded bg-muted px-3 py-1 text-muted-foreground hover:bg-secondary disabled:opacity-50"
                  disabled={analyzeLoading || !analyzeResult?.success}
                  onclick={() => { confirmingApply = true; }}
                >DB 저장</button>
              </div>
              <p class="mt-2 text-muted-foreground">Preview는 DB 저장 없음. Apply만 category/tags/summary를 저장합니다.</p>
            </div>

            {#if confirmingApply}
              <div class="rounded border border-amber-300 bg-amber-50 p-3 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
                <p>현재 preview 결과를 DB에 저장합니다.</p>
                <div class="mt-2 flex gap-2">
                  <button class="rounded bg-amber-600 px-3 py-1 text-white" onclick={() => runManualAnalyze('apply')}>확인</button>
                  <button class="rounded bg-background px-3 py-1 text-muted-foreground" onclick={() => { confirmingApply = false; }}>취소</button>
                </div>
              </div>
            {/if}

            {#if analyzeError}
              <p class="rounded border border-red-300 bg-red-50 p-2 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{analyzeError}</p>
            {/if}

            {#if analyzeResult}
              <div class="rounded border border-border p-3">
                <div class="mb-2 flex items-center justify-between gap-2">
                  <div>
                    <span class="font-semibold">{analyzeResult.success ? '성공' : '실패'}</span>
                    <span class="text-muted-foreground"> · {analyzeResult.provider}/{analyzeResult.model} · {analyzeResult.elapsed_ms}ms</span>
                    {#if analyzeResult.prompt_policy_id}
                      <span class="text-muted-foreground"> · {analyzeResult.prompt_policy_id}/{analyzeResult.prompt_policy_version}</span>
                    {/if}
                  </div>
                  <button class="rounded bg-muted px-2 py-1 text-muted-foreground hover:bg-secondary" onclick={copyAnalyzeResult}>복사</button>
                </div>
                {#if analyzeResult.error}
                  <p class="mb-2 text-red-600 dark:text-red-300">{analyzeResult.error}</p>
                {/if}
                {#if analyzeResult.warnings.length > 0}
                  <div class="mb-2 text-amber-700 dark:text-amber-300">{analyzeResult.warnings.join(', ')}</div>
                {/if}
                <div class="grid gap-2">
                  <div class="rounded bg-muted p-2">
                    <div class="text-muted-foreground">category</div>
                    <div class="font-medium">{String(analyzeResult.result.category ?? '-')}</div>
                  </div>
                  <div class="rounded bg-muted p-2">
                    <div class="text-muted-foreground">tags</div>
                    <div>{Array.isArray(analyzeResult.result.tags) ? analyzeResult.result.tags.join(', ') : String(analyzeResult.result.tags ?? '-')}</div>
                  </div>
                  <div class="rounded bg-muted p-2">
                    <div class="text-muted-foreground">summary</div>
                    <div>{String(analyzeResult.result.summary ?? '-')}</div>
                  </div>
                  <div class="rounded bg-muted p-2">
                    <div class="text-muted-foreground">intent / scope</div>
                    <div>{String(analyzeResult.result.intent ?? '-')}</div>
                    <div class="mt-2 flex flex-wrap gap-1">
                      <span class="rounded border border-border bg-background px-2 py-0.5 text-foreground">
                        trigger: {String(analyzeResult.result.trigger ?? '-')}
                      </span>
                      {#if Array.isArray(analyzeResult.result.scope)}
                        {#each analyzeResult.result.scope as item}
                          <span class="rounded border border-border bg-background px-2 py-0.5 text-muted-foreground">{String(item)}</span>
                        {/each}
                      {:else}
                        <span class="rounded border border-border bg-background px-2 py-0.5 text-muted-foreground">{String(analyzeResult.result.scope ?? '-')}</span>
                      {/if}
                    </div>
                  </div>
                </div>
                <pre class="mt-3 max-h-56 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(analyzeResult.result, null, 2)}</pre>
              </div>
            {/if}
          </div>
        {:else}
          <div class="space-y-2 text-xs">
            <div class="rounded border border-border p-3">
              <div class="mb-2 flex items-center justify-between gap-2">
                <div>
                  <div class="font-semibold text-foreground">Archive execution</div>
                  <div class="mt-1 flex flex-wrap gap-1">
                    <span class="rounded px-2 py-0.5 {getArchiveStateClass(selectedRecord.archive_state)}">archive {selectedRecord.archive_state ?? '-'}</span>
                    <span class="rounded px-2 py-0.5 {getExecutionStateClass(selectedRecord.execution_state)}">execution {selectedRecord.execution_state ?? '-'}</span>
                  </div>
                </div>
                <button
                  class="rounded bg-muted px-2 py-1 text-muted-foreground hover:bg-secondary disabled:opacity-50"
                  onclick={refreshSelectedExecutionHistory}
                  disabled={selectedExecutionHistoryLoading}
                >갱신</button>
              </div>
              {#if selectedRecord.next_available_at}
                <p class="text-muted-foreground">next available {formatDateTime(selectedRecord.next_available_at)}</p>
              {/if}
            </div>

            {#if selectedExecutionHistoryError}
              <p class="rounded border border-red-300 bg-red-50 p-2 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{selectedExecutionHistoryError}</p>
            {:else if selectedExecutionHistoryLoading}
              <p class="text-muted-foreground">실행 이력 로드 중...</p>
            {:else if selectedExecutionHistory.length === 0}
              <p class="text-muted-foreground">실행 이력이 없습니다.</p>
            {:else}
              <div class="space-y-2">
                {#each selectedExecutionHistory as attempt, index (attempt.id ?? `${attempt.llm_request_id ?? 'attempt'}-${index}`)}
                  <div class="rounded border border-border p-2">
                    <div class="flex items-center justify-between gap-2">
                      <span class="rounded px-2 py-0.5 {getExecutionStateClass(getAttemptStatus(attempt))}">{getAttemptStatus(attempt)}</span>
                      <span class="text-muted-foreground">{formatDateTime(getAttemptTime(attempt))}</span>
                    </div>
                    <div class="mt-1 font-mono text-muted-foreground">{getAttemptProfile(attempt)}</div>
                    {#if attempt.llm_request_id}
                      <div class="mt-1 text-muted-foreground">LLM request #{attempt.llm_request_id}</div>
                    {/if}
                    {#if attempt.error_message}
                      <div class="mt-1 truncate text-red-600 dark:text-red-300" title={attempt.error_message}>{attempt.error_message}</div>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    </div>
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
