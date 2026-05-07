<script lang="ts">
	import type { ParsedLine } from '$lib/dev-runner/log-types';

	interface Props {
		line: ParsedLine;
		expanded: boolean;
		onExpand: () => void;
		onCollapse: () => void;
	}

	let { line, expanded, onExpand, onCollapse }: Props = $props();
</script>

<div class="dr-log-line dr-log-line-noise flex items-center py-0 leading-5 {line.isStale ? 'opacity-30' : ''}">
	{#if expanded}
		<span class="text-gray-600 italic">... {line.noiseCount} hidden lines ...</span>
		<button onclick={onCollapse} class="ml-2 text-gray-600 hover:text-gray-400">▲</button>
	{:else}
		<button onclick={onExpand} class="text-gray-600 hover:text-gray-400 italic w-full text-left">
			... {line.noiseCount} hidden lines ...
		</button>
	{/if}
</div>
