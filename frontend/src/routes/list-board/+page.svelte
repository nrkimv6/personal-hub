<script lang="ts">
	import { onMount } from 'svelte';
	import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import { listBoardApi, type ListBoardItem, type ListBoardColumn } from '$lib/api';
	import { createPagePagination } from '$lib/utils/pagination.svelte';
	import ListBoardCell from './ListBoardCell.svelte';
	import ColumnMenu from './ColumnMenu.svelte';

	let markdownText = $state('');
	let source = $state('');
	let badgeType = $state('');
	let importing = $state(false);
	let importResult: { created: number; updated: number; skipped: number; errors: string[] } | null =
		$state(null);
	let importError = $state('');

	let items: ListBoardItem[] = $state([]);
	let columns: ListBoardColumn[] = $state([]);
	let sources: { source: string | null; count: number }[] = $state([]);
	let loading = $state(false);
	let loadError = $state('');

	let filterSource = $state('');
	let filterBadgeType = $state('');

	let sortKey = $state('');
	let sortDir: 'asc' | 'desc' | '' = $state('');

	let savingItemId: number | null = $state(null);
	let saveError = $state('');

	const pager = createPagePagination(50);

	async function loadAll() {
		await Promise.all([loadItems(), loadColumns(), loadSources()]);
	}

	async function loadColumns() {
		try {
			columns = await listBoardApi.listColumns();
		} catch {
			columns = [];
		}
	}

	async function loadSources() {
		try {
			sources = await listBoardApi.listSources();
		} catch {
			sources = [];
		}
	}

	async function loadItems() {
		loading = true;
		loadError = '';
		try {
			const res = await listBoardApi.listItems({
				page: pager.page,
				page_size: pager.pageSize,
				source: filterSource || undefined,
				badge_type: filterBadgeType || undefined,
				sort_by: sortKey || undefined,
				sort_order: sortDir || undefined,
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
			await loadAll();
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

	function toggleSort(key: string) {
		if (sortKey !== key) {
			sortKey = key;
			sortDir = 'asc';
		} else if (sortDir === 'asc') {
			sortDir = 'desc';
		} else if (sortDir === 'desc') {
			sortKey = '';
			sortDir = '';
		} else {
			sortDir = 'asc';
		}
		pager.reset();
		loadItems();
	}

	async function handleCellChange(item: ListBoardItem, colKey: string, newValue: unknown) {
		const prev = item.properties[colKey];
		// optimistic update
		item.properties = { ...item.properties, [colKey]: newValue };
		savingItemId = item.id;
		saveError = '';
		try {
			const updated = await listBoardApi.patchItemProperties(item.id, { [colKey]: newValue });
			const idx = items.findIndex((i) => i.id === item.id);
			if (idx >= 0) items[idx] = updated;
		} catch (e: unknown) {
			// rollback
			item.properties = { ...item.properties, [colKey]: prev };
			saveError = e instanceof Error ? e.message : '저장 실패';
		} finally {
			savingItemId = null;
		}
	}

	function formatDuration(minutes: number | null): string {
		if (minutes === null) return '—';
		if (minutes < 60) return `${minutes}분`;
		const h = Math.floor(minutes / 60);
		const m = minutes % 60;
		return m ? `${h}시간 ${m}분` : `${h}시간`;
	}

	onMount(loadAll);
</script>

<div class="flex flex-col gap-4 p-4">
	<PageHeader title="리스트 보드" />

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

	<!-- 컬럼 관리 -->
	<section class="rounded border border-zinc-700 bg-zinc-900 p-3">
		<ColumnMenu {columns} onchange={loadColumns} />
	</section>

	<!-- 필터 -->
	<div class="flex flex-wrap items-center gap-2">
		{#if sources.length > 0}
			<select
				class="rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-sm"
				bind:value={filterSource}
				onchange={applyFilter}
			>
				<option value="">전체 source</option>
				{#each sources as s}
					<option value={s.source ?? ''}>{s.source ?? '(없음)'} ({s.count})</option>
				{/each}
			</select>
		{:else}
			<input
				class="w-40 rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-sm placeholder-zinc-500"
				placeholder="source 필터"
				bind:value={filterSource}
			/>
		{/if}
		<input
			class="w-36 rounded border border-zinc-600 bg-zinc-800 px-2 py-1 text-sm placeholder-zinc-500"
			placeholder="badge_type 필터"
			bind:value={filterBadgeType}
		/>
		<button class="rounded bg-zinc-700 px-3 py-1 text-sm" onclick={applyFilter}>적용</button>
		{#if pager.total > 0}
			<span class="text-xs text-zinc-500">총 {pager.total}개</span>
		{/if}
		{#if saveError}
			<span class="text-xs text-red-400">{saveError}</span>
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
						{#each [
							{ key: 'title', label: '제목' },
							{ key: 'duration_minutes', label: '소요시간' },
							{ key: 'source', label: 'source' },
							{ key: 'badge_type', label: 'badge' },
						] as col}
							<th class="cursor-pointer pb-1 pr-3 select-none" onclick={() => toggleSort(col.key)}>
								<span class="flex items-center gap-0.5">
									{col.label}
									{#if sortKey === col.key && sortDir === 'asc'}
										<ChevronUp size={12} />
									{:else if sortKey === col.key && sortDir === 'desc'}
										<ChevronDown size={12} />
									{:else}
										<ChevronsUpDown size={12} class="opacity-30" />
									{/if}
								</span>
							</th>
						{/each}
						{#each columns.filter((c) => c.is_visible) as col (col.id)}
							<th class="pb-1 pr-2 text-zinc-400">{col.display_name}</th>
						{/each}
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
							<td class="py-1 pr-3 text-zinc-400">{item.badge_type ?? '—'}</td>
							{#each columns.filter((c) => c.is_visible) as col (col.id)}
								<ListBoardCell
									column={col}
									value={item.properties[col.key] ?? null}
									saving={savingItemId === item.id}
									onchange={(v) => handleCellChange(item, col.key, v)}
								/>
							{/each}
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
