<script lang="ts">
	import { onMount } from 'svelte';
	import { listBoardApi, type ListBoardItem } from '$lib/api';
	import { createPagePagination } from '$lib/utils/pagination.svelte';

	let markdownText = $state('');
	let source = $state('');
	let badgeType = $state('');
	let importing = $state(false);
	let importResult: { created: number; updated: number; skipped: number; errors: string[] } | null =
		$state(null);
	let importError = $state('');

	let items: ListBoardItem[] = $state([]);
	let loading = $state(false);
	let loadError = $state('');

	let filterSource = $state('');
	let filterBadgeType = $state('');

	const pager = createPagePagination(50);

	async function loadItems() {
		loading = true;
		loadError = '';
		try {
			const res = await listBoardApi.listItems({
				page: pager.page,
				page_size: pager.pageSize,
				source: filterSource || undefined,
				badge_type: filterBadgeType || undefined,
			});
			items = res.items;
			pager.total = res.total;
		} catch (e: unknown) {
			loadError = e instanceof Error ? e.message : '목록 조회 실패';
		} finally {
			loading = false;
		}
	}

	async function handleImport() {
		if (!markdownText.trim() || !source.trim()) return;
		importing = true;
		importResult = null;
		importError = '';
		try {
			const res = await listBoardApi.importItems({
				markdown_text: markdownText,
				source: source.trim(),
				badge_type: badgeType.trim() || undefined,
			});
			importResult = res;
			pager.reset();
			await loadItems();
		} catch (e: unknown) {
			importError = e instanceof Error ? e.message : 'Import 실패';
		} finally {
			importing = false;
		}
	}

	async function applyFilter() {
		pager.reset();
		await loadItems();
	}

	function formatDuration(minutes: number | null): string {
		if (minutes === null) return '—';
		if (minutes < 60) return `${minutes}분`;
		const h = Math.floor(minutes / 60);
		const m = minutes % 60;
		return m ? `${h}시간 ${m}분` : `${h}시간`;
	}

	onMount(loadItems);
</script>

<div class="flex flex-col gap-4 p-4">
	<h1 class="text-lg font-semibold">리스트 보드</h1>

	<!-- Import 섹션 -->
	<section class="rounded border border-zinc-700 bg-zinc-900 p-4">
		<h2 class="mb-3 text-sm font-medium text-zinc-300">Markdown Import</h2>
		<div class="mb-2 flex gap-2">
			<input
				class="flex-1 rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-sm placeholder-zinc-500"
				placeholder="데이터소스 이름 (필수)"
				bind:value={source}
			/>
			<input
				class="w-40 rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-sm placeholder-zinc-500"
				placeholder="배지 타입 (선택)"
				bind:value={badgeType}
			/>
		</div>
		<textarea
			class="mb-2 w-full rounded border border-zinc-600 bg-zinc-800 px-2 py-1 font-mono text-xs placeholder-zinc-500"
			rows="6"
			placeholder="Markdown 표를 붙여넣으세요..."
			bind:value={markdownText}
		></textarea>
		<button
			class="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium disabled:opacity-50"
			disabled={importing || !markdownText.trim() || !source.trim()}
			onclick={handleImport}
		>
			{importing ? 'Importing...' : 'Import'}
		</button>

		{#if importResult}
			<div class="mt-2 text-sm text-zinc-300">
				신규 <span class="text-green-400">{importResult.created}</span> ·
				갱신 <span class="text-yellow-400">{importResult.updated}</span> ·
				스킵 {importResult.skipped}
				{#if importResult.errors.length > 0}
					· 오류 <span class="text-red-400">{importResult.errors.length}</span>
				{/if}
			</div>
		{/if}
		{#if importError}
			<div class="mt-2 text-sm text-red-400">{importError}</div>
		{/if}
	</section>

	<!-- 필터 -->
	<div class="flex items-center gap-2">
		<input
			class="w-40 rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-sm placeholder-zinc-500"
			placeholder="source 필터"
			bind:value={filterSource}
		/>
		<input
			class="w-36 rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-sm placeholder-zinc-500"
			placeholder="badge_type 필터"
			bind:value={filterBadgeType}
		/>
		<button
			class="rounded bg-zinc-700 px-3 py-1 text-sm"
			onclick={applyFilter}
		>적용</button>
		{#if pager.total > 0}
			<span class="text-xs text-zinc-500">총 {pager.total}개</span>
		{/if}
	</div>

	<!-- 테이블 -->
	{#if loadError}
		<div class="text-sm text-red-400">{loadError}</div>
	{:else if loading}
		<div class="text-sm text-zinc-500">로딩 중...</div>
	{:else if items.length === 0}
		<div class="text-sm text-zinc-500">아이템이 없습니다. 위에서 Markdown을 import해 주세요.</div>
	{:else}
		<div class="overflow-x-auto">
			<table class="w-full text-xs">
				<thead>
					<tr class="border-b border-zinc-700 text-left text-zinc-400">
						<th class="pb-1 pr-3">제목</th>
						<th class="pb-1 pr-3">소요시간</th>
						<th class="pb-1 pr-3">source</th>
						<th class="pb-1">badge</th>
					</tr>
				</thead>
				<tbody>
					{#each items as item (item.id)}
						<tr class="border-b border-zinc-800 hover:bg-zinc-800/40">
							<td class="py-1 pr-3">
								<a
									href={item.url}
									target="_blank"
									rel="noopener noreferrer"
									class="text-blue-400 hover:underline"
								>{item.title}</a>
							</td>
							<td class="py-1 pr-3 text-zinc-400">{formatDuration(item.duration_minutes)}</td>
							<td class="py-1 pr-3 text-zinc-400">{item.source ?? '—'}</td>
							<td class="py-1 text-zinc-400">{item.badge_type ?? '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- 페이지네이션 -->
		{#if pager.totalPages > 1}
			<div class="flex items-center gap-2 text-sm">
				<button
					class="rounded px-2 py-0.5 disabled:opacity-40"
					disabled={pager.page <= 1}
					onclick={() => { pager.prev(); loadItems(); }}
				>←</button>
				<span class="text-zinc-400">{pager.page} / {pager.totalPages}</span>
				<button
					class="rounded px-2 py-0.5 disabled:opacity-40"
					disabled={pager.page >= pager.totalPages}
					onclick={() => { pager.next(); loadItems(); }}
				>→</button>
			</div>
		{/if}
	{/if}
</div>
