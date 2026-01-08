<script lang="ts">
  type Tab = { id: string; label: string; icon?: string };

  let { tabs, activeTab = $bindable() }: { tabs: Tab[]; activeTab: string } = $props();
</script>

<div class="border-b border-border dark:border-gray-700 mb-4">
  <nav class="flex space-x-1" aria-label="Primary Tabs">
    {#each tabs as tab}
      <button
        onclick={() => activeTab = tab.id}
        class="py-3 px-5 border-b-2 font-medium text-base transition-colors
          {activeTab === tab.id
            ? 'border-blue-500 text-primary dark:text-blue-400'
            : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'}"
      >
        {#if tab.icon}<span class="mr-2">{tab.icon}</span>{/if}
        {tab.label}
      </button>
    {/each}
  </nav>
</div>
