<script lang="ts">
  import type { ServiceHealthItem } from '$lib/types';

  interface Props {
    health: Record<string, ServiceHealthItem>;
  }

  let { health }: Props = $props();

  // 서비스 그룹 정의: 관련 서비스들을 하나로 묶음
  const SERVICE_GROUPS: Record<string, { display: string; members: string[] }> = {
    api: { display: 'API Server', members: ['api', 'api_dev', 'api_internal', 'api_external'] },
    frontend: { display: 'Frontend', members: ['frontend', 'frontend_dev', 'frontend_internal', 'frontend_external'] },
    worker: { display: 'Worker', members: ['worker', 'worker_dev', 'worker_http'] },
    cloudflared: { display: 'Cloudflared', members: ['cloudflared'] },
    tunnel: { display: 'Tunnel', members: ['tunnel'] }
  };

  const GROUP_ORDER = ['api', 'frontend', 'worker', 'cloudflared', 'tunnel'];

  interface GroupedService {
    name: string;
    displayName: string;
    status: 'healthy' | 'unhealthy' | 'unknown';
    pid?: number;
    port?: number;
    internalMs?: number;
    externalMs?: number;
    errors: string[];
  }

  function getGroupedServices(): GroupedService[] {
    const result: GroupedService[] = [];
    const usedKeys = new Set<string>();

    for (const groupKey of GROUP_ORDER) {
      const group = SERVICE_GROUPS[groupKey];
      const members = group.members.filter(m => health[m]);

      if (members.length === 0) continue;

      members.forEach(m => usedKeys.add(m));

      // 그룹 내 서비스 정보 수집
      let status: 'healthy' | 'unhealthy' | 'unknown' = 'healthy';
      let pid: number | undefined;
      let port: number | undefined;
      let internalMs: number | undefined;
      let externalMs: number | undefined;
      const errors: string[] = [];

      for (const memberKey of members) {
        const info = health[memberKey];
        if (!info) continue;

        // 상태 결정: 하나라도 unhealthy면 전체 unhealthy
        if (info.status === 'unhealthy') status = 'unhealthy';
        else if (info.status === 'unknown' && status === 'healthy') status = 'unknown';

        // PID 체크 서비스에서 pid, port 가져오기
        if (memberKey === groupKey || memberKey === `${groupKey}_dev`) {
          pid = info.pid;
          port = info.port;
        }

        // HTTP 체크에서 응답시간 가져오기
        if (memberKey.endsWith('_internal') && info.response_time_ms) {
          internalMs = info.response_time_ms;
        }
        if (memberKey.endsWith('_external') && info.response_time_ms) {
          externalMs = info.response_time_ms;
        }
        // worker_http는 internal로 취급
        if (memberKey === 'worker_http' && info.response_time_ms) {
          internalMs = info.response_time_ms;
        }

        // 에러 메시지 수집
        if (info.error_message) {
          errors.push(info.error_message);
        }
      }

      result.push({
        name: groupKey,
        displayName: group.display,
        status,
        pid,
        port,
        internalMs,
        externalMs,
        errors
      });
    }

    // 그룹에 포함되지 않은 서비스 추가
    for (const [key, info] of Object.entries(health)) {
      if (usedKeys.has(key)) continue;
      result.push({
        name: key,
        displayName: key,
        status: info.status as 'healthy' | 'unhealthy' | 'unknown',
        pid: info.pid,
        port: info.port,
        internalMs: info.response_time_ms,
        errors: info.error_message ? [info.error_message] : []
      });
    }

    return result;
  }

  function getStatusColor(status: string) {
    switch (status) {
      case 'healthy': return 'text-green-500';
      case 'unhealthy': return 'text-red-500';
      default: return 'text-gray-400';
    }
  }

  function getStatusBgColor(status: string) {
    switch (status) {
      case 'healthy': return 'bg-green-100 dark:bg-green-900/30';
      case 'unhealthy': return 'bg-red-100 dark:bg-red-900/30';
      default: return 'bg-gray-100 dark:bg-gray-800';
    }
  }

  function getStatusLabel(status: string) {
    switch (status) {
      case 'healthy': return 'OK';
      case 'unhealthy': return 'Down';
      default: return '?';
    }
  }

  let groupedServices = $derived(getGroupedServices());
</script>

<div class="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
  <h2 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">서비스 상태</h2>

  {#if Object.keys(health).length === 0}
    <p class="text-gray-500 dark:text-gray-400 text-sm">
      헬스 모니터가 비활성화되어 있거나 데이터가 없습니다.
    </p>
  {:else}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {#each groupedServices as svc}
        <div class="flex items-start gap-3 p-3 rounded-lg {getStatusBgColor(svc.status)}">
          <span class="text-xl {getStatusColor(svc.status)} mt-0.5">●</span>
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-gray-900 dark:text-white truncate">
                {svc.displayName}
              </span>
              <span class="text-xs font-medium px-2 py-0.5 rounded {getStatusColor(svc.status)} {getStatusBgColor(svc.status)} shrink-0">
                {getStatusLabel(svc.status)}
              </span>
            </div>
            <div class="text-xs text-gray-500 dark:text-gray-400 mt-1 space-y-0.5">
              {#if svc.pid || svc.port}
                <div class="flex gap-3">
                  {#if svc.pid}<span>PID: {svc.pid}</span>{/if}
                  {#if svc.port}<span>Port: {svc.port}</span>{/if}
                </div>
              {/if}
              {#if svc.internalMs || svc.externalMs}
                <div class="flex gap-3">
                  {#if svc.internalMs}<span>내부: {svc.internalMs.toFixed(0)}ms</span>{/if}
                  {#if svc.externalMs}<span>외부: {svc.externalMs.toFixed(0)}ms</span>{/if}
                </div>
              {/if}
              {#if svc.errors.length > 0}
                <div class="text-red-500 truncate" title={svc.errors.join(', ')}>
                  {svc.errors[0]}
                </div>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
