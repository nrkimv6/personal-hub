<script lang="ts">
  import type { InstagramSummary } from '$lib/types';

  interface Props {
    summary: InstagramSummary;
  }

  let { summary }: Props = $props();

  function getWorkerStatusColor(status: string) {
    switch (status) {
      case 'healthy':
        return 'text-green-500';
      case 'warning':
        return 'text-yellow-500';
      case 'dead':
        return 'text-red-500';
      default:
        return 'text-gray-400';
    }
  }

  function getWorkerStatusLabel(status: string) {
    switch (status) {
      case 'healthy':
        return '활성';
      case 'warning':
        return '경고';
      case 'dead':
        return '중지';
      default:
        return '없음';
    }
  }

  function getWorkerStatusBg(status: string) {
    switch (status) {
      case 'healthy':
        return 'bg-green-100 dark:bg-green-900/30';
      case 'warning':
        return 'bg-yellow-100 dark:bg-yellow-900/30';
      case 'dead':
        return 'bg-red-100 dark:bg-red-900/30';
      default:
        return 'bg-gray-100 dark:bg-gray-800';
    }
  }
</script>

<div class="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
  <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
    <span class="text-xl">📸</span>
    Instagram
  </h2>

  <div class="space-y-3">
    <!-- 워커 상태 -->
    <div class="flex justify-between items-center">
      <span class="text-gray-600 dark:text-gray-400">워커</span>
      <span class="flex items-center gap-2">
        <span class="text-lg {getWorkerStatusColor(summary.worker_status)}">●</span>
        <span class="px-2 py-0.5 text-sm rounded {getWorkerStatusBg(summary.worker_status)} {getWorkerStatusColor(summary.worker_status)}">
          {getWorkerStatusLabel(summary.worker_status)}
        </span>
      </span>
    </div>

    <!-- Uptime -->
    {#if summary.worker_uptime}
      <div class="flex justify-between items-center">
        <span class="text-gray-600 dark:text-gray-400">Uptime</span>
        <span class="font-medium text-gray-900 dark:text-white">{summary.worker_uptime}</span>
      </div>
    {/if}

    <div class="pt-2 border-t border-gray-200 dark:border-gray-700">
      <!-- 오늘 수집 -->
      <div class="flex justify-between items-center">
        <span class="text-gray-600 dark:text-gray-400">오늘 수집</span>
        <span class="font-bold text-xl text-purple-600 dark:text-purple-400">{summary.today_collected}</span>
      </div>

      <!-- 다음 실행 -->
      {#if summary.next_schedule}
        <div class="flex justify-between items-center text-sm mt-2">
          <span class="text-gray-600 dark:text-gray-400">다음 실행</span>
          <span class="font-medium text-gray-900 dark:text-white">{summary.next_schedule}</span>
        </div>
      {/if}
    </div>
  </div>
</div>
