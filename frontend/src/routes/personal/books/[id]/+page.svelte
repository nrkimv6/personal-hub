<script lang="ts">
	import { page } from '$app/stores';
	import { AlertTriangle, ArrowLeft, Lock, RefreshCw } from 'lucide-svelte';
	import AccessBadges from '$lib/personal/books/components/AccessBadges.svelte';
	import CoverImage from '$lib/personal/books/components/CoverImage.svelte';
	import SegmentedControl from '$lib/personal/books/components/SegmentedControl.svelte';
	import StatusBadge from '$lib/personal/books/components/StatusBadge.svelte';
	import { booksState } from '$lib/personal/books/state/books.svelte';
	import type { Disposal } from '$lib/personal/books/types';

	const labels: Record<Disposal, string> = { undecided: '미정', keep: '보관', sell: '판매', scan: '스캔', discard: '폐기', review: '재검토' };
	const condition = { mint: '최상', good: '양호', fair: '보통', poor: '낡음', damaged: '손상', marked: '필기/표시 있음' };

	let confirmText = $state<string | null>(null);
	let pending = $state<Disposal | null>(null);
	const book = $derived(booksState.getBook($page.params.id ?? ''));
	const stale = $derived(book?.lastCheckedAt ? Math.floor((Date.now() - new Date(book.lastCheckedAt).getTime()) / (1000 * 60 * 60 * 24)) > 30 : false);
	const buybackLoading = $derived(book ? (booksState.buybackRefreshing[book.id] ?? false) : false);
	const buybackError = $derived(book ? booksState.buybackErrors[book.id] : null);

	function requestDisposal(disposal: string) {
		if (!book) return;
		const target = disposal as Disposal;
		if (target === 'sell' && book.scanPurpose === 'guillotine') {
			confirmText = '재단 스캔 예정인 책은 판매할 수 없습니다.';
			pending = null;
			return;
		}
		if ((target === 'sell' || target === 'discard') && book.highlights.length > 0) {
			pending = target;
			confirmText = `이 책에는 하이라이트가 ${book.highlights.length}개 있습니다. 정말 ${target === 'sell' ? '판매' : '폐기'}로 변경하시겠습니까?`;
			return;
		}
		if (target === 'discard' && book.library === 'no' && book.millie === 'no' && book.ebook === 'no' && book.usedBuyback === 'no') {
			pending = target;
			confirmText = '도서관·밀리·전자책·중고매입 모두 불가능한 책입니다. 다시 구하기 어려울 수 있습니다. 폐기로 변경할까요?';
			return;
		}
		booksState.setDisposal(book.id, target, `'${book.title}' -> ${labels[target]}`);
	}
</script>

