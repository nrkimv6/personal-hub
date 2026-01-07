<script lang="ts">
  import { integrityApi } from '$lib/api';

  // Props
  interface Props {
    onIssueCountChange?: (count: number) => void;
  }
  let { onIssueCountChange }: Props = $props();

  // 상태
  let loading = $state(false);
  let checkResult = $state<{
    total_issues: number;
    by_severity: { critical: number; warning: number; info: number };
    issues: Array<{
      table: string;
      issue_type: string;
      severity: 'critical' | 'warning' | 'info';
      count: number;
      sample_ids: number[];
      description: string;
      auto_fixable: boolean;
    }>;
  } | null>(null);

  let dbStats = $state<{
    tables: Record<string, number | null>;
    db_size_bytes: number;
    db_size_mb: number;
  } | null>(null);

  let fixingAll = $state(false);
  let fixingTable = $state<string | null>(null);
  let lastFixResult = $state<{
    success: boolean;
    message: string;
  } | null>(null);

  // 초기 데이터 로드
  async function loadData() {
    loading = true;
    try {
      const [checkRes, statsRes] = await Promise.all([
        integrityApi.check(),
        integrityApi.stats()
      ]);
      checkResult = checkRes;
      dbStats = statsRes;

      if (checkResult && onIssueCountChange) {
        onIssueCountChange(checkResult.total_issues);
      }
    } catch (err) {
      console.error('Failed to load integrity data:', err);
    } finally {
      loading = false;
    }
  }

  // 전체 검사 실행
  async function runCheck() {
    loading = true;
    lastFixResult = null;
    try {
      checkResult = await integrityApi.check();
      if (checkResult && onIssueCountChange) {
        onIssueCountChange(checkResult.total_issues);
      }
    } catch (err) {
      console.error('Check failed:', err);
    } finally {
      loading = false;
    }
  }

  // 자동 수정 (전체)
  async function fixAll(dryRun: boolean) {
    fixingAll = true;
    lastFixResult = null;
    try {
      const result = await integrityApi.fixAll(dryRun);
      if (dryRun) {
        const affectedTotal = result.results.reduce((sum: number, r: { affected_count: number }) => sum + r.affected_count, 0);
        lastFixResult = {
          success: true,
          message: `미리보기: ${result.fixable_issues}개 문제, ${affectedTotal}개 레코드 수정 가능`
        };
      } else {
        const fixedCount = result.results.filter((r: { fixed: boolean }) => r.fixed).length;
        const affectedTotal = result.results.reduce((sum: number, r: { affected_count: number }) => sum + r.affected_count, 0);
        lastFixResult = {
          success: true,
          message: `${fixedCount}개 문제 수정 완료, ${affectedTotal}개 레코드 처리됨`
        };
        // 검사 다시 실행
        await runCheck();
      }
    } catch (err) {
      lastFixResult = {
        success: false,
        message: `수정 실패: ${err}`
      };
    } finally {
      fixingAll = false;
    }
  }

  // 특정 문제 수정
  async function fixSpecific(table: string, issueType: string, dryRun: boolean) {
    fixingTable = `${table}/${issueType}`;
    lastFixResult = null;
    try {
      const result = await integrityApi.fixSpecific(table, issueType, dryRun);
      if (result.error) {
        lastFixResult = {
          success: false,
          message: result.error
        };
      } else if (dryRun) {
        lastFixResult = {
          success: true,
          message: `미리보기: ${result.affected_count}개 레코드 수정 가능`
        };
      } else {
        lastFixResult = {
          success: true,
          message: `${result.affected_count}개 레코드 수정 완료`
        };
        // 검사 다시 실행
        await runCheck();
      }
    } catch (err) {
      lastFixResult = {
        success: false,
        message: `수정 실패: ${err}`
      };
    } finally {
      fixingTable = null;
    }
  }

  // 심각도별 아이콘
  function getSeverityIcon(severity: string): string {
    switch (severity) {
      case 'critical': return '🔴';
      case 'warning': return '🟡';
      case 'info': return '🔵';
      default: return '⚪';
    }
  }

  // 심각도별 색상 클래스
  function getSeverityClass(severity: string): string {
    switch (severity) {
      case 'critical': return 'text-red-600 bg-red-50 dark:text-red-400 dark:bg-red-900/20';
      case 'warning': return 'text-yellow-600 bg-yellow-50 dark:text-yellow-400 dark:bg-yellow-900/20';
      case 'info': return 'text-blue-600 bg-blue-50 dark:text-blue-400 dark:bg-blue-900/20';
      default: return 'text-gray-600 bg-gray-50 dark:text-gray-400 dark:bg-gray-800';
    }
  }

  // 테이블 카운트 포맷
  function formatCount(count: number | null): string {
    if (count === null) return '-';
    return count.toLocaleString();
  }

  // 컴포넌트 마운트 시 데이터 로드
  $effect(() => {
    loadData();
  });
