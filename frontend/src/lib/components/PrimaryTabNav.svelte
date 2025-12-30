<script lang="ts">
  type Tab = { id: string; label: string; icon?: string };

  let { tabs, activeTab = $bindable() }: { tabs: Tab[]; activeTab: string } = $props();
</script>

<div class="border-b border-gray-200 dark:border-gray-700 mb-4">
  <nav class="flex space-x-1" aria-label="Primary Tabs">
    {#each tabs as tab}
      <button
        onclick={() => activeTab = tab.id}
        class="py-3 px-5 border-b-2 font-medium text-base transition-colors
          {activeTab === tab.id
            ? 'border-blue-500 text-blue-600 dark:text-blue-400'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
      >
        {#if tab.icon}<span class="mr-2">{tab.icon}</span>{/if}
        {tab.label}
      </button>
    {/each}
  </nav>
</div>
