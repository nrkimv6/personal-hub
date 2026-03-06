<script lang="ts">
  import { theme, toggleTheme } from '$lib/stores/theme';
  import { Sun, Moon } from 'lucide-svelte';

  interface Props {
    collapsed?: boolean;
  }
  let { collapsed = false }: Props = $props();
</script>

<button
  onclick={toggleTheme}
  class="flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sidebar-muted hover:bg-sidebar-accent hover:text-sidebar-foreground w-full
    {collapsed ? 'lg:justify-center lg:px-0' : ''}"
  title={$theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환'}
>
  <span class="flex items-center justify-center">
    {#if $theme === 'dark'}
      <Sun size={18} />
    {:else}
      <Moon size={18} />
    {/if}
  </span>
  {#if !collapsed}
    <span class="text-sm">{$theme === 'dark' ? '라이트 모드' : '다크 모드'}</span>
  {/if}
</button>
