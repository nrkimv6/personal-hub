<script lang="ts">
  import { Monitor } from 'lucide-svelte';
  import type { SystemResource } from '$lib/types';

  interface Props {
    resource: SystemResource;
  }

  let { resource }: Props = $props();

  function getProgressColor(percent: number) {
    if (percent >= 90) return 'bg-error';
    if (percent >= 70) return 'bg-warning';
    return 'bg-primary';
  }

  function formatMB(mb: number) {
    if (mb >= 1024) {
      return `${(mb / 1024).toFixed(1)} GB`;
    }
    return `${mb.toFixed(0)} MB`;
  }
</script>

<div class="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
  <h2 class="text-lg font-semibold text-foreground dark:text-white mb-4 flex items-center gap-2">
    <Monitor size={20} class="text-primary" />
    시스템 리소스
  </h2>

  <div class="space-y-4">
    <!-- CPU -->
    <div>
      <div class="flex justify-between text-sm mb-1">
        <span class="text-muted-foreground dark:text-muted-foreground">CPU</span>
        <span class="font-medium text-foreground dark:text-white">{resource.cpu_percent.toFixed(1)}%</span>
      </div>
      <div class="w-full h-2 bg-secondary dark:bg-gray-700 rounded-full overflow-hidden">
        <div
          class="h-full transition-all duration-300 {getProgressColor(resource.cpu_percent)}"
          style="width: {Math.min(resource.cpu_percent, 100)}%"
        ></div>
      </div>
    </div>

    <!-- Memory -->
    <div>
      <div class="flex justify-between text-sm mb-1">
        <span class="text-muted-foreground dark:text-muted-foreground">Memory</span>
        <span class="font-medium text-foreground dark:text-white">{resource.memory_percent.toFixed(1)}%</span>
      </div>
      <div class="w-full h-2 bg-secondary dark:bg-gray-700 rounded-full overflow-hidden">
        <div
          class="h-full transition-all duration-300 {getProgressColor(resource.memory_percent)}"
          style="width: {Math.min(resource.memory_percent, 100)}%"
        ></div>
      </div>
      <div class="text-xs text-muted-foreground dark:text-muted-foreground mt-1">
        {formatMB(resource.memory_used_mb)} / {formatMB(resource.memory_total_mb)}
      </div>
    </div>

    <!-- 탭/컨텍스트 -->
    <div class="pt-2 border-t border-border dark:border-gray-700">
      <div class="flex justify-between text-sm">
        <span class="text-muted-foreground dark:text-muted-foreground">탭 / 컨텍스트</span>
        <span class="font-medium text-foreground dark:text-white">
          {resource.active_tabs} / {resource.browser_contexts}
        </span>
      </div>
    </div>
  </div>
</div>
