<script lang="ts">
  type Tab = { id: string; label: string };

  let { tabs, activeTab = $bindable() }: { tabs: Tab[]; activeTab: string } = $props();
</script>

<div class="bg-gray-50 dark:bg-gray-800 rounded-lg p-1 mb-4 inline-flex">
  {#each tabs as tab}
    <button
      onclick={() => activeTab = tab.id}
      class="py-1.5 px-3 rounded-md text-sm font-medium transition-colors
        {activeTab === tab.id
          ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm'
          : 'text-gray-600 dark:text-gray-400 hover:text-gray-900'}"
    >
      {tab.label}
    </button>
  {/each}
</div>
