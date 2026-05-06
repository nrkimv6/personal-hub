<script lang="ts">
  import {
    planRecordsApi,
    type PlanRecord,
    type PlanArchiveRetrievalQuery,
    type PlanArchiveRetrievalResult,
  } from '$lib/api/plan-records';
  import type { ArchiveResidualState } from './planArchiveResidualState.svelte';

  let {
    state,
    selectedRecord,
    showToast,
  }: {
    state: ArchiveResidualState;
    selectedRecord: PlanRecord | null;
    showToast: (msg: string) => void;
  } = $props();

  function buildRetrievalFilters(includeLimit = true): PlanArchiveRetrievalQuery {
    const tags = state.retrievalTags
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean);
    const payload: PlanArchiveRetrievalQuery = {};
    if (state.retrievalQ.trim()) payload.q = state.retrievalQ.trim();
    if (state.retrievalDateFrom) payload.date_from = state.retrievalDateFrom;
    if (state.retrievalDateTo) payload.date_to = state.retrievalDateTo;
    if (state.retrievalCategory.trim()) payload.category = state.retrievalCategory.trim();
    if (tags.length > 0) payload.tags = tags;
    if (state.retrievalIntent.trim()) payload.intent = state.retrievalIntent.trim();
    if (state.retrievalScope.trim()) payload.scope = state.retrievalScope.trim();
    if (state.retrievalPath.trim()) payload.path = state.retrievalPath.trim();
    if (state.retrievalRepoKey.trim()) payload.repo_key = state.retrievalRepoKey.trim();
    if (state.retrievalRelationType.trim()) payload.relation_type = state.retrievalRelationType.trim();
    if (includeLimit) {
      const limitValue = Number(state.retrievalLimit);
      payload.limit = Number.isFinite(limitValue) ? limitValue : 10;
    }
    return payload;
  }

  async function runRetrievalSearch() {
    state.retrievalLoading = true;
    state.retrievalError = '';
    try {
      const res = await planRecordsApi.searchArchiveRetrieval(buildRetrievalFilters());
      state.retrievalResults = res.results ?? [];
      state.retrievalTotal = res.total ?? state.retrievalResults.length;
      void loadRetrievalMetrics();
    } catch (e) {
      state.retrievalResults = [];
      state.retrievalTotal = 0;
      state.retrievalError = e instanceof Error ? e.message : 'retrieval 검색 실패';
    } finally {
      state.retrievalLoading = false;
    }
  }

  async function loadRetrievalMetrics() {
    state.metricsLoading = true;
    state.metricsError = '';
    try {
      state.retrievalMetrics = await planRecordsApi.getArchiveRetrievalMetrics(buildRetrievalFilters(false));
    } catch (e) {
      state.retrievalMetrics = null;
      state.metricsError = e instanceof Error ? e.message : 'retrieval metrics 로드 실패';
    } finally {
      state.metricsLoading = false;
    }
  }

  async function runArchiveIndex(apply = false) {
    if (apply && state.indexResult?.dry_run !== true) {
      showToast('dry-run 결과 확인 후 apply를 실행할 수 있습니다.');
      return;
    }
    state.indexLoading = true;
    state.indexError = '';
    try {
      state.indexResult = await planRecordsApi.indexArchiveRecords({
        limit: Number(state.indexLimit),
        force: state.indexForce,
        since: state.indexSince || undefined,
        apply,
      });
      showToast(
        `${state.indexResult.dry_run ? 'Index dry-run' : 'Index apply'}: indexed ${state.indexResult.indexed}, failed ${state.indexResult.failed}, skipped ${state.indexResult.skipped}`
      );
      if (!state.indexResult.dry_run) {
        await loadRetrievalMetrics();
      }
    } catch (e) {
      state.indexError = e instanceof Error ? e.message : 'archive index 실행 실패';
    } finally {
      state.indexLoading = false;
    }
  }

  async function runCrossRepoIndex(apply = false) {
    if (!selectedRecord) return;
    state.crossRepoIndexLoading = true;
    try {
      state.crossRepoIndexResult = await planRecordsApi.indexCrossRepoArchive({
        record_id: selectedRecord.id,
        max_commits: 30,
        apply,
      });
      showToast(
        `Cross-repo ${state.crossRepoIndexResult.dry_run ? 'dry-run' : 'apply'}: repos ${state.crossRepoIndexResult.repos}, indexed ${state.crossRepoIndexResult.indexed}`
      );
      if (apply) await loadRetrievalMetrics();
    } catch (e) {
      showToast(e instanceof Error ? e.message : 'cross-repo index 실패');
    } finally {
      state.crossRepoIndexLoading = false;
    }
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

  export { loadRetrievalMetrics };
</script>

<!-- Plan Archive retrieval MVP -->
<div class="mb-3 rounded border border-border bg-background p-3 text-xs">
  <div class="mb-3 flex items-center justify-between gap-2 flex-wrap">
    <h3 class="font-semibold text-foreground">Plan Archive retrieval</h3>
    <div class="flex items-center gap-2">
      {#if state.retrievalLoading || state.metricsLoading}
        <span class="text-muted-foreground">조회 중...</span>
      {/if}
      <button
        class="px-2 py-1 rounded bg-muted hover:bg-secondary text-muted-foreground disabled:opacity-50"
        onclick={loadRetrievalMetrics}
        disabled={state.metricsLoading}
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
      bind:value={state.retrievalQ}
    />
    <input
      class="border border-border rounded px-2 py-1 bg-background text-foreground font-mono"
      placeholder="파일 경로 filter"
      bind:value={state.retrievalPath}
    />
    <input
      class="border border-border rounded px-2 py-1 bg-background text-foreground font-mono"
      placeholder="repo_key"
      bind:value={state.retrievalRepoKey}
    />
    <input
      class="border border-border rounded px-2 py-1 bg-background text-foreground"
      placeholder="category"
      bind:value={state.retrievalCategory}
    />
    <input
      class="border border-border rounded px-2 py-1 bg-background text-foreground"
      placeholder="tags comma"
      bind:value={state.retrievalTags}
    />
    <button
      type="submit"
      class="px-3 py-1 rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
      disabled={state.retrievalLoading}
    >{state.retrievalLoading ? '검색 중...' : 'retrieval 검색'}</button>
    <input
      class="border border-border rounded px-2 py-1 bg-background text-foreground"
      placeholder="intent"
      bind:value={state.retrievalIntent}
    />
    <input
      class="border border-border rounded px-2 py-1 bg-background text-foreground"
      placeholder="scope"
      bind:value={state.retrievalScope}
    />
    <input
      class="border border-border rounded px-2 py-1 bg-background text-foreground"
      placeholder="relation_type"
      bind:value={state.retrievalRelationType}
    />
    <div class="grid grid-cols-2 gap-2">
      <input
        class="border border-border rounded px-2 py-1 bg-background text-foreground"
        type="date"
        aria-label="retrieval date from"
        bind:value={state.retrievalDateFrom}
      />
      <input
        class="border border-border rounded px-2 py-1 bg-background text-foreground"
        type="date"
        aria-label="retrieval date to"
        bind:value={state.retrievalDateTo}
      />
    </div>
    <input
      class="border border-border rounded px-2 py-1 bg-background text-foreground"
      type="number"
      min="1"
      max="100"
      aria-label="retrieval result limit"
      bind:value={state.retrievalLimit}
    />
  </form>

  <div class="mt-3 grid gap-3 xl:grid-cols-[1fr_1fr]">
    <div class="rounded border border-border p-2">
      <div class="mb-2 flex items-center justify-between gap-2">
        <h4 class="font-semibold text-foreground">검색 결과</h4>
        <span class="text-muted-foreground">total {state.retrievalTotal}</span>
      </div>
      {#if state.retrievalError}
        <p class="text-red-500">{state.retrievalError}</p>
      {:else if state.retrievalResults.length === 0}
        <p class="text-muted-foreground">검색 실행 후 evidence chunk와 source id가 표시됩니다.</p>
      {:else}
        <div class="space-y-3">
          {#each state.retrievalResults as result, i}
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
          {#if state.retrievalMetrics}
            <span class="text-muted-foreground">plans {state.retrievalMetrics.total_plans ?? 0}</span>
          {/if}
        </div>
        {#if state.metricsError}
          <p class="text-red-500">{state.metricsError}</p>
        {:else if !state.retrievalMetrics}
          <p class="text-muted-foreground">metrics API 결과를 기다리는 중입니다.</p>
        {:else}
          <div class="grid gap-2 sm:grid-cols-5">
            <div class="rounded bg-muted px-2 py-2">
              <div class="text-muted-foreground">7d follow-up</div>
              <div class="font-semibold text-foreground">{formatRate(state.retrievalMetrics.followup_rates?.days_7)}</div>
            </div>
            <div class="rounded bg-muted px-2 py-2">
              <div class="text-muted-foreground">14d follow-up</div>
              <div class="font-semibold text-foreground">{formatRate(state.retrievalMetrics.followup_rates?.days_14)}</div>
            </div>
            <div class="rounded bg-muted px-2 py-2">
              <div class="text-muted-foreground">30d follow-up</div>
              <div class="font-semibold text-foreground">{formatRate(state.retrievalMetrics.followup_rates?.days_30)}</div>
            </div>
            <div class="rounded bg-muted px-2 py-2">
              <div class="text-muted-foreground">chain max</div>
              <div class="font-semibold text-foreground">{state.retrievalMetrics.chain_depth_max ?? 0}</div>
            </div>
            <div class="rounded bg-muted px-2 py-2">
              <div class="text-muted-foreground">cross-repo plans</div>
              <div class="font-semibold text-foreground">{state.retrievalMetrics.cross_repo_plan_count ?? 0}</div>
            </div>
          </div>

          <div class="mt-3 grid gap-3 lg:grid-cols-2">
            <div>
              <div class="mb-1 font-medium text-foreground">Top file refs</div>
              {#if (state.retrievalMetrics.top_file_refs ?? []).length === 0}
                <p class="text-muted-foreground">file ref 집계가 없습니다.</p>
              {:else}
                <div class="space-y-1">
                  {#each (state.retrievalMetrics.top_file_refs ?? []).slice(0, 5) as ref}
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
              {#if (state.retrievalMetrics.missing_file_candidates ?? []).length === 0}
                <p class="text-muted-foreground">누락 후보가 없습니다.</p>
              {:else}
                <div class="space-y-1">
                  {#each (state.retrievalMetrics.missing_file_candidates ?? []).slice(0, 5) as candidate}
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

          {#if Object.keys(state.retrievalMetrics.relation_counts ?? {}).length > 0}
            <div class="mt-3 flex flex-wrap gap-1">
              {#each Object.entries(state.retrievalMetrics.relation_counts ?? {}) as [type, count]}
                <span class="rounded bg-muted px-1.5 py-0.5">{type} {count}</span>
              {/each}
            </div>
          {/if}
          {#if Object.keys(state.retrievalMetrics.repo_counts ?? {}).length > 0}
            <div class="mt-3">
              <div class="mb-1 font-medium text-foreground">Repo evidence</div>
              <div class="flex flex-wrap gap-1">
                {#each Object.entries(state.retrievalMetrics.repo_counts ?? {}) as [repoKey, count]}
                  <span class="rounded bg-muted px-1.5 py-0.5 font-mono">{repoKey} {count}</span>
                {/each}
              </div>
            </div>
          {/if}
          {#if (state.retrievalMetrics.downstream_sync_missing_candidates ?? []).length > 0}
            <div class="mt-3 rounded border border-yellow-300 bg-yellow-50 px-2 py-2 text-yellow-800 dark:border-yellow-800 dark:bg-yellow-950 dark:text-yellow-200">
              <div class="mb-1 font-medium">Downstream sync evidence 후보</div>
              <div class="space-y-1">
                {#each (state.retrievalMetrics.downstream_sync_missing_candidates ?? []).slice(0, 4) as candidate}
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
          {#if state.indexResult}
            <span class="text-muted-foreground">{state.indexResult.dry_run ? 'dry-run' : 'applied'}</span>
          {/if}
        </div>
        <div class="grid gap-2 sm:grid-cols-[0.8fr_0.8fr_auto_auto]">
          <input
            class="border border-border rounded px-2 py-1 bg-background text-foreground"
            type="number"
            min="1"
            aria-label="archive index limit"
            bind:value={state.indexLimit}
          />
          <input
            class="border border-border rounded px-2 py-1 bg-background text-foreground"
            type="date"
            aria-label="archive index since"
            bind:value={state.indexSince}
          />
          <label class="flex items-center gap-1 text-muted-foreground">
            <input type="checkbox" bind:checked={state.indexForce} />
            force
          </label>
          <div class="flex gap-2">
            <button
              class="px-2 py-1 rounded bg-muted hover:bg-secondary text-muted-foreground disabled:opacity-50"
              onclick={() => runArchiveIndex(false)}
              disabled={state.indexLoading}
            >dry-run</button>
            <button
              class="px-2 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
              onclick={() => runArchiveIndex(true)}
              disabled={state.indexLoading || state.indexResult?.dry_run !== true}
            >apply index</button>
          </div>
        </div>
        {#if state.indexError}
          <p class="mt-2 text-red-500">{state.indexError}</p>
        {/if}
        {#if state.indexResult}
          <div class="mt-2 flex flex-wrap gap-2 text-muted-foreground">
            <span class="rounded bg-muted px-2 py-1">indexed {state.indexResult.indexed}</span>
            <span class="rounded bg-muted px-2 py-1">failed {state.indexResult.failed}</span>
            <span class="rounded bg-muted px-2 py-1">skipped {state.indexResult.skipped}</span>
            {#if state.indexResult.run_id != null}
              <span class="rounded bg-muted px-2 py-1">run #{state.indexResult.run_id}</span>
            {/if}
          </div>
          {#if (state.indexResult.errors ?? []).length > 0}
            <div class="mt-2 text-red-500">
              {#each (state.indexResult.errors ?? []).slice(0, 3) as item}
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
                disabled={state.crossRepoIndexLoading || !selectedRecord}
              >cross dry-run</button>
              <button
                class="px-2 py-1 rounded bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
                onclick={() => runCrossRepoIndex(true)}
                disabled={state.crossRepoIndexLoading || !selectedRecord || state.crossRepoIndexResult?.dry_run !== true}
              >apply cross</button>
            </div>
          </div>
          {#if state.crossRepoIndexResult}
            <div class="flex flex-wrap gap-2 text-muted-foreground">
              <span class="rounded bg-muted px-2 py-1">{state.crossRepoIndexResult.dry_run ? 'dry-run' : 'applied'}</span>
              <span class="rounded bg-muted px-2 py-1">repos {state.crossRepoIndexResult.repos}</span>
              <span class="rounded bg-muted px-2 py-1">indexed {state.crossRepoIndexResult.indexed}</span>
              <span class="rounded bg-muted px-2 py-1">failed {state.crossRepoIndexResult.failed}</span>
              <span class="rounded bg-muted px-2 py-1">skipped {state.crossRepoIndexResult.skipped}</span>
            </div>
            {#if (state.crossRepoIndexResult.errors ?? []).length > 0}
              <div class="mt-2 text-red-500">
                {#each (state.crossRepoIndexResult.errors ?? []).slice(0, 3) as item}
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