{#if !book}
	<div class="mx-auto max-w-2xl">
		<a href="/personal/books" class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft class="h-4 w-4" /> 전체 도서로</a>
		<p class="mt-8 rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">책을 찾을 수 없습니다.</p>
	</div>
{:else}
	<div class="mx-auto max-w-3xl space-y-5">
		<a href="/personal/books" class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft class="h-4 w-4" /> 전체 도서로</a>

		<div class="flex gap-4">
			<CoverImage title={book.title} src={book.cover} class="h-40 w-28 shrink-0" />
			<div class="min-w-0 flex-1 space-y-2">
				<h1 class="text-xl font-semibold leading-tight text-foreground md:text-2xl">{book.title}</h1>
				<p class="text-sm text-muted-foreground">{book.author} · {book.publisher} · {book.publishedYear ?? '-'}</p>
				<p class="text-xs text-muted-foreground">ISBN {book.isbn}</p>
				<div class="flex flex-wrap items-center gap-2 pt-1">
					<StatusBadge status={book.disposal} />
					<StatusBadge status={book.recommendation} prefix="추천:" variant="outline" />
					{#if book.scanPurpose === 'guillotine'}
						<span class="inline-flex items-center gap-1 rounded-full border border-muted-foreground/30 bg-muted px-2 py-0.5 text-[10px] text-muted-foreground"><Lock class="h-3 w-3" /> 재단 스캔 예약 - 판매 잠금</span>
					{/if}
				</div>
			</div>
		</div>

		<section class="space-y-2 rounded-lg border border-border bg-card p-4">
			<h2 class="text-sm font-semibold">처분 결정</h2>
			<SegmentedControl
				value={book.disposal}
				onchange={requestDisposal}
				options={[
					{ value: 'undecided', label: '미정' },
					{ value: 'keep', label: '보관' },
					{ value: 'sell', label: '판매' },
					{ value: 'scan', label: '스캔' },
					{ value: 'discard', label: '폐기' },
					{ value: 'review', label: '재검토' }
				]}
				class="flex-wrap"
			/>
		</section>

		<section class="grid gap-3 md:grid-cols-2">
			<div class="space-y-3 rounded-lg border border-border bg-card p-4">
				<h2 class="text-sm font-semibold">내 책 정보</h2>
				<div class="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-2 text-sm"><span class="pt-1 text-xs text-muted-foreground">상태</span><span>{condition[book.condition]}</span></div>
				<label class="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-2 text-sm">
					<span class="pt-1 text-xs text-muted-foreground">위치</span>
					<input value={book.location} onblur={(event) => booksState.updateBook(book.id, { location: event.currentTarget.value })} class="w-full rounded border border-border bg-background px-2 py-1 text-sm" />
				</label>
				<div class="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-2 text-sm"><span class="pt-1 text-xs text-muted-foreground">재독 의향</span><span>{'★'.repeat(book.rereadIntent)}</span></div>
				<label class="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-2 text-sm">
					<span class="pt-1 text-xs text-muted-foreground">보관 이유</span>
					<textarea value={book.reasonToKeep ?? ''} onblur={(event) => booksState.updateBook(book.id, { reasonToKeep: event.currentTarget.value })} rows="2" class="w-full rounded border border-border bg-background px-2 py-1 text-sm"></textarea>
				</label>
			</div>

			<div class="space-y-3 rounded-lg border border-border bg-card p-4">
				<div class="flex items-center justify-between gap-3">
					<h2 class="text-sm font-semibold">외부 접근성</h2>
					{#if stale}
						<span class="inline-flex items-center gap-1 rounded-full border border-warning-muted bg-warning-light px-2 py-0.5 text-[10px] text-warning-foreground"><AlertTriangle class="h-3 w-3" /> 재확인 필요</span>
					{/if}
				</div>
				<AccessBadges library={book.library} millie={book.millie} ebook={book.ebook} used={book.usedBuyback} size="md" />
				<div class="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-2 text-sm"><span class="pt-1 text-xs text-muted-foreground">추천 매입가</span><span>{book.usedBuybackPrice ? `${book.usedBuybackPrice.toLocaleString()}원` : '-'}</span></div>
				<div class="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-2 text-sm">
					<span class="pt-1 text-xs text-muted-foreground">알라딘</span>
					<div class="space-y-2">
						<div class="grid grid-cols-3 gap-1">
							{#each ['최상', '상', '중'] as grade}
								{@const quote = (book.buybackQuotes ?? []).find((item) => item.grade === grade)}
								<div class="rounded-md border border-border bg-background px-2 py-1">
									<div class="text-[10px] text-muted-foreground">{grade}</div>
									<div class="text-xs font-medium">{quote?.price ? `${quote.price.toLocaleString()}원` : '-'}</div>
								</div>
							{/each}
						</div>
						{#if book.buybackRecommendation}
							<p class="text-[11px] text-muted-foreground">{book.buybackRecommendation.message}</p>
						{/if}
						{#if buybackError}
							<p class="text-[11px] text-error">{buybackError}</p>
						{/if}
					</div>
				</div>
				<div class="grid grid-cols-[88px_minmax(0,1fr)] items-start gap-2 text-sm"><span class="pt-1 text-xs text-muted-foreground">마지막 확인</span><span>{book.lastCheckedAt ?? '-'}</span></div>
				<button type="button" disabled={buybackLoading} onclick={() => booksState.refreshAladinBuyback(book.id)} class="inline-flex items-center justify-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60">
					<RefreshCw class="h-3.5 w-3.5 {buybackLoading ? 'animate-spin' : ''}" />
					알라딘 매입가 확인
				</button>
			</div>
		</section>

		<section class="space-y-3 rounded-lg border border-border bg-card p-4">
			<h2 class="text-sm font-semibold">하이라이트 ({book.highlights.length})</h2>
			{#if book.highlights.length === 0}
				<p class="text-xs text-muted-foreground">아직 등록된 하이라이트가 없습니다.</p>
			{:else}
				<ul class="space-y-3">
					{#each book.highlights as highlight}
						<li class="rounded-md border border-border bg-background p-3">
							<p class="text-sm leading-relaxed text-foreground">"{highlight.quote}"</p>
							<div class="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
								<span>p.{highlight.page}</span><span>중요도 {highlight.importance}</span>
								{#each highlight.tags as tag}<span class="rounded-full bg-muted px-2 py-0.5">#{tag}</span>{/each}
							</div>
							{#if highlight.memo}<p class="mt-2 text-xs text-muted-foreground">{highlight.memo}</p>{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	</div>
{/if}

{#if confirmText}
	<div class="fixed inset-0 z-50 flex items-end justify-center bg-foreground/30 p-4 md:items-center">
		<div class="w-full max-w-sm space-y-4 rounded-lg border border-border bg-card p-5 shadow-xl">
			<div class="flex items-start gap-2">
				<AlertTriangle class="h-5 w-5 text-warning" />
				<p class="text-sm text-foreground">{confirmText}</p>
			</div>
			<div class="flex justify-end gap-2">
				<button type="button" onclick={() => { confirmText = null; pending = null; }} class="rounded-md border border-border bg-card px-3 py-1.5 text-sm hover:bg-accent">취소</button>
				{#if pending && book}
					<button type="button" onclick={() => { booksState.setDisposal(book.id, pending as Disposal); confirmText = null; pending = null; }} class="rounded-md bg-error px-3 py-1.5 text-sm font-medium text-error-foreground">계속</button>
				{/if}
			</div>
		</div>
	</div>
{/if}

