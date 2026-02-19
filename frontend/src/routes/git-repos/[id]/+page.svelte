<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { gitReposApi } from '$lib/api/gitRepos';
  import type { GitRepo, GitStatus, GitLogEntry, OperationLog } from '$lib/types/gitRepos';

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
  let loading = $state(true);
  let working = $state(false);
  let error = $state('');
  let toast = $state('');

  // 커밋
  let commitMsg = $state('');
  let generatingMsg = $state(false);

  // 선택된 파일
  let selectedStaged: Set<string> = $state(new Set());
  let selectedUnstaged: Set<string> = $state(new Set());

  // diff 표시 파일
  let diffFile: string | null = $state(null);
  let fileDiff = $state('');

  onMount(async () => {
    await loadAll();
  });

  async function loadAll() {
    loading = true;
    error = '';
    try {
      // repo 기본 정보는 list에서 가져오거나 refresh로 얻음
      const refreshed = await gitReposApi.refreshRepo(repoId);
      repo = refreshed;

      await Promise.all([loadStatus(), loadLog(), loadOperations()]);
    } catch (e) {
      error = e instanceof Error ? e.message : '로드 실패';
    } finally {
      loading = false;
    }
  }

  async function loadStatus() {
    try {
      status = await gitReposApi.getStatus(repoId);
      // diff 로드
      const [d, sd] = await Promise.all([
        gitReposApi.getDiff(repoId, false),
        gitReposApi.getDiff(repoId, true),
      ]);
      diff = d.diff;
      stagedDiff = sd.diff;
    } catch (e) {
      status = null;
    }
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
    try {
      await gitReposApi.stageFiles(repoId, [file]);
      await loadStatus();
    } catch (e) {
      showToast('스테이징 실패', 'error');
    }
  }

  async function handleUnstageFile(file: string) {
    working = true;
    try {
      // unstage는 restore --staged 사용
      const result = await fetch(`/api/v1/git-repos/${repoId}/stage`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: [file] }),
      });
      // 백엔드에 unstage 엔드포인트가 없으면 stage 취소
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
      const result = await gitReposApi.commit(repoId, commitMsg);
      if (result.success) {
        showToast('커밋 완료');
        commitMsg = '';
        await loadAll();
      } else {
        showToast(result.stderr || result.stdout || '커밋 실패', 'error');
      }
    } finally {
      working = false;
    }
  }

  async function handlePush() {
    working = true;
    try {
      const result = await gitReposApi.push(repoId);
      if (result.success) {
        showToast('푸시 완료');
        await loadAll();
      } else {
        showToast(result.stderr || '푸시 실패', 'error');
      }
    } finally {
      working = false;
    }
  }

  async function handlePull() {
    working = true;
    try {
      const result = await gitReposApi.pull(repoId);
      if (result.success) {
        showToast('풀 완료');
        await loadAll();
      } else {
        showToast(result.stderr || '풀 실패', 'error');
      }
    } finally {
      working = false;
    }
  }

  async function handleFetch() {
    working = true;
    try {
      const result = await gitReposApi.fetch(repoId);
      if (result.success) {
        showToast('페치 완료');
        await loadStatus();
      } else {
        showToast(result.stderr || '페치 실패', 'error');
      }
    } finally {
      working = false;
    }
  }

  async function handleGenerateMessage() {
    generatingMsg = true;
    try {
      const result = await gitReposApi.generateMessage(repoId);
      if (result.message) {
        commitMsg = result.message;
        showToast('커밋 메시지가 생성되었습니다.');
      } else {
        showToast('메시지 생성 실패 (LLM 처리 대기 중)', 'error');
      }
    } catch (e) {
      showToast('메시지 생성 실패: ' + (e instanceof Error ? e.message : ''), 'error');
    } finally {
      generatingMsg = false;
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
</script>

<div class="p-6 max-w-5xl mx-auto">
  <!-- 뒤로가기 + 헤더 -->
  <div class="flex items-center gap-3 mb-6">
    <button
      class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
      onclick={() => goto('/git-repos')}
    >← 목록</button>
    {#if repo}
      <h1 class="text-xl font-bold text-gray-800 dark:text-gray-100">
        {repo.alias || repo.path.split(/[/\\]/).pop()}
      </h1>
      <span class="text-sm text-gray-400 dark:text-gray-500 truncate">{repo.path}</span>
      {#if repo.last_branch}
        <span class="ml-auto font-mono text-xs bg-gray-100 dark:bg-gray-700 px-2 py-1 rounded text-gray-600 dark:text-gray-300">
          🌿 {repo.last_branch}
        </span>
      {/if}
    {/if}
  </div>

  {#if loading}
    <div class="text-center py-16 text-gray-400">로딩 중…</div>
  {:else if error}
    <div class="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400">{error}</div>
  {:else}
    <!-- 상단 액션 버튼 -->
    <div class="flex gap-2 mb-5">
      <button class="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50" onclick={handleFetch} disabled={working}>페치</button>
      <button class="px-3 py-1.5 text-sm rounded-lg bg-teal-600 text-white hover:bg-teal-700 disabled:opacity-50" onclick={handlePull} disabled={working}>풀</button>
      <button class="px-3 py-1.5 text-sm rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50" onclick={handlePush} disabled={working}>푸시</button>
      {#if repo?.last_ahead != null && repo.last_ahead > 0}
        <span class="text-xs text-green-600 dark:text-green-400 self-center">↑{repo.last_ahead} ahead</span>
      {/if}
      {#if repo?.last_behind != null && repo.last_behind > 0}
        <span class="text-xs text-red-500 dark:text-red-400 self-center">↓{repo.last_behind} behind</span>
      {/if}
    </div>

    <!-- 탭 -->
    <div class="flex gap-1 mb-5 border-b border-gray-200 dark:border-gray-700">
      {#each [['changes', '변경사항'], ['log', '커밋 로그'], ['history', '작업 이력']] as [tab, label]}
        <button
          class="px-4 py-2 text-sm font-medium border-b-2 transition-colors {activeTab === tab ? 'border-blue-600 text-blue-600 dark:text-blue-400 dark:border-blue-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'}"
          onclick={() => (activeTab = tab as typeof activeTab)}
        >{label}</button>
      {/each}
    </div>

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
              <button
                class="px-3 py-2 text-sm rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300 disabled:opacity-50"
                onclick={handleGenerateMessage}
                disabled={generatingMsg}
                title="LLM으로 커밋 메시지 자동 생성"
              >{generatingMsg ? '…' : '✨'}</button>
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
