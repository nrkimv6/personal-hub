<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { gitReposApi } from '$lib/api/gitRepos';
  import { llmApi, type ProviderInfo } from '$lib/api';
  import { apiGate } from '$lib/stores/apiGate.svelte';
  import { confirm } from '$lib/stores/confirm';
  import type { GitRepo, GitStatus, GitLogEntry, OperationLog, AutoCleanupResult } from '$lib/types/gitRepos';
  import {
    ArrowLeft,
    GitBranch,
    Eraser,
    CheckCircle,
    Loader2,
    Package,
    GitCommit,
    Sparkles,
    RefreshCw,
    Download,
    Upload,
    ChevronDown,
    ChevronRight,
    Search,
    FileEdit
  } from 'lucide-svelte';
  import TabNav from '$lib/components/layout/TabNav.svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';

  // URL params
  const repoId = $derived(Number($page.params.id));

  // 상태
  let repo: GitRepo | null = $state(null);
  let status: GitStatus | null = $state(null);
  let logEntries: GitLogEntry[] = $state([]);
  let operations: OperationLog[] = $state([]);
  let diff = $state('');
  let stagedDiff = $state('');

  let activeTab: 'changes' | 'log' | 'history' = $state('changes');

  const repoTabs = [
    { id: 'changes', label: '변경사항' },
    { id: 'log', label: '커밋 로그' },
    { id: 'history', label: '작업 이력' },
  ];
  let loading = $state(true);
  let working = $state(false);
  let refreshingStatus = $state(false);
  let refreshAttempt = $state(0);
  let error = $state('');
  let toast = $state('');

  // 커밋
  let commitMsg = $state('');
  let generatingMsg = $state(false);
  let llmProvider = $state('claude');
  let providers = $state<ProviderInfo[]>([]);

  // 자동 정리
  let cleanupRequestId = $state<number | null>(null);
  let cleanupLogs = $state<string[]>([]);
  let cleanupDone = $state(false);
  let cleanupResult = $state<AutoCleanupResult | null>(null);

  // 선택된 파일
  let selectedStaged: Set<string> = $state(new Set());
  let selectedUnstaged: Set<string> = $state(new Set());

  // diff 표시 파일
  let diffFile: string | null = $state(null);
  let fileDiff = $state('');

  onMount(async () => {
    await loadAll();
    llmApi.getProviders().then(data => { providers = data; }).catch(() => {});
  });

  async function loadRepo() {
    repo = await gitReposApi.getRepo(repoId);
  }

  async function loadAll() {
    loading = true;
    error = '';
    try {
      await loadRepo();
      loading = false;
      await Promise.all([loadStatus(), loadLog(), loadOperations()]);
    } catch (e) {
      if (repo) {
        showToast(e instanceof Error ? e.message : '로드 실패', 'error');
      } else {
        error = e instanceof Error ? e.message : '로드 실패';
      }
    } finally {
      loading = false;
    }

    if (repo) {
      void refreshRepoStatus();
    }
  }

  async function refreshRepoStatus() {
    if (refreshingStatus) return;
    refreshingStatus = true;
    refreshAttempt = 0;
    try {
      await gitReposApi.executeAndPoll(
        () => gitReposApi.refreshRepo(repoId),
        {
          interval: 500,
          maxRetries: 30,
          onPending: (attempt) => {
            refreshAttempt = attempt;
          }
        }
      );
      await Promise.all([loadRepo(), loadStatus(), loadLog(), loadOperations()]);
    } catch (e) {
      showToast(e instanceof Error ? e.message : '상태 갱신 실패', 'error');
    } finally {
      refreshingStatus = false;
    }
  }

  async function loadStatus() {
    const [statusResult, diffResult, stagedDiffResult] = await Promise.allSettled([
      gitReposApi.getStatus(repoId),
      gitReposApi.getDiff(repoId, false),
      gitReposApi.getDiff(repoId, true),
    ]);

    if (statusResult.status === 'fulfilled') {
      status = statusResult.value;
    } else {
      status = null;
    }

    diff = diffResult.status === 'fulfilled' ? diffResult.value.diff : '';
    stagedDiff = stagedDiffResult.status === 'fulfilled' ? stagedDiffResult.value.diff : '';
  }

  async function loadLog() {
    try {
      logEntries = await gitReposApi.getLog(repoId, 20);
    } catch {
      logEntries = [];
    }
  }

  async function loadOperations() {
    try {
      operations = await gitReposApi.getOperations(repoId, 50);
    } catch {
      operations = [];
    }
  }

  async function handleStageFile(file: string) {
    working = true;
    try {
      await gitReposApi.executeAndPoll(
        () => gitReposApi.stageFiles(repoId, [file]),
        { interval: 500, maxRetries: 30 }
      );
      await loadStatus();
    } catch (e) {
      showToast('스테이징 실패', 'error');
    } finally {
      working = false;
    }
  }

  async function handleUnstageFile(file: string) {
    working = true;
    try {
      await gitReposApi.executeAndPoll(
        () => gitReposApi.unstageFiles(repoId, [file]),
        { interval: 500, maxRetries: 30 }
      );
      await loadStatus();
    } catch {
      showToast('언스테이징 실패', 'error');
    } finally {
      working = false;
    }
  }

  async function handleCommit() {
    if (!commitMsg.trim()) return;
    working = true;
    try {
      const result = await gitReposApi.executeAndPoll(
        () => gitReposApi.commit(repoId, commitMsg),
        { interval: 1000, maxRetries: 60 }
      );
      if (result.result?.success) {
        showToast('커밋 완료');
        commitMsg = '';
        await loadAll();
      } else {
        showToast(result.result?.stderr || result.result?.stdout || '커밋 실패', 'error');
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : '커밋 실패', 'error');
    } finally {
      working = false;
    }
  }

  async function handlePush() {
    working = true;
    try {
      const result = await gitReposApi.executeAndPoll(
        () => gitReposApi.push(repoId),
        { interval: 1000, maxRetries: 60 }
      );
      if (result.result?.success) {
        showToast('푸시 완료');
        await loadAll();
      } else {
        showToast(result.result?.stderr || '푸시 실패', 'error');
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : '푸시 실패', 'error');
    } finally {
      working = false;
    }
  }

  async function handlePull() {
    working = true;
    try {
      const result = await gitReposApi.executeAndPoll(
        () => gitReposApi.pull(repoId),
        { interval: 1000, maxRetries: 60 }
      );
      if (result.result?.success) {
        showToast('풀 완료');
        await loadAll();
      } else {
        showToast(result.result?.stderr || '풀 실패', 'error');
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : '풀 실패', 'error');
    } finally {
      working = false;
    }
  }

  async function handleFetch() {
    working = true;
    try {
      const result = await gitReposApi.executeAndPoll(
        () => gitReposApi.fetch(repoId),
        { interval: 1000, maxRetries: 60 }
      );
      if (result.result?.success) {
        showToast('페치 완료');
        await loadStatus();
      } else {
        showToast(result.result?.stderr || '페치 실패', 'error');
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : '페치 실패', 'error');
    } finally {
      working = false;
    }
  }

  async function handleGenerateMessage() {
    generatingMsg = true;
    try {
      const result = await gitReposApi.generateMessage(repoId, { provider: llmProvider });
      if (result.message) {
        commitMsg = result.message;
        showToast('커밋 메시지가 생성되었습니다.');
      } else {
        showToast(`메시지 생성 요청 접수됨 (#${result.request_id})`);
      }
    } catch (e) {
      showToast('메시지 생성 실패: ' + (e instanceof Error ? e.message : ''), 'error');
    } finally {
      generatingMsg = false;
    }
  }

  async function handleAutoCleanup() {
    if (
      !(await confirm({
        title: '자동 정리 실행',
        message: '미커밋 파일을 자동 분류·커밋하시겠습니까?\n(tmp_* 패턴 파일은 archive로 이동됩니다)',
        confirmText: '실행',
        variant: 'warning'
      }))
    ) return;
    
    working = true;
    cleanupRequestId = null;
    cleanupLogs = [];
    cleanupDone = false;
    cleanupResult = null;
    
    try {
      const res = await gitReposApi.autoCleanup(repoId, { provider: llmProvider });
      cleanupRequestId = res.request_id;

      if (apiGate.state !== 'open') {
        showToast('API 서버 재시작 중입니다', 'error');
        working = false;
        return;
      }
      
      const eventSource = new EventSource(`/api/v1/llm/chat/${cleanupRequestId}/stream`);
      
      eventSource.onmessage = (e) => {
        cleanupLogs = [...cleanupLogs, e.data];
      };
      
      eventSource.addEventListener('completed', async () => {
        eventSource.close();
        cleanupDone = true;
        await loadCleanupResult();
        await loadAll();
      });
      
      eventSource.onerror = () => {
        eventSource.close();
        working = false;
      };
      
    } catch (e) {
      showToast('자동 정리 시작 실패', 'error');
      working = false;
    }
  }

  async function loadCleanupResult() {
    if (!cleanupRequestId) return;
    try {
      const res = await gitReposApi.getCleanupResult(repoId, cleanupRequestId);
      cleanupResult = res;
    } catch (e) {
      // ignore
    } finally {
      working = false;
    }
  }

  async function showFileDiff(file: string, staged: boolean) {
    diffFile = file;
    try {
      const result = await gitReposApi.getDiff(repoId, staged);
      // 특정 파일 diff만 필터
      fileDiff = result.diff;
    } catch {
      fileDiff = '';
    }
  }

  function showToast(msg: string, type: 'success' | 'error' = 'success') {
    toast = msg;
    setTimeout(() => (toast = ''), 3000);
  }

  function formatDate(str: string) {
    return new Date(str).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  }

  const pageTitle = $derived.by(() => {
    const currentRepo = repo;
    return currentRepo
      ? currentRepo.alias || currentRepo.path.split(/[/\\]/).pop() || 'Git 저장소'
      : 'Git 저장소';
  });
  const pageSubtitle = $derived.by(() => repo?.path ?? '저장소 상태, 변경사항, 작업 이력을 관리합니다.');
