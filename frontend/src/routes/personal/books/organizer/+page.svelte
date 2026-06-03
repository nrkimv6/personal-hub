<script lang="ts">
	import BookCard from '$lib/personal/books/components/BookCard.svelte';
	import EmptyState from '$lib/personal/books/components/EmptyState.svelte';
	import SegmentedControl from '$lib/personal/books/components/SegmentedControl.svelte';
	import { booksState } from '$lib/personal/books/state/books.svelte';

	type Tab = 'sell' | 'scan' | 'discard' | 'review';
	let tab = $state<Tab>('sell');

	const lists = $derived.by(() => {
		const today = new Date().toISOString().slice(0, 10);
		return {
			sell: booksState.books.filter((book) => book.sellStatus === 'ready'),
			scan: booksState.books.filter((book) => book.scanStatus === 'ready'),
			discard: booksState.books.filter((book) => book.discardStatus === 'ready'),
			review: booksState.books.filter((book) => book.disposal === 'review' && book.reviewDate && book.reviewDate <= today)
		};
	});
	const current = $derived(lists[tab]);
</script>

<div class="space-y-4">
	<div>
		<h1 class="text-xl font-semibold md:text-2xl">정리함</h1>
		<p class="mt-0.5 text-xs text-muted-foreground">지금 처리해야 할 책을 한눈에 모아 봅니다.</p>
	</div>
	<SegmentedControl
		value={tab}
		onchange={(value) => (tab = value as Tab)}
		options={[
			{ value: 'sell', label: `판매 대기 ${lists.sell.length}` },
			{ value: 'scan', label: `스캔 대기 ${lists.scan.length}` },
			{ value: 'discard', label: `폐기 대기 ${lists.discard.length}` },
			{ value: 'review', label: `오늘 재검토 ${lists.review.length}` }
		]}
		class="flex-wrap"
	/>

	{#if current.length === 0}
		<EmptyState title="비어 있습니다" description="이 큐에 들어온 책이 아직 없습니다." />
	{:else}
		<div class="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
			{#each current as book}
				<BookCard {book} />
			{/each}
		</div>
	{/if}
</div>

