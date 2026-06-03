<script lang="ts">
	import { Layers, Plus, Search } from 'lucide-svelte';
	import BookCard from '$lib/personal/books/components/BookCard.svelte';
	import BookRow from '$lib/personal/books/components/BookRow.svelte';
	import BookRowHeader from '$lib/personal/books/components/BookRowHeader.svelte';
	import EmptyState from '$lib/personal/books/components/EmptyState.svelte';
	import FilterChip from '$lib/personal/books/components/FilterChip.svelte';
	import { booksState } from '$lib/personal/books/state/books.svelte';
	import type { Disposal } from '$lib/personal/books/types';
	import { createOffsetPagination } from '$lib/utils/pagination.svelte';

	const tabs: { value: Disposal | 'all'; label: string }[] = [
		{ value: 'all', label: '전체' },
		{ value: 'undecided', label: '미정' },
		{ value: 'keep', label: '보관' },
		{ value: 'sell', label: '판매' },
		{ value: 'scan', label: '스캔' },
		{ value: 'discard', label: '폐기' },
		{ value: 'review', label: '재검토' }
	];

	let tab = $state<Disposal | 'all'>('all');
	let query = $state('');
	let accessFilter = $state<'all' | 'library' | 'millie' | 'buyback'>('all');
	let visibleCount = $state(24);
	const pager = createOffsetPagination(24);

	const counts = $derived.by(() => {
		const result: Record<string, number> = { all: booksState.books.length };
		for (const book of booksState.books) result[book.disposal] = (result[book.disposal] ?? 0) + 1;
		return result;
	});

	const filtered = $derived.by(() => {
		const normalized = query.trim().toLowerCase();
		return booksState.books.filter((book) => {
			if (tab !== 'all' && book.disposal !== tab) return false;
			if (accessFilter === 'library' && book.library !== 'yes') return false;
			if (accessFilter === 'millie' && book.millie !== 'yes') return false;
			if (accessFilter === 'buyback' && book.usedBuyback !== 'yes') return false;
			if (!normalized) return true;
			return book.title.toLowerCase().includes(normalized) || book.author.toLowerCase().includes(normalized) || book.isbn.includes(normalized);
		});
	});

	const visible = $derived(filtered.slice(0, visibleCount));
	const hasMore = $derived(visibleCount < filtered.length);

	$effect(() => {
		tab;
		query;
		accessFilter;
		pager.reset();
		visibleCount = pager.limit;
	});

	function showMore() {
		const loaded = Math.min(pager.limit, filtered.length - visibleCount);
		pager.advance(loaded, filtered.length);
		visibleCount += loaded;
	}
</script>

<div class="space-y-4">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div>
			<h1 class="text-xl font-semibold text-foreground md:text-2xl">전체 도서</h1>
			<p class="mt-0.5 text-xs text-muted-foreground">총 {booksState.books.length}권 · 미정 {counts.undecided ?? 0} · 판매 대기 {counts.sell ?? 0} · 재검토 {counts.review ?? 0}</p>
		</div>
		<div class="flex items-center gap-2">
			<a href="/personal/books/quick" class="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-accent">
				<Layers class="h-4 w-4" />
				빠른 정리
			</a>
			<a href="/personal/books/scan" class="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover">
				<Plus class="h-4 w-4" />
				<span class="hidden md:inline">ISBN으로 추가</span><span class="md:hidden">추가</span>
			</a>
		</div>
	</div>

	<div class="relative">
		<Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
		<input
			bind:value={query}
			placeholder="제목 · 저자 · ISBN으로 검색"
			class="w-full rounded-md border border-border bg-card py-2 pl-9 pr-3 text-sm outline-none placeholder:text-muted-foreground focus:border-primary focus:ring-1 focus:ring-primary"
		/>
	</div>

	<div class="space-y-2">
		<div class="flex flex-wrap items-center gap-2 overflow-x-auto">
			{#each tabs as item}
				<FilterChip active={tab === item.value} count={counts[item.value]} onclick={() => (tab = item.value)}>
					{item.label}
				</FilterChip>
			{/each}
		</div>
		<div class="flex flex-wrap items-center gap-2 overflow-x-auto">
			<span class="text-[11px] text-muted-foreground">접근성:</span>
			<FilterChip active={accessFilter === 'all'} onclick={() => (accessFilter = 'all')}>전체</FilterChip>
			<FilterChip active={accessFilter === 'library'} onclick={() => (accessFilter = 'library')}>도서관 O</FilterChip>
			<FilterChip active={accessFilter === 'millie'} onclick={() => (accessFilter = 'millie')}>밀리 O</FilterChip>
			<FilterChip active={accessFilter === 'buyback'} onclick={() => (accessFilter = 'buyback')}>중고매입 O</FilterChip>
		</div>
	</div>

	{#if booksState.error}
		<p class="rounded-md border border-warning-muted bg-warning-light px-3 py-2 text-xs text-warning-foreground">API 연결 전 sample data로 표시 중: {booksState.error}</p>
	{/if}

	{#if filtered.length === 0}
		<EmptyState title="해당 조건의 책이 없습니다" description="필터를 조정하거나 새 책을 등록해 보세요." />
	{:else}
		<div class="hidden overflow-hidden rounded-lg border border-border bg-card md:block">
			<BookRowHeader />
			{#each visible as book}
				<BookRow {book} />
			{/each}
		</div>
		<div class="space-y-2 md:hidden">
			{#each visible as book}
				<BookCard {book} />
			{/each}
		</div>
		{#if hasMore}
			<div class="flex justify-center">
				<button type="button" class="rounded-md border border-border bg-card px-4 py-2 text-sm hover:bg-accent" onclick={showMore}>더 보기</button>
			</div>
		{/if}
	{/if}
</div>

