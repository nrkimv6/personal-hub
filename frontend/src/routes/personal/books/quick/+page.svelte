<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import AccessBadges from '$lib/personal/books/components/AccessBadges.svelte';
	import CoverImage from '$lib/personal/books/components/CoverImage.svelte';
	import DatePresetPicker from '$lib/personal/books/components/DatePresetPicker.svelte';
	import EmptyState from '$lib/personal/books/components/EmptyState.svelte';
	import { booksState } from '$lib/personal/books/state/books.svelte';
	import type { Disposal } from '$lib/personal/books/types';

	const actions: { key: Disposal; label: string; className: string; shortcut: string }[] = [
		{ key: 'keep', label: '보관', className: 'bg-[var(--book-action-keep)]', shortcut: 'K' },
		{ key: 'sell', label: '판매', className: 'bg-[var(--book-action-sell)]', shortcut: 'S' },
		{ key: 'scan', label: '스캔', className: 'bg-[var(--book-action-scan)]', shortcut: 'C' },
		{ key: 'discard', label: '폐기', className: 'bg-[var(--book-action-discard)]', shortcut: 'D' }
	];
	const labels: Record<Disposal, string> = { undecided: '미정', keep: '보관', sell: '판매', scan: '스캔', discard: '폐기', review: '재검토' };

	let idx = $state(0);
	let showLater = $state(false);
	const queue = $derived(booksState.books.filter((book) => book.disposal === 'undecided'));
	const current = $derived(queue[idx]);

	function next() {
		idx = Math.min(idx + 1, queue.length);
	}

	function decide(disposal: Disposal) {
		if (!current) return;
		booksState.setDisposal(current.id, disposal, `'${current.title}' -> ${labels[disposal]}`);
		next();
	}

	function later(date: string) {
		if (!current) return;
		booksState.updateBook(current.id, { disposal: 'review', reviewDate: date });
		showLater = false;
		next();
	}

	function onKey(event: KeyboardEvent) {
		if (showLater) return;
		const key = event.key.toLowerCase();
		if (key === 'k') decide('keep');
		if (key === 's') decide('sell');
		if (key === 'c') decide('scan');
		if (key === 'd') decide('discard');
		if (key === 'l') showLater = true;
	}

	onMount(() => window.addEventListener('keydown', onKey));
	onDestroy(() => window.removeEventListener('keydown', onKey));
</script>

<div class="mx-auto max-w-md space-y-4">
	<div class="flex items-baseline justify-between">
		<h1 class="text-xl font-semibold md:text-2xl">빠른 정리</h1>
		<span class="text-xs text-muted-foreground">{Math.min(idx + 1, queue.length)} / {queue.length}</span>
	</div>

	{#if !current}
		<EmptyState title="정리할 책이 없습니다" description="모든 미정 도서를 처리했습니다." />
	{:else}
		<article class="space-y-4 rounded-lg border border-border bg-card p-5 shadow-sm">
			<div class="flex justify-center">
				<CoverImage title={current.title} src={current.cover} class="h-56 w-40" />
			</div>
			<div class="space-y-1 text-center">
				<h2 class="text-lg font-semibold leading-snug">{current.title}</h2>
				<p class="text-sm text-muted-foreground">{current.author} · {current.publisher}</p>
			</div>
			<div class="flex justify-center">
				<AccessBadges library={current.library} millie={current.millie} ebook={current.ebook} used={current.usedBuyback} />
			</div>
			{#if current.reasonToKeep}
				<p class="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">보관 이유: {current.reasonToKeep}</p>
			{/if}
			<p class="text-center text-[11px] text-muted-foreground">재독 의향 {'★'.repeat(current.rereadIntent)}{current.usedBuybackPrice ? ` · 매입가 ${current.usedBuybackPrice.toLocaleString()}원` : ''}</p>
		</article>

		<div class="grid grid-cols-2 gap-2">
			{#each actions as action}
				<button type="button" onclick={() => decide(action.key)} class="flex flex-col items-center justify-center gap-1 rounded-lg py-4 text-white shadow-sm transition-transform active:scale-[0.98] {action.className}">
					<span class="text-base font-semibold">{action.label}</span>
					<span class="text-[10px] opacity-80">키 {action.shortcut}</span>
				</button>
			{/each}
		</div>
		<button type="button" onclick={() => (showLater = true)} class="w-full rounded-lg bg-[var(--book-action-later)] py-3 text-white shadow-sm active:scale-[0.99]">나중에 결정 (L)</button>
	{/if}
</div>

{#if showLater}
	<button class="fixed inset-0 z-50 flex items-end justify-center bg-foreground/30" aria-label="나중에 결정 닫기" onclick={() => (showLater = false)}></button>
	<div class="fixed bottom-0 left-1/2 z-50 w-full max-w-md -translate-x-1/2 space-y-3 rounded-t-lg border border-border bg-card p-5 shadow-xl">
		<h3 class="text-sm font-semibold">언제 다시 볼까요?</h3>
		<DatePresetPicker onpick={later} />
	</div>
{/if}

