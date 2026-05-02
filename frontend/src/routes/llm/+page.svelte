<script lang="ts">
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import LlmTab from './LlmTab.svelte';
</script>

<svelte:head>
	<title>LLM 관리 | Monitor Page</title>
</svelte:head>

<div class="p-4 lg:p-6 space-y-4">
	<PageHeader title="LLM 관리" />
	<LlmTab />
</div>
