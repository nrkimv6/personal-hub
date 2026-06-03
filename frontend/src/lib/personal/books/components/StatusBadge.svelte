<script lang="ts">
	import type { Disposal } from '../types';

	const props = $props<{
		status: Disposal;
		size?: 'sm' | 'md';
		variant?: 'soft' | 'outline';
		prefix?: string;
		class?: string;
	}>();
	let status: Disposal = $derived(props.status);
	let size: 'sm' | 'md' = $derived(props.size ?? 'sm');
	let variant: 'soft' | 'outline' = $derived(props.variant ?? 'soft');
	let prefix: string = $derived(props.prefix ?? '');
	let className: string = $derived(props.class ?? '');

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

