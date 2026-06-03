<script lang="ts">
	import type { Disposal } from '../types';

	let { status, size = 'sm', variant = 'soft', prefix = '', class: className = '' } = $props<{
		status: Disposal;
		size?: 'sm' | 'md';
		variant?: 'soft' | 'outline';
		prefix?: string;
		class?: string;
	}>();

	const labels: Record<Disposal, string> = {
		undecided: '미정',
		keep: '보관',
		sell: '판매',
		scan: '스캔',
		discard: '폐기',
		review: '재검토'
	};
</script>

<span class="book-status book-status-{status} {size} {variant} {className}">
	{#if prefix}<span class="opacity-70">{prefix}</span>{/if}
	{labels[status]}
</span>

