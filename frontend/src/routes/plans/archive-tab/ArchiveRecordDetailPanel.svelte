<script lang="ts">
  import {
    planRecordsApi,
    type PlanRecord,
    type PlanArchiveExecutionAttempt,
    type PlanRecordRelation,
  } from '$lib/api/plan-records';
  import { llmApi } from '$lib/api';
  import type { ProviderInfo } from '$lib/api/system';
  import MemoEditor from '../MemoEditor.svelte';
  import PlanViewer from '../PlanViewer.svelte';
  import type { ArchiveResidualState } from './planArchiveResidualState.svelte';

  let {
    record,
    relations,
    relationsLoading,
    executionHistory,
    executionHistoryLoading,
    executionHistoryError,
    detailTab,
    providers,
    state,
    showToast,
    onClose,
    onTabChange,
    onRefreshHistory,
    onSaved,
  }: {
    record: PlanRecord;
    relations: PlanRecordRelation[];
    relationsLoading: boolean;
    executionHistory: PlanArchiveExecutionAttempt[];
    executionHistoryLoading: boolean;
    executionHistoryError: string;
    detailTab: 'content' | 'memo' | 'analyze' | 'history';
    providers: ProviderInfo[];
    state: ArchiveResidualState;
    showToast: (msg: string) => void;
    onClose: () => void;
    onTabChange: (tab: 'content' | 'memo' | 'analyze' | 'history') => void;
    onRefreshHistory: () => void;
    onSaved: (recordId: number) => void;
  } = $props();

  async function requestAnalysis() {
    if (!state.queueAnalyzeProvider) { showToast('provider를 선택하세요'); return; }
    state.queueAnalyzeLoading = true;
    try {
      const res = await planRecordsApi.reanalyze(record.id, {
        provider: state.queueAnalyzeProvider,
        model: state.queueAnalyzeModel || undefined,
      });
      if (res.queued) {
        showToast(`분석 요청 등록 (id=${res.request_id}, ${res.provider}/${res.model || 'default'})`);
      } else {
        showToast(`이미 pending 요청 있음 (id=${res.request_id})`);
      }
      try {
        const detail = await planRecordsApi.get(record.id);
        state.appliedRequestId = detail.applied_request_id ?? null;
      } catch {
        state.appliedRequestId = null;
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : '분석 요청 실패');
    } finally {
      state.queueAnalyzeLoading = false;
    }
  }

  async function runManualAnalyze(mode: 'preview' | 'apply') {
    state.manualAnalyzeLoading = true;
    state.manualAnalyzeError = '';
    state.manualConfirmingApply = false;
    try {
      const result = await planRecordsApi.analyzeRecord(record.id, {
        mode,
        provider: state.manualAnalyzeProvider || undefined,
        model: state.manualAnalyzeModel || undefined,
        timeout_seconds: Number(state.manualAnalyzeTimeout),
      });
      state.manualAnalyzeResult = result;
      if (result.saved) {
        onSaved(result.record_id ?? record.id);
      }
      showToast(result.saved ? 'DB 저장 완료' : result.success ? '분석 완료' : (result.error || '분석 실패'));
    } catch (e) {
      state.manualAnalyzeError = e instanceof Error ? e.message : '분석 요청 실패';
    } finally {
      state.manualAnalyzeLoading = false;
    }
  }

  async function copyAnalyzeResult() {
    if (!state.manualAnalyzeResult) return;
    await navigator.clipboard.writeText(JSON.stringify(state.manualAnalyzeResult.result, null, 2));
    showToast('분석 결과를 복사했습니다.');
  }

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

  function getCategoryFromPath(filePath: string): string {
    const CATEGORIES = ['feature', 'bugfix', 'refactor', 'infra', 'docs', 'test', 'misc'];
    const name = filePath.split(/[\\/]/).pop() ?? filePath;
    const noDate = name.replace(/^\d{4}-\d{2}-\d{2}_/, '');
    const prefix = noDate.split('-')[0].toLowerCase();
    const map: Record<string, string> = {
      feat: 'feature', fix: 'bugfix', hotfix: 'bugfix',
      refactor: 'refactor', ref: 'refactor',
      chore: 'infra', ci: 'infra', infra: 'infra', build: 'infra',
      docs: 'docs', doc: 'docs', test: 'test',
    };
    const parts = filePath.split(/[\\/]/);
    if (parts.length >= 2) {
      const parent = parts[parts.length - 2].toLowerCase();
      if (CATEGORIES.includes(parent)) return parent;
    }
    return map[prefix] ?? 'misc';
  }

  function relationLabel(type: string) {
    const labels: Record<string, string> = {
      predecessor: '선행', successor: '후속',
      unresolved_followup: '미해결 후속', cause: '원인',
      guard: '방어', supersedes: '대체', mentions: '언급'
    };
    return labels[type] ?? type;
  }

  function relationPeer(relation: PlanRecordRelation) {
    return relation.direction === 'incoming' ? relation.source : relation.target;
  }

  function getExecutionStateClass(state: string | null | undefined) {
    switch (state) {
      case 'queued': case 'pending':
        return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-200';
      case 'running': case 'processing':
        return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200';
      case 'failed':
        return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200';
      case 'completed': case 'success':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200';
      default:
        return 'bg-muted text-muted-foreground';
    }
  }

  function getArchiveStateClass(s: string | null | undefined) {
    switch (s) {
      case 'ready': case 'indexed':
        return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200';
      case 'blocked': case 'stale':
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
</script>

<div class="w-80 flex-shrink-0 border-l border-border pl-4 flex flex-col gap-2">
  <div class="flex items-center justify-between">
    <h3 class="text-xs font-semibold text-foreground truncate">
      {record.file_path.split(/[\\/]/).pop()}
    </h3>
    <button
      class="text-muted-foreground hover:text-foreground text-xs"
      onclick={onClose}
    >닫기</button>
  </div>
  <p class="text-xs text-muted-foreground">완료일: {formatDate(record.archived_at)}</p>
  <p class="text-xs text-muted-foreground">
    카테고리: <span class="font-medium">{getCategoryFromPath(record.file_path)}</span>
  </p>
  <div class="rounded border border-border p-2 text-xs">
    <div class="mb-1 flex items-center justify-between">
      <span class="font-semibold text-foreground">계획 관계</span>
      {#if relations.some((relation) => relation.relation_type === 'unresolved_followup')}
        <span class="rounded bg-red-100 px-1.5 py-0.5 text-red-700 dark:bg-red-900 dark:text-red-200">미해결 후속</span>
      {/if}
    </div>
    {#if relationsLoading}
      <p class="text-muted-foreground">불러오는 중...</p>
    {:else if relations.length === 0}
      <p class="text-muted-foreground">관계 없음</p>
    {:else}
      <div class="space-y-1">
        {#each relations.slice(0, 5) as relation}
          <div class="flex min-w-0 items-center gap-1">
            <span class="shrink-0 rounded bg-muted px-1 py-0.5 text-muted-foreground">{relation.direction === 'incoming' ? 'in' : 'out'}</span>
            <span class="shrink-0 rounded px-1 py-0.5 {relation.relation_type === 'unresolved_followup' ? 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200' : 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200'}">
              {relationLabel(relation.relation_type)}
            </span>
            <span class="truncate text-muted-foreground" title={relationPeer(relation).file_path}>
              {relationPeer(relation).title || relationPeer(relation).file_path.split(/[\\/]/).pop()}
            </span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
  <!-- 탭 버튼 -->
  <div class="flex gap-1 border-b border-border pb-1">
    <button
      class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'content' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => onTabChange('content')}
    >내용</button>
    <button
      class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'memo' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => onTabChange('memo')}
    >메모</button>
    <button
      class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'analyze' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => onTabChange('analyze')}
    >분석</button>
    <button
      class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'history' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => { onTabChange('history'); onRefreshHistory(); }}
    >실행</button>
  </div>
  <!-- 분석 요청 -->
  <div class="border-t border-border pt-2">
    <div class="flex items-center gap-2 mb-1">
      <p class="text-xs font-semibold text-foreground">LLM 분석 요청</p>
      {#if state.appliedRequestId}
        <span class="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-200">DB 반영됨 #{state.appliedRequestId}</span>
      {/if}
    </div>
    <div class="flex gap-1 mb-1">
      <select
        class="flex-1 border border-border rounded px-1.5 py-0.5 text-xs bg-background text-foreground"
        bind:value={state.queueAnalyzeProvider}
      >
        <option value="">provider 선택</option>
        {#each providers as p}
          <option value={p.key}>{p.key}{p.key === 'codex' ? ' (profile 불필요)' : ''}</option>
        {/each}
      </select>
      <input
        class="w-28 border border-border rounded px-1.5 py-0.5 text-xs bg-background text-foreground"
        placeholder="model (선택)"
        bind:value={state.queueAnalyzeModel}
      />
    </div>
    <button
      class="w-full px-2 py-1 text-xs rounded bg-blue-100 hover:bg-blue-200 text-blue-700 dark:bg-blue-900 dark:hover:bg-blue-800 dark:text-blue-200 disabled:opacity-50"
      onclick={requestAnalysis}
      disabled={state.queueAnalyzeLoading || !state.queueAnalyzeProvider}
    >{state.queueAnalyzeLoading ? '요청 중...' : '분석 요청'}</button>
  </div>

  <div class="flex-1 overflow-auto">
    {#if detailTab === 'content'}
      <PlanViewer filePath={record.file_path} recordId={record.id} />
    {:else if detailTab === 'memo'}
      <MemoEditor filePath={record.file_path} />
    {:else if detailTab === 'analyze'}
      <div class="space-y-3 text-xs">
        <div class="rounded border border-border p-3">
          <div class="grid gap-2">
            <label class="grid gap-1">
              <span class="text-muted-foreground">provider</span>
              <select class="rounded border border-border bg-background px-2 py-1" bind:value={state.manualAnalyzeProvider}>
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
                bind:value={state.manualAnalyzeModel}
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
              <input class="rounded border border-border bg-background px-2 py-1" type="number" min="1" max="3600" bind:value={state.manualAnalyzeTimeout} />
            </label>
          </div>
          <div class="mt-3 flex flex-wrap gap-2">
            <button
              class="rounded bg-blue-600 px-3 py-1 text-white disabled:opacity-50"
              disabled={state.manualAnalyzeLoading}
              onclick={() => runManualAnalyze('preview')}
            >{state.manualAnalyzeLoading ? '실행 중...' : 'Preview'}</button>
            <button
              class="rounded bg-muted px-3 py-1 text-muted-foreground hover:bg-secondary disabled:opacity-50"
              disabled={state.manualAnalyzeLoading || !state.manualAnalyzeResult?.success}
              onclick={() => { state.manualConfirmingApply = true; }}
            >DB 저장</button>
          </div>
          <p class="mt-2 text-muted-foreground">Preview는 DB 저장 없음. Apply만 category/tags/summary를 저장합니다.</p>
        </div>

        {#if state.manualConfirmingApply}
          <div class="rounded border border-amber-300 bg-amber-50 p-3 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
            <p>현재 preview 결과를 DB에 저장합니다.</p>
            <div class="mt-2 flex gap-2">
              <button class="rounded bg-amber-600 px-3 py-1 text-white" onclick={() => runManualAnalyze('apply')}>확인</button>
              <button class="rounded bg-background px-3 py-1 text-muted-foreground" onclick={() => { state.manualConfirmingApply = false; }}>취소</button>
            </div>
          </div>
        {/if}

        {#if state.manualAnalyzeError}
          <p class="rounded border border-red-300 bg-red-50 p-2 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{state.manualAnalyzeError}</p>
        {/if}

        {#if state.manualAnalyzeResult}
          <div class="rounded border border-border p-3">
            <div class="mb-2 flex items-center justify-between gap-2">
              <div>
                <span class="font-semibold">{state.manualAnalyzeResult.success ? '성공' : '실패'}</span>
                <span class="text-muted-foreground"> · {state.manualAnalyzeResult.provider}/{state.manualAnalyzeResult.model} · {state.manualAnalyzeResult.elapsed_ms}ms</span>
                {#if state.manualAnalyzeResult.prompt_policy_id}
                  <span class="text-muted-foreground"> · {state.manualAnalyzeResult.prompt_policy_id}/{state.manualAnalyzeResult.prompt_policy_version}</span>
                {/if}
              </div>
              <button class="rounded bg-muted px-2 py-1 text-muted-foreground hover:bg-secondary" onclick={copyAnalyzeResult}>복사</button>
            </div>
            {#if state.manualAnalyzeResult.error}
              <p class="mb-2 text-red-600 dark:text-red-300">{state.manualAnalyzeResult.error}</p>
            {/if}
            {#if state.manualAnalyzeResult.warnings.length > 0}
              <div class="mb-2 text-amber-700 dark:text-amber-300">{state.manualAnalyzeResult.warnings.join(', ')}</div>
            {/if}
            <div class="grid gap-2">
              <div class="rounded bg-muted p-2">
                <div class="text-muted-foreground">category</div>
                <div class="font-medium">{String(state.manualAnalyzeResult.result.category ?? '-')}</div>
              </div>
              <div class="rounded bg-muted p-2">
                <div class="text-muted-foreground">tags</div>
                <div>{Array.isArray(state.manualAnalyzeResult.result.tags) ? state.manualAnalyzeResult.result.tags.join(', ') : String(state.manualAnalyzeResult.result.tags ?? '-')}</div>
              </div>
              <div class="rounded bg-muted p-2">
                <div class="text-muted-foreground">summary</div>
                <div>{String(state.manualAnalyzeResult.result.summary ?? '-')}</div>
              </div>
              <div class="rounded bg-muted p-2">
                <div class="text-muted-foreground">intent / scope</div>
                <div>{String(state.manualAnalyzeResult.result.intent ?? '-')}</div>
                <div class="mt-2 flex flex-wrap gap-1">
                  <span class="rounded border border-border bg-background px-2 py-0.5 text-foreground">
                    trigger: {String(state.manualAnalyzeResult.result.trigger ?? '-')}
                  </span>
                  {#if Array.isArray(state.manualAnalyzeResult.result.scope)}
                    {#each state.manualAnalyzeResult.result.scope as item}
                      <span class="rounded border border-border bg-background px-2 py-0.5 text-muted-foreground">{String(item)}</span>
                    {/each}
                  {:else}
                    <span class="rounded border border-border bg-background px-2 py-0.5 text-muted-foreground">{String(state.manualAnalyzeResult.result.scope ?? '-')}</span>
                  {/if}
                </div>
              </div>
            </div>
            <pre class="mt-3 max-h-56 overflow-auto rounded bg-muted p-2 text-[11px]">{JSON.stringify(state.manualAnalyzeResult.result, null, 2)}</pre>
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
                <span class="rounded px-2 py-0.5 {getArchiveStateClass(record.archive_state)}">archive {record.archive_state ?? '-'}</span>
                <span class="rounded px-2 py-0.5 {getExecutionStateClass(record.execution_state)}">execution {record.execution_state ?? '-'}</span>
              </div>
            </div>
            <button
              class="rounded bg-muted px-2 py-1 text-muted-foreground hover:bg-secondary disabled:opacity-50"
              onclick={onRefreshHistory}
              disabled={executionHistoryLoading}
            >갱신</button>
          </div>
          {#if record.next_available_at}
            <p class="text-muted-foreground">next available {formatDateTime(record.next_available_at)}</p>
          {/if}
        </div>

        {#if executionHistoryError}
          <p class="rounded border border-red-300 bg-red-50 p-2 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">{executionHistoryError}</p>
        {:else if executionHistoryLoading}
          <p class="text-muted-foreground">실행 이력 로드 중...</p>
        {:else if executionHistory.length === 0}
          <p class="text-muted-foreground">실행 이력이 없습니다.</p>
        {:else}
          <div class="space-y-2">
            {#each executionHistory as attempt, index (attempt.id ?? `${attempt.llm_request_id ?? 'attempt'}-${index}`)}
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
