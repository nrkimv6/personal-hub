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

<div class="space-y-3 p-4 md:p-6">
	<PageHeader title="리스트 보드" />

	<!-- Import 섹션 -->
	<section class="rounded-lg border border-border bg-card p-4">
		<h2 class="mb-3 text-sm font-medium text-foreground">Markdown Import</h2>
		<div class="mb-2 flex flex-col gap-2 sm:flex-row">
			<input
				class="flex-1 rounded-md border border-border bg-background px-2.5 py-1.5 text-sm placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
				placeholder="데이터소스 이름 (필수)"
				bind:value={source}
			/>
			<input
				class="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-sm placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring sm:w-40"
				placeholder="배지 타입 (선택)"
				bind:value={badgeType}
			/>
		</div>
		<textarea
			class="mb-2 w-full rounded-md border border-border bg-background px-2.5 py-2 font-mono text-xs placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
			rows="6"
			placeholder="Markdown 표를 붙여넣으세요..."
			bind:value={markdownText}
		></textarea>
		<button
			class="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
			disabled={importing || !markdownText.trim() || !source.trim()}
			onclick={handleImport}
		>
			{importing ? 'Importing...' : 'Import'}
		</button>

		{#if importResult}
			<div class="mt-2 text-sm text-muted-foreground">
				신규 <span class="text-success">{importResult.created}</span> ·
				갱신 <span class="text-warning">{importResult.updated}</span> ·
				스킵 {importResult.skipped}
				{#if importResult.errors.length > 0}
					· 오류 <span class="text-destructive">{importResult.errors.length}</span>
				{/if}
			</div>
		{/if}
		{#if importError}
			<div class="mt-2 text-sm text-destructive">{importError}</div>
		{/if}
	</section>

	<!-- 컬럼 관리 -->
	<section class="rounded-lg border border-border bg-card p-3">
		<ColumnMenu {columns} onchange={loadColumns} />
	</section>

	<!-- 필터 -->
	<div class="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-3 py-2">
		{#if sources.length > 0}
			<select
				class="rounded-md border border-border bg-background px-2.5 py-1.5 text-sm focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
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
				class="w-40 rounded-md border border-border bg-background px-2.5 py-1.5 text-sm placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
				placeholder="source 필터"
				bind:value={filterSource}
			/>
		{/if}
		<input
			class="w-36 rounded-md border border-border bg-background px-2.5 py-1.5 text-sm placeholder:text-muted-foreground focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
			placeholder="badge_type 필터"
			bind:value={filterBadgeType}
		/>
		<button
			class="rounded-md border border-border bg-background px-3 py-1.5 text-sm transition-colors hover:bg-muted"
			onclick={applyFilter}>적용</button>
		{#if pager.total > 0}
			<span class="text-xs text-muted-foreground">총 {pager.total}개</span>
		{/if}
		{#if saveError}
			<span class="text-xs text-destructive">{saveError}</span>
		{/if}
	</div>

	<!-- 테이블 -->
	{#if loadError}
		<div class="text-sm text-destructive">{loadError}</div>
	{:else if loading}
		<div class="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">로딩 중...</div>
	{:else if items.length === 0}
		<div class="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">아이템이 없습니다. 위에서 Markdown을 import해 주세요.</div>
	{:else}
		<div class="overflow-hidden rounded-lg border border-border bg-card">
			<div class="overflow-x-auto">
				<table class="w-full text-xs">
					<thead class="border-b border-border bg-muted">
						<tr class="text-left">
							{#each [
								{ key: 'title', label: '제목' },
								{ key: 'duration_minutes', label: '소요시간' },
								{ key: 'source', label: 'source' },
								{ key: 'badge_type', label: 'badge' },
							] as col}
								<th
									class="cursor-pointer px-2 py-2 text-xs font-medium text-muted-foreground select-none"
									onclick={() => toggleSort(col.key)}
								>
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
								<th class="px-2 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground">{col.display_name}</th>
							{/each}
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each items as item (item.id)}
							<tr class="hover:bg-muted">
								<td class="max-w-[28rem] px-2 py-2">
									<a
										href={item.url}
										target="_blank"
										rel="noopener noreferrer"
										class="block truncate text-primary hover:underline"
									>{item.title}</a>
								</td>
								<td class="px-2 py-2 whitespace-nowrap text-muted-foreground">{formatDuration(item.duration_minutes)}</td>
								<td class="max-w-40 truncate px-2 py-2 whitespace-nowrap text-muted-foreground">{item.source ?? '—'}</td>
								<td class="max-w-32 truncate px-2 py-2 whitespace-nowrap text-muted-foreground">{item.badge_type ?? '—'}</td>
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
		</div>

		<!-- 페이지네이션 -->
		{#if pager.totalPages > 1}
			<div class="flex items-center gap-2 text-sm">
				<button
					class="rounded-md border border-border bg-background px-2 py-0.5 transition-colors hover:bg-muted disabled:opacity-40"
					disabled={pager.page <= 1}
					onclick={() => { pager.prev(); loadItems(); }}
				>←</button>
				<span class="text-muted-foreground">{pager.page} / {pager.totalPages}</span>
				<button
					class="rounded-md border border-border bg-background px-2 py-0.5 transition-colors hover:bg-muted disabled:opacity-40"
					disabled={pager.page >= pager.totalPages}
					onclick={() => { pager.next(); loadItems(); }}
				>→</button>
			</div>
		{/if}
	{/if}
</div>
