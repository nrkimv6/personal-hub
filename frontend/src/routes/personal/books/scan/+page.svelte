<script lang="ts">
	import { onDestroy } from 'svelte';
	import { AlertCircle, Camera, Plus, ScanLine } from 'lucide-svelte';
	import CoverImage from '$lib/personal/books/components/CoverImage.svelte';
	import { booksState } from '$lib/personal/books/state/books.svelte';

	type ScanState = { kind: 'idle' } | { kind: 'scanning' } | { kind: 'result'; isbn: string; title: string; author: string; duplicate: boolean };
	const mocks = [
		{ isbn: '9788937473135', title: '데미안', author: '헤르만 헤세', duplicateHint: true },
		{ isbn: '9788932473930', title: '호밀밭의 파수꾼', author: 'J. D. 샐린저', duplicateHint: false },
		{ isbn: '9788970127999', title: '변신', author: '프란츠 카프카', duplicateHint: false }
	];

	let scanState: ScanState = $state({ kind: 'idle' });
	let continuous = $state(false);
	let timer: number | null = null;

	function startScan() {
		if (timer) window.clearTimeout(timer);
		scanState = { kind: 'scanning' };
		timer = window.setTimeout(() => {
			const pick = mocks[Math.floor(Math.random() * mocks.length)];
			scanState = {
				kind: 'result',
				isbn: pick.isbn,
				title: pick.title,
				author: pick.author,
				duplicate: pick.duplicateHint || booksState.books.some((book) => book.isbn === pick.isbn)
			};
			timer = null;
		}, 900);
	}

	function closeResult(andContinue = false) {
		scanState = { kind: 'idle' };
		if (andContinue || continuous) startScan();
	}

	onDestroy(() => {
		if (timer) window.clearTimeout(timer);
	});
</script>

<div class="mx-auto max-w-md space-y-4">
	<div>
		<h1 class="text-xl font-semibold md:text-2xl">ISBN 바코드 등록</h1>
		<p class="mt-0.5 text-xs text-muted-foreground">실제 카메라 연결 전 단계의 mock scanner입니다.</p>
	</div>

	<div class="relative aspect-[3/4] overflow-hidden rounded-lg border border-border bg-foreground/90">
		<div class="absolute inset-0 flex items-center justify-center">
			<div class="relative h-40 w-64 rounded-md border-2 border-white/80">
				<span class="absolute -left-1 -top-1 h-4 w-4 border-l-2 border-t-2 border-primary"></span>
				<span class="absolute -right-1 -top-1 h-4 w-4 border-r-2 border-t-2 border-primary"></span>
				<span class="absolute -bottom-1 -left-1 h-4 w-4 border-b-2 border-l-2 border-primary"></span>
				<span class="absolute -bottom-1 -right-1 h-4 w-4 border-b-2 border-r-2 border-primary"></span>
				{#if scanState.kind === 'scanning'}<div class="absolute left-0 right-0 top-1/2 h-0.5 -translate-y-1/2 animate-pulse bg-primary"></div>{/if}
			</div>
		</div>
		<p class="absolute bottom-4 left-0 right-0 text-center text-xs text-white/80">{scanState.kind === 'scanning' ? '스캔 중...' : 'ISBN 바코드를 사각형 안에 비춰주세요'}</p>
		<div class="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2 py-1 text-[10px] text-white"><Camera class="h-3 w-3" /> 목업</div>
	</div>

	<button type="button" onclick={startScan} disabled={scanState.kind === 'scanning'} class="w-full rounded-lg bg-primary py-3 text-sm font-semibold text-primary-foreground shadow-sm disabled:opacity-60">
		<ScanLine class="mr-1 inline h-4 w-4" />
		{scanState.kind === 'scanning' ? '스캔 중...' : '스캔 시작'}
	</button>

	<label class="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm">
		<span>연속 스캔 모드</span>
		<input type="checkbox" bind:checked={continuous} class="h-4 w-4 accent-primary" />
	</label>
</div>

{#if scanState.kind === 'result'}
	<button class="fixed inset-0 z-50 bg-foreground/30" aria-label="스캔 결과 닫기" onclick={() => closeResult(false)}></button>
	<div class="fixed bottom-0 left-1/2 z-50 w-full max-w-md -translate-x-1/2 space-y-4 rounded-t-lg border border-border bg-card p-5 shadow-xl">
		{#if scanState.duplicate}
			<div class="flex items-center gap-2 rounded-md bg-warning-light p-2 text-xs text-warning-foreground"><AlertCircle class="h-4 w-4" /> 이미 소장 중인 책입니다.</div>
		{/if}
		<div class="flex gap-3">
			<CoverImage title={scanState.title} class="h-24 w-16 shrink-0" />
			<div class="min-w-0 flex-1">
				<h3 class="font-semibold">{scanState.title}</h3>
				<p class="text-xs text-muted-foreground">{scanState.author}</p>
				<p class="mt-1 text-[10px] text-muted-foreground">ISBN {scanState.isbn}</p>
			</div>
		</div>
		<div class="flex gap-2">
			<button type="button" onclick={() => closeResult(true)} class="flex-1 rounded-md border border-border bg-card py-2 text-sm hover:bg-accent">다시 스캔</button>
			<button type="button" onclick={() => closeResult(false)} disabled={scanState.duplicate} class="flex-1 rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"><Plus class="mr-1 inline h-4 w-4" /> {scanState.duplicate ? '이미 있음' : '추가'}</button>
		</div>
	</div>
{/if}

