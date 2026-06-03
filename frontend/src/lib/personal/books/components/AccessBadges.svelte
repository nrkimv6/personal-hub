<script lang="ts">
	import type { AccessState } from '../types';

	let { library, millie, ebook, used, size = 'sm', compact = false } = $props<{
		library: AccessState;
		millie: AccessState;
		ebook: AccessState;
		used: AccessState;
		size?: 'sm' | 'md';
		compact?: boolean;
	}>();

	const items = $derived([
		{ label: '도서관', state: library, key: 'library' },
		{ label: '밀리', state: millie, key: 'millie' },
		{ label: '전자책', state: ebook, key: 'ebook' },
		{ label: '중고', state: used, key: 'used' }
	]);

	function stateLabel(state: AccessState): string {
		if (state === 'yes') return '가능';
		if (state === 'check') return '확인 필요';
		return '없음';
	}
</script>

<div class="flex flex-wrap items-center gap-1">
	{#each items as item}
		{#if !(compact && item.state === 'no')}
			<span
				class="book-access book-access-{item.state === 'yes' ? item.key : item.state} {size}"
				title="{item.label}: {stateLabel(item.state)}"
			>
				{item.label}{item.state === 'check' ? ' ?' : ''}{item.state === 'no' ? ' x' : ''}
			</span>
		{/if}
	{/each}
</div>

