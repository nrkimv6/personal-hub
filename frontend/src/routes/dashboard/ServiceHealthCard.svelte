<script lang="ts">
  import type { ServiceHealthItem } from '$lib/types';

  interface Props {
    health: Record<string, ServiceHealthItem>;
  }

  let { health }: Props = $props();

  function getStatusColor(status: string) {
    switch (status) {
      case 'healthy':
        return 'text-green-500';
      case 'unhealthy':
        return 'text-red-500';
      default:
        return 'text-gray-400';
    }
  }

  function getStatusBgColor(status: string) {
    switch (status) {
      case 'healthy':
        return 'bg-green-100 dark:bg-green-900/30';
      case 'unhealthy':
        return 'bg-red-100 dark:bg-red-900/30';
      default:
        return 'bg-gray-100 dark:bg-gray-800';
    }
  }

  function getStatusLabel(status: string) {
    switch (status) {
      case 'healthy':
        return 'OK';
      case 'unhealthy':
        return 'Down';
      default:
        return '?';
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

  const serviceOrder = ['api', 'frontend', 'worker', 'cloudflared', 'tunnel'];

  function getSortedServices() {
    const entries = Object.entries(health);
    return entries.sort(([a], [b]) => {
      const indexA = serviceOrder.indexOf(a);
      const indexB = serviceOrder.indexOf(b);
      if (indexA === -1 && indexB === -1) return a.localeCompare(b);
      if (indexA === -1) return 1;
      if (indexB === -1) return -1;
      return indexA - indexB;
    });
  }
</script>

<div class="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
  <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">서비스 상태</h2>

  {#if Object.keys(health).length === 0}
    <p class="text-gray-500 dark:text-gray-400 text-sm">
      헬스 모니터가 비활성화되어 있거나 데이터가 없습니다.
    </p>
  {:else}
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
      {#each getSortedServices() as [name, info]}
        <div class="flex items-center gap-3 p-3 rounded-lg {getStatusBgColor(info.status)}">
          <span class="text-xl {getStatusColor(info.status)}">●</span>
          <div class="flex-1 min-w-0">
            <div class="font-medium text-gray-900 dark:text-white truncate">
              {getServiceDisplayName(name)}
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
              {#if info.pid}
                <div>PID: {info.pid}</div>
              {/if}
              {#if info.port}
                <div>Port: {info.port}</div>
              {/if}
              {#if info.response_time_ms}
                <div>{info.response_time_ms.toFixed(0)}ms</div>
              {/if}
              {#if info.error_message}
                <div class="text-red-500 truncate" title={info.error_message}>
                  {info.error_message}
                </div>
              {/if}
            </div>
          </div>
          <span class="text-xs font-medium px-2 py-1 rounded {getStatusColor(info.status)} {getStatusBgColor(info.status)}">
            {getStatusLabel(info.status)}
          </span>
        </div>
      {/each}
    </div>
  {/if}
</div>