</script>

{#snippet headerActions()}
  <button
    class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 flex items-center gap-1"
    onclick={() => goto('/git-repos')}
  >
    <ArrowLeft size={16} /> 목록
  </button>
  {#if repo?.last_branch}
    <span class="font-mono text-xs bg-gray-100 dark:bg-gray-700 px-2 py-1 rounded text-gray-600 dark:text-gray-300 flex items-center gap-1">
      <GitBranch size={12} /> {repo.last_branch}
    </span>
  {/if}
{/snippet}

<div class="max-w-5xl mx-auto space-y-4 p-4 md:p-6">
  <PageHeader title={pageTitle} subtitle={pageSubtitle} density="compact">
    {@render headerActions()}
  </PageHeader>

  {#if loading}
    <div class="text-center py-16 text-gray-400">
      <Loader2 size={32} class="animate-spin mx-auto mb-2" />
      로딩 중…
    </div>
  {:else if error}
    <div class="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400">{error}</div>
    {:else if repo}
      {@const r = repo}
    <TabNav tabs={repoTabs} bind:activeTab variant="primary" />

    <!-- 상단 액션 버튼 -->
    <div class="flex flex-wrap gap-2">
      <button class="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1" onclick={handleFetch} disabled={working}>
        <RefreshCw size={14} /> 페치
      </button>
      <button class="px-3 py-1.5 text-sm rounded-lg bg-teal-600 text-white hover:bg-teal-700 disabled:opacity-50 flex items-center gap-1" onclick={handlePull} disabled={working}>
        <Download size={14} /> 풀
      </button>
      <button class="px-3 py-1.5 text-sm rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50 flex items-center gap-1" onclick={handlePush} disabled={working}>
        <Upload size={14} /> 푸시
      </button>
      <button class="px-3 py-1.5 text-sm rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 flex items-center gap-1" onclick={handleAutoCleanup} disabled={working}>
        <Eraser size={14} /> 자동 정리
      </button>
      {#if r.last_ahead != null && r.last_ahead > 0}
        <span class="text-xs text-green-600 dark:text-green-400 self-center">↑{r.last_ahead} ahead</span>
      {/if}
      {#if r.last_behind != null && r.last_behind > 0}
        <span class="text-xs text-red-500 dark:text-red-400 self-center">↓{r.last_behind} behind</span>
      {/if}
      {#if refreshingStatus}
        <span class="text-xs text-gray-500 dark:text-gray-400 self-center flex items-center gap-1">
          <Loader2 size={12} class="animate-spin" /> 상태 갱신 중{refreshAttempt ? ` (${refreshAttempt})` : ''}
        </span>
      {/if}
    </div>

    <!-- 자동 정리 로그 패널 -->
    {#if cleanupRequestId}
      <div class="mb-6 p-4 rounded-xl bg-gray-900 text-gray-100 font-mono text-xs overflow-hidden border border-amber-500/30">
        <div class="flex justify-between items-center mb-2 border-b border-gray-800 pb-2">
          <span class="text-amber-400 font-bold flex items-center gap-2">
            <Eraser size={14} /> Git 자동 정리 로그 (ID: {cleanupRequestId})
          </span>
          {#if cleanupDone}
            <span class="text-green-400 font-bold flex items-center gap-1">
              <CheckCircle size={14} /> 정리 완료
            </span>
          {:else}
            <span class="text-amber-500 flex items-center gap-1">
              <Loader2 size={14} class="animate-spin" /> 진행 중...
            </span>
          {/if}
        </div>
        <pre class="max-h-48 overflow-y-auto whitespace-pre-wrap">{cleanupLogs.join('\n')}</pre>
        
        {#if cleanupResult}
          <div class="mt-3 pt-3 border-t border-gray-800 text-gray-300">
            {#if cleanupResult.success}
              <p class="text-green-400 mb-1">성공적으로 정리되었습니다.</p>
              {#if cleanupResult.moved.length > 0}
                <p class="flex items-center gap-1">
                  <Package size={14} /> 이동된 파일 ({cleanupResult.moved.length}개): {cleanupResult.moved.join(', ')}
                </p>
              {/if}
              {#if cleanupResult.commits.length > 0}
                <p class="flex items-center gap-1">
                  <GitCommit size={14} /> 생성된 커밋 ({cleanupResult.commits.length}개):
                </p>
                <ul class="list-disc list-inside ml-2">
                  {#each cleanupResult.commits as commit}
                    <li>{commit.message} ({commit.files.length}개 파일)</li>
                  {/each}
                </ul>
              {/if}
            {:else}
              <p class="text-red-400">정리 실패: {cleanupResult.error || '알 수 없는 오류'}</p>
            {/if}
          </div>
        {/if}
      </div>
    {/if}

    <!-- 탭 내용 -->
    {#if activeTab === 'changes'}
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <!-- 파일 목록 -->
        <div>
          {#if status}
            <!-- staged -->
            {#if status.staged.length > 0}
              <div class="mb-4">
                <p class="text-xs font-semibold text-green-600 dark:text-green-400 uppercase mb-2">Staged ({status.staged.length})</p>
                {#each status.staged as file}
                  <div class="flex items-center gap-2 py-1 px-2 rounded hover:bg-gray-50 dark:hover:bg-gray-700/30 group">
                    <button class="text-xs text-left flex-1 font-mono text-gray-700 dark:text-gray-300 truncate" onclick={() => showFileDiff(file, true)}>{file}</button>
                    <button class="hidden group-hover:inline text-xs text-orange-500 hover:text-orange-700" onclick={() => handleUnstageFile(file)}>언스테이지</button>
                  </div>
                {/each}
              </div>
            {/if}

            <!-- unstaged -->
            {#if status.unstaged.length > 0}
              <div class="mb-4">
                <p class="text-xs font-semibold text-yellow-600 dark:text-yellow-400 uppercase mb-2">Unstaged ({status.unstaged.length})</p>
                {#each status.unstaged as file}
                  <div class="flex items-center gap-2 py-1 px-2 rounded hover:bg-gray-50 dark:hover:bg-gray-700/30 group">
                    <button class="text-xs text-left flex-1 font-mono text-gray-700 dark:text-gray-300 truncate" onclick={() => showFileDiff(file, false)}>{file}</button>
                    <button class="hidden group-hover:inline text-xs text-green-600 hover:text-green-700" onclick={() => handleStageFile(file)}>스테이지</button>
                  </div>
                {/each}
              </div>
            {/if}

            <!-- untracked -->
            {#if status.untracked.length > 0}
              <div class="mb-4">
                <p class="text-xs font-semibold text-gray-500 uppercase mb-2">Untracked ({status.untracked.length})</p>
                {#each status.untracked as file}
                  <div class="flex items-center gap-2 py-1 px-2 rounded hover:bg-gray-50 dark:hover:bg-gray-700/30 group">
                    <span class="text-xs flex-1 font-mono text-gray-500 dark:text-gray-400 truncate">{file}</span>
                    <button class="hidden group-hover:inline text-xs text-green-600 hover:text-green-700" onclick={() => handleStageFile(file)}>스테이지</button>
                  </div>
                {/each}
              </div>
            {/if}

            {#if status.staged.length === 0 && status.unstaged.length === 0 && status.untracked.length === 0}
              <div class="text-center py-8 text-gray-400 text-sm">변경 사항 없음 (clean)</div>
            {/if}
          {:else}
            <div class="text-center py-8 text-gray-400 text-sm">상태를 불러올 수 없습니다.</div>
          {/if}

          <!-- 커밋 영역 -->
          <div class="mt-4 border-t dark:border-gray-700 pt-4">
            <div class="flex gap-2 mb-2">
              <input
                class="flex-1 border rounded-lg px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                placeholder="커밋 메시지"
                bind:value={commitMsg}
                onkeydown={(e) => e.key === 'Enter' && !e.shiftKey && handleCommit()}
              />
              <select
                class="px-2 py-2 text-xs rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 border-0"
                bind:value={llmProvider}
                title="LLM 엔진 선택"
              >
                {#if providers.length > 0}
                  {#each providers as p}
                    <option value={p.key}>{p.display_name}</option>
                  {/each}
                {:else}
                  <option value="claude">Claude</option>
                  <option value="gemini">Gemini</option>
                {/if}
              </select>
              <button
                class="px-3 py-2 text-sm rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300 disabled:opacity-50 flex items-center justify-center"
                onclick={handleGenerateMessage}
                disabled={generatingMsg}
                title="LLM으로 커밋 메시지 자동 생성"
              >
                {#if generatingMsg}
                  <Loader2 size={16} class="animate-spin" />
                {:else}
                  <Sparkles size={16} />
                {/if}
              </button>
            </div>
            <button
              class="w-full py-2 rounded-lg bg-green-600 text-white text-sm hover:bg-green-700 disabled:opacity-50"
              onclick={handleCommit}
              disabled={working || !commitMsg.trim()}
            >{working ? '커밋 중…' : '커밋'}</button>
          </div>
        </div>

        <!-- Diff 미리보기 -->
        <div class="bg-gray-50 dark:bg-gray-900/50 rounded-xl overflow-hidden">
          {#if diffFile}
            <p class="text-xs font-mono text-gray-500 dark:text-gray-400 px-3 py-2 border-b dark:border-gray-700">{diffFile}</p>
          {/if}
          <pre class="text-xs font-mono p-3 overflow-auto max-h-96 text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{fileDiff || (stagedDiff || diff) || '파일을 클릭해 diff를 확인하세요.'}</pre>
        </div>
      </div>

    {:else if activeTab === 'log'}
      <!-- 커밋 로그 -->
      {#if logEntries.length === 0}
        <div class="text-center py-10 text-gray-400 text-sm">커밋 기록이 없습니다.</div>
      {:else}
        <div class="space-y-1">
          {#each logEntries as entry}
            <div class="flex items-start gap-3 py-2 px-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/30">
              <span class="font-mono text-xs text-gray-400 dark:text-gray-500 w-16 flex-shrink-0 mt-0.5">{entry.short_hash}</span>
              <div class="flex-1 min-w-0">
                <p class="text-sm text-gray-700 dark:text-gray-200 truncate">{entry.message}</p>
                <p class="text-xs text-gray-400 dark:text-gray-500">{entry.author} · {entry.date}</p>
              </div>
            </div>
          {/each}
        </div>
      {/if}

    {:else}
      <!-- 작업 이력 -->
      {#if operations.length === 0}
        <div class="text-center py-10 text-gray-400 text-sm">작업 이력이 없습니다.</div>
      {:else}
        <div class="space-y-1">
          {#each operations as op}
            <details class="rounded-lg border border-gray-100 dark:border-gray-700">
              <summary class="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/30 text-sm list-none">
                <span class="w-16 text-xs font-medium {op.status === 'success' ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}">{op.status}</span>
                <span class="font-mono text-xs text-blue-600 dark:text-blue-400 w-20 flex-shrink-0">{op.operation}</span>
                <span class="text-gray-600 dark:text-gray-300 flex-1 truncate">{op.message || '-'}</span>
                <span class="text-xs text-gray-400 dark:text-gray-500 flex-shrink-0">{formatDate(op.created_at)}</span>
              </summary>
              {#if op.detail}
                <pre class="px-4 py-2 text-xs font-mono bg-gray-50 dark:bg-gray-900/50 text-gray-600 dark:text-gray-300 whitespace-pre-wrap overflow-auto max-h-40 border-t dark:border-gray-700">{op.detail}</pre>
              {/if}
            </details>
          {/each}
        </div>
      {/if}
    {/if}
  {/if}
</div>

<!-- 토스트 -->
{#if toast}
  <div class="fixed bottom-6 right-6 z-50 px-4 py-3 rounded-xl bg-gray-800 text-white text-sm shadow-lg">
    {toast}
  </div>
{/if}