</script>

<div class="space-y-6">
  <div class="flex justify-end">
    <button
      onclick={runCheck}
      disabled={loading}
      class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
    >
      {loading ? '검사 중...' : '🔄 검사 실행'}
    </button>
  </div>

  <!-- 알림 메시지 -->
  {#if lastFixResult}
    <div class="p-3 rounded {lastFixResult.success ? 'bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400' : 'bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400'}">
      {lastFixResult.message}
      <button
        onclick={() => lastFixResult = null}
        class="ml-2 text-sm underline"
      >닫기</button>
    </div>
  {/if}

  <!-- 요약 카드 -->
  {#if checkResult}
    <div class="grid grid-cols-4 gap-4">
      <div class="bg-white dark:bg-gray-800 p-4 rounded shadow-sm">
        <div class="text-sm text-gray-500 dark:text-gray-400">전체 문제</div>
        <div class="text-2xl font-bold text-gray-900 dark:text-white">{checkResult.total_issues}</div>
      </div>
      <div class="bg-red-50 dark:bg-red-900/20 p-4 rounded shadow-sm">
        <div class="text-sm text-red-600 dark:text-red-400">Critical</div>
        <div class="text-2xl font-bold text-red-700 dark:text-red-300">{checkResult.by_severity.critical}</div>
      </div>
      <div class="bg-yellow-50 dark:bg-yellow-900/20 p-4 rounded shadow-sm">
        <div class="text-sm text-yellow-600 dark:text-yellow-400">Warning</div>
        <div class="text-2xl font-bold text-yellow-700 dark:text-yellow-300">{checkResult.by_severity.warning}</div>
      </div>
      <div class="bg-blue-50 dark:bg-blue-900/20 p-4 rounded shadow-sm">
        <div class="text-sm text-blue-600 dark:text-blue-400">Info</div>
        <div class="text-2xl font-bold text-blue-700 dark:text-blue-300">{checkResult.by_severity.info}</div>
      </div>
    </div>

    <!-- 자동 수정 버튼 -->
    {#if checkResult.issues.some(i => i.auto_fixable)}
      <div class="flex gap-2">
        <button
          onclick={() => fixAll(true)}
          disabled={fixingAll}
          class="px-4 py-2 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50"
        >
          {fixingAll ? '처리 중...' : '👁️ 미리보기 (전체)'}
        </button>
        <button
          onclick={() => fixAll(false)}
          disabled={fixingAll}
          class="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
        >
          {fixingAll ? '처리 중...' : '🔧 자동 수정 (전체)'}
        </button>
      </div>
    {/if}

    <!-- 문제 목록 -->
    {#if checkResult.issues.length > 0}
      <div class="bg-white dark:bg-gray-800 rounded shadow-sm overflow-hidden">
        <table class="w-full">
          <thead class="bg-gray-50 dark:bg-gray-900">
            <tr>
              <th class="px-4 py-3 text-left text-sm font-medium text-gray-600 dark:text-gray-400">심각도</th>
              <th class="px-4 py-3 text-left text-sm font-medium text-gray-600 dark:text-gray-400">테이블</th>
              <th class="px-4 py-3 text-left text-sm font-medium text-gray-600 dark:text-gray-400">유형</th>
              <th class="px-4 py-3 text-left text-sm font-medium text-gray-600 dark:text-gray-400">설명</th>
              <th class="px-4 py-3 text-right text-sm font-medium text-gray-600 dark:text-gray-400">수량</th>
              <th class="px-4 py-3 text-center text-sm font-medium text-gray-600 dark:text-gray-400">작업</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200 dark:divide-gray-700">
            {#each checkResult.issues as issue}
              <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                <td class="px-4 py-3">
                  <span class="px-2 py-1 rounded text-sm {getSeverityClass(issue.severity)}">
                    {getSeverityIcon(issue.severity)} {issue.severity}
                  </span>
                </td>
                <td class="px-4 py-3 font-mono text-sm text-gray-900 dark:text-white">{issue.table}</td>
                <td class="px-4 py-3 font-mono text-sm text-gray-900 dark:text-white">{issue.issue_type}</td>
                <td class="px-4 py-3 text-sm text-gray-600 dark:text-gray-400">{issue.description}</td>
                <td class="px-4 py-3 text-right font-mono text-gray-900 dark:text-white">{issue.count.toLocaleString()}</td>
                <td class="px-4 py-3 text-center">
                  {#if issue.auto_fixable}
                    <div class="flex justify-center gap-1">
                      <button
                        onclick={() => fixSpecific(issue.table, issue.issue_type, true)}
                        disabled={fixingTable === `${issue.table}/${issue.issue_type}`}
                        class="px-2 py-1 text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50"
                        title="미리보기"
                      >👁️</button>
                      <button
                        onclick={() => fixSpecific(issue.table, issue.issue_type, false)}
                        disabled={fixingTable === `${issue.table}/${issue.issue_type}`}
                        class="px-2 py-1 text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded hover:bg-green-200 dark:hover:bg-green-900/50 disabled:opacity-50"
                        title="수정"
                      >🔧</button>
                    </div>
                  {:else}
                    <span class="text-xs text-gray-400 dark:text-gray-500">수동 처리</span>
                  {/if}
                </td>
              </tr>
              <!-- 샘플 ID 표시 (있는 경우) -->
              {#if issue.sample_ids.length > 0}
                <tr class="bg-gray-50 dark:bg-gray-900/50">
                  <td colspan="6" class="px-4 py-2 text-xs text-gray-500 dark:text-gray-400">
                    샘플 ID: {issue.sample_ids.join(', ')}
                    {#if issue.count > issue.sample_ids.length}
                      ... 외 {issue.count - issue.sample_ids.length}개
                    {/if}
                  </td>
                </tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <div class="bg-green-50 dark:bg-green-900/20 p-6 rounded text-center text-green-700 dark:text-green-400">
        ✅ 모든 정합성 검사를 통과했습니다!
      </div>
    {/if}
  {/if}

  <!-- DB 통계 -->
  {#if dbStats}
    <div class="bg-white dark:bg-gray-800 rounded shadow-sm p-4">
      <h2 class="text-lg font-semibold mb-4 text-gray-900 dark:text-white">DB 통계</h2>
      <div class="mb-4">
        <span class="text-gray-500 dark:text-gray-400">DB 크기:</span>
        <span class="font-mono font-semibold text-gray-900 dark:text-white">{dbStats.db_size_mb} MB</span>
      </div>
      <div class="grid grid-cols-4 gap-3">
        {#each Object.entries(dbStats.tables) as [table, count]}
          <div class="flex justify-between items-center py-1 px-2 bg-gray-50 dark:bg-gray-900/50 rounded text-sm">
            <span class="font-mono text-gray-600 dark:text-gray-400">{table}</span>
            <span class="font-mono font-semibold text-gray-900 dark:text-white">{formatCount(count)}</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- 로딩 표시 -->
  {#if loading && !checkResult}
    <div class="flex justify-center items-center py-12">
      <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      <span class="ml-3 text-gray-600 dark:text-gray-400">검사 중...</span>
    </div>
  {/if}
</div>
