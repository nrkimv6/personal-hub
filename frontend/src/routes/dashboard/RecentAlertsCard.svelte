<script lang="ts">
  import type { RecentAlert } from '$lib/types';

  interface Props {
    alerts: RecentAlert[];
  }

  let { alerts }: Props = $props();

  function getAlertColor(type: string) {
    switch (type) {
      case 'recovery':
        return 'text-green-500';
      case 'failure':
        return 'text-red-500';
      default:
        return 'text-gray-500';
    }
  }

  function getAlertIcon(type: string) {
    switch (type) {
      case 'recovery':
        return '🟢';
      case 'failure':
        return '🔴';
      default:
        return '⚪';
    }
  }

  function formatTimestamp(timestamp: string) {
    try {
      const date = new Date(timestamp);
      return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
    } catch {
      return timestamp;
    }
  }

  function getServiceDisplayName(name: string) {
    const names: Record<string, string> = {
      api: 'API Server',
      frontend: 'Frontend',
      worker: 'Worker',
      cloudflared: 'Cloudflared',
      tunnel: 'Tunnel'
    };
    return names[name] || name;
  }
</script>

<div class="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
  <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
    <span class="text-xl">⚠️</span>
    최근 알림
  </h2>

  {#if alerts.length === 0}
    <p class="text-gray-500 dark:text-gray-400 text-sm text-center py-4">
      최근 알림이 없습니다.
    </p>
  {:else}
    <div class="space-y-2 max-h-48 overflow-y-auto">
      {#each alerts as alert}
        <div class="flex items-start gap-3 p-2 rounded hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
          <span class="text-lg flex-shrink-0">{getAlertIcon(alert.type)}</span>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-xs text-gray-500 dark:text-gray-400">
                {formatTimestamp(alert.timestamp)}
              </span>
              <span class="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
                {alert.check_type}
              </span>
            </div>
            <div class="text-sm text-gray-900 dark:text-white mt-0.5">
              <span class="font-medium">{getServiceDisplayName(alert.service)}</span>
              <span class="text-gray-500 dark:text-gray-400"> - </span>
              <span class={getAlertColor(alert.type)}>{alert.message}</span>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
