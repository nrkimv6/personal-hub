<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import {
		CheckCircle2,
		RefreshCw,
		Loader2,
		X,
		Trash2,
		Tag,
		Check,
		SquareCheck,
		Square
	} from 'lucide-svelte';

	interface FileReview {
		id: number;
		file_path: string;
		final_category_id: number | null;
		ai_confidence: number | null;
		status: string;
	}

	interface Category {
		id: number;
		name: string;
		full_path: string;
		parent_id: number | null;
		children: Category[];
	}

	let files: FileReview[] = $state([]);
	let totalCount = $state(0);
	let selectedIds = $state<number[]>([]);
	let loading = $state(false);
	let loadingMore = $state(false);
	let sortBy = $state('confidence');
	let sortDir = $state('asc');
	let confidenceFilter = $state<'all' | 'low' | 'mid' | 'high'>('all');
	let filterCategoryId = $state<number | ''>('');

	const PAGE_SIZE = 100;
	let currentOffset = $state(0);
	let hasMore = $state(false);

	// 카테고리 목록 (이름 표시용)
	let categories = $state<Category[]>([]);
	let flatCategories = $state<Category[]>([]);
	let categoryMap = $derived(new Map(flatCategories.map((c) => [c.id, c.full_path])));

	// 카테고리 변경 모달
	let showCategoryPicker = $state(false);

	onMount(() => {
		loadCategories();
		loadFiles(true);
	});

	async function loadCategories() {
		try {
			const res = await fetchWithTimeout('/api/ic/categories?include_tree=true');
			if (res.ok) {
				const data = await res.json();
				categories = data.categories ?? [];
				flatCategories = flattenCategories(categories);
			}
		} catch {
			/* ignore */
		}
	}

	function flattenCategories(cats: any[]): Category[] {
		let result: Category[] = [];
		for (const cat of cats) {
			result.push({ id: cat.id, name: cat.name, full_path: cat.full_path, parent_id: cat.parent_id ?? null, children: cat.children ?? [] });
			if (cat.children?.length > 0) {
				result = result.concat(flattenCategories(cat.children));
			}
		}
		return result;
	}

	async function loadFiles(reset = false) {
		if (reset) {
			loading = true;
			currentOffset = 0;
			files = [];
		} else {
			loadingMore = true;
		}

		try {
			const params = new URLSearchParams({
				status: 'ai_classified',
				order_by: sortBy === 'date' ? 'extracted_date' : 'ai_confidence',
				order_dir: sortDir,
				limit: String(PAGE_SIZE),
				skip: String(reset ? 0 : currentOffset)
			});
			if (filterCategoryId !== '') {
				params.append('category_id', String(filterCategoryId));
			}
			const response = await fetchWithTimeout(`/api/ic/files?${params}`);
			if (response.ok) {
				const data = await response.json();
				const newFiles: FileReview[] = data.files || [];
				if (reset) {
					files = newFiles;
				} else {
					files = [...files, ...newFiles];
				}
				currentOffset = (reset ? 0 : currentOffset) + newFiles.length;
				hasMore = newFiles.length === PAGE_SIZE;
				totalCount = data.total ?? files.length;
			}
		} catch (err) {
			console.error('파일 로드 실패:', err);
		} finally {
			loading = false;
			loadingMore = false;
		}
	}

	// 신뢰도 필터링 (클라이언트)
	let filteredFiles = $derived(
		confidenceFilter === 'all'
			? files
			: files.filter((f) => {
					const c = f.ai_confidence ?? 0;
					if (confidenceFilter === 'low') return c < 0.7;
					if (confidenceFilter === 'mid') return c >= 0.7 && c < 0.9;
					return c >= 0.9; // high
				})
	);

	function toggleFile(id: number) {
		if (selectedIds.includes(id)) {
			selectedIds = selectedIds.filter((x) => x !== id);
		} else {
			selectedIds = [...selectedIds, id];
		}
	}

	function selectAll() {
		const allIds = filteredFiles.map((f) => f.id);
		const allSelected = allIds.every((id) => selectedIds.includes(id));
		if (allSelected) {
			// 현재 필터된 항목 전체 해제
			const filterSet = new Set(allIds);
			selectedIds = selectedIds.filter((id) => !filterSet.has(id));
		} else {
			// 현재 필터된 항목 전체 선택
			const existing = new Set(selectedIds);
			for (const id of allIds) existing.add(id);
			selectedIds = Array.from(existing);
		}
	}

	let allSelected = $derived(
		filteredFiles.length > 0 && filteredFiles.every((f) => selectedIds.includes(f.id))
	);

	async function approveSelected() {
		if (selectedIds.length === 0) return;
		try {
			const res = await fetchWithTimeout('/api/ic/files/approve', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: selectedIds })
			});
			if (!res.ok) throw new Error('승인 실패');
			selectedIds = [];
			await loadFiles(true);
		} catch (err) {
			alert('승인 실패');
		}
	}

	async function deleteSelected() {
		if (selectedIds.length === 0) return;
		if (!confirm(`선택한 ${selectedIds.length}개 이미지를 삭제하시겠습니까?`)) return;
		try {
			const res = await fetchWithTimeout('/api/ic/files/bulk-delete', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: selectedIds })
			});
			if (!res.ok) throw new Error('삭제 실패');
			selectedIds = [];
			await loadFiles(true);
		} catch (err: any) {
			alert(`삭제 실패: ${err.message}`);
		}
	}

	async function assignCategory(categoryId: number) {
		if (selectedIds.length === 0) return;
		try {
			const res = await fetchWithTimeout('/api/ic/files/bulk-classify', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: selectedIds, category_id: categoryId })
			});
			if (!res.ok) throw new Error('카테고리 지정 실패');
			selectedIds = [];
			showCategoryPicker = false;
			await loadFiles(true);
		} catch (err: any) {
			alert(`카테고리 지정 실패: ${err.message}`);
		}
	}

	async function changeCategoryForFile(file: FileReview, newCategoryId: number) {
		try {
			const res = await fetchWithTimeout(`/api/ic/files/${file.id}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					final_category_id: newCategoryId,
					is_user_corrected: true
				})
			});
			if (!res.ok) throw new Error('카테고리 변경 실패');
			file.final_category_id = newCategoryId;
			files = [...files];
		} catch (err) {
			console.error('카테고리 변경 실패:', err);
		}
	}

	function getThumbnailUrl(fileId: number): string {
		return `/api/ic/files/${fileId}/thumbnail`;
	}

	function getCategoryName(categoryId: number | null): string {
		if (!categoryId) return '—';
		return categoryMap.get(categoryId) ?? `#${categoryId}`;
	}

	function getConfidenceColor(conf: number | null): string {
		if (!conf) return 'text-muted-foreground';
		if (conf >= 0.9) return 'text-green-400';
		if (conf >= 0.7) return 'text-yellow-400';
		return 'text-red-400';
	}

	function getConfidenceBgColor(conf: number | null): string {
		if (!conf) return 'bg-muted';
		if (conf >= 0.9) return 'bg-green-500/20';
		if (conf >= 0.7) return 'bg-yellow-500/20';
		return 'bg-red-500/20';
	}

	// 정렬/필터 변경 시 재로드
	function handleFilterChange() {
		loadFiles(true);
	}
</script>

<div class="space-y-4">
	<!-- 헤더 -->
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div>
			<div class="flex items-center gap-2">
				<CheckCircle2 class="size-5 text-primary" />
				<h2 class="text-xl font-bold tracking-tight">검토 및 승인</h2>
				{#if totalCount > 0}
					<span class="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
						{totalCount.toLocaleString()}건
					</span>
				{/if}
			</div>
			<p class="mt-1 text-sm text-muted-foreground">AI가 분류한 결과를 검토하고 승인합니다.</p>
		</div>
		<button
			onclick={() => loadFiles(true)}
			disabled={loading}
			class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50 transition-colors"
		>
			<RefreshCw class="size-3.5 {loading ? 'animate-spin' : ''}" />
			새로고침
		</button>
	</div>

	<!-- 필터 바 -->
	<div class="rounded-xl border border-border bg-card p-3">
		<div class="flex flex-wrap items-center gap-3">
			<!-- 신뢰도 필터 -->
			<div class="flex items-center gap-0.5 rounded-md border border-border bg-muted p-0.5">
				{#each [
					{ key: 'all', label: '전체' },
					{ key: 'low', label: '낮음 <70%', color: 'text-red-600' },
					{ key: 'mid', label: '중간 70-90%', color: 'text-yellow-600' },
					{ key: 'high', label: '높음 ≥90%', color: 'text-green-600' }
				] as filter}
					<button
						onclick={() => {
							confidenceFilter = filter.key as typeof confidenceFilter;
						}}
						class="rounded px-2.5 py-1 text-[11px] font-medium transition-all {confidenceFilter === filter.key
							? 'bg-card text-foreground shadow-sm'
							: 'text-muted-foreground hover:text-foreground'}"
					>
						{filter.label}
					</button>
				{/each}
			</div>

			<!-- 카테고리 필터 -->
			<select
				bind:value={filterCategoryId}
				onchange={() => handleFilterChange()}
				class="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
			>
				<option value="">전체 카테고리</option>
				{#each flatCategories as cat}
					<option value={cat.id}>{cat.full_path}</option>
				{/each}
			</select>

			<!-- 정렬 -->
			<select
				bind:value={sortBy}
				onchange={handleFilterChange}
				class="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
			>
				<option value="confidence">신뢰도순</option>
				<option value="date">날짜순</option>
			</select>
			<select
				bind:value={sortDir}
				onchange={handleFilterChange}
				class="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
			>
				<option value="asc">오름차순</option>
				<option value="desc">내림차순</option>
			</select>

			<!-- 전체 선택 -->
			<button
				onclick={selectAll}
				class="ml-auto flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-accent transition-colors"
			>
				{#if allSelected}
					<SquareCheck class="size-3.5 text-primary" />
					전체 해제
				{:else}
					<Square class="size-3.5" />
					전체 선택 ({filteredFiles.length})
				{/if}
			</button>
		</div>
	</div>

	<!-- 벌크 액션 바 -->
	{#if selectedIds.length > 0}
		<div class="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
			<span class="text-xs font-medium text-primary">{selectedIds.length}개 선택됨</span>
			<div class="mx-1 h-4 w-px bg-border"></div>
			<button
				onclick={approveSelected}
				class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
			>
				<Check class="size-3" />
				승인
			</button>
			<button
				onclick={() => {
					loadCategories();
					showCategoryPicker = true;
				}}
				class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
			>
				<Tag class="size-3" />
				카테고리 변경
			</button>
			<button
				onclick={deleteSelected}
				class="flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/10"
			>
				<Trash2 class="size-3" />
				삭제
			</button>
			<button
				onclick={() => (selectedIds = [])}
				class="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
			>
				<X class="size-3" />
				선택 해제
			</button>
		</div>
	{/if}

	<!-- 콘텐츠 -->
	<div class="rounded-xl border bg-card">
		{#if loading}
			<div class="flex items-center justify-center py-16 text-sm text-muted-foreground gap-2">
				<Loader2 class="size-4 animate-spin" />
				로딩 중...
			</div>
		{:else if filteredFiles.length === 0}
			<div class="py-16 text-center text-sm text-muted-foreground">
				{confidenceFilter !== 'all' ? '해당 신뢰도 범위의 파일이 없습니다.' : '검토할 파일이 없습니다.'}
			</div>
		{:else}
			<div
				class="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
			>
				{#each filteredFiles as file (file.id)}
					{@const isSelected = selectedIds.includes(file.id)}
					<div
						role="button"
						tabindex="0"
						class="group relative aspect-square cursor-pointer overflow-hidden rounded-lg border bg-muted transition-all {isSelected
							? 'ring-2 ring-primary'
							: 'hover:ring-1 hover:ring-primary/50'}"
						onclick={() => toggleFile(file.id)}
						onkeydown={(e) => e.key === 'Enter' && toggleFile(file.id)}
					>
						<img
							src={getThumbnailUrl(file.id)}
							alt={file.file_path}
							loading="lazy"
							decoding="async"
							class="absolute inset-0 h-full w-full object-cover transition-transform group-hover:scale-105"
							onerror={(e) => {
								(e.target as HTMLImageElement).style.display = 'none';
							}}
						/>

						<!-- Fallback -->
						<div
							class="flex h-full w-full items-center justify-center text-[10px] text-muted-foreground/50"
						>
							{file.id}
						</div>

						<!-- 체크박스 -->
						<button
							class="absolute left-1.5 top-1.5 z-10 flex size-5 items-center justify-center rounded border border-white/50 bg-black/40 opacity-0 transition-all group-hover:opacity-100 {isSelected
								? '!opacity-100 border-primary bg-primary text-white'
								: ''}"
							onclick={(e) => {
								e.stopPropagation();
								toggleFile(file.id);
							}}
							aria-label="Select image"
						>
							{#if isSelected}
								<Check class="size-3" />
							{/if}
						</button>

						<!-- 신뢰도 -->
						{#if file.ai_confidence}
							<div class="absolute right-1.5 top-1.5">
								<span
									class="rounded px-1.5 py-0.5 text-[10px] font-bold {getConfidenceBgColor(file.ai_confidence)} {getConfidenceColor(file.ai_confidence)}"
								>
									{Math.round(file.ai_confidence * 100)}%
								</span>
							</div>
						{/if}

						<!-- 하단 정보 -->
						<div
							class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent p-1.5 pt-5"
						>
							<p class="truncate text-[10px] font-medium text-white">
								{file.file_path.split(/[/\\]/).pop() ?? `file_${file.id}`}
							</p>
							<p class="truncate text-[9px] text-white/70">
								{getCategoryName(file.final_category_id)}
							</p>
							<!-- 개별 카테고리 변경 드롭다운 -->
							<!-- svelte-ignore a11y_click_events_have_key_events -->
							<!-- svelte-ignore a11y_no_static_element_interactions -->
							<div onclick={(e) => e.stopPropagation()} class="mt-1">
								<select
									value={file.final_category_id ?? ''}
									onchange={(e) => {
										const val = (e.currentTarget as HTMLSelectElement).value;
										if (val) changeCategoryForFile(file, parseInt(val));
									}}
									class="w-full rounded border border-white/20 bg-black/50 px-1 py-0.5 text-[9px] text-white focus:outline-none"
								>
									<option value="">— 변경 —</option>
									{#each flatCategories as cat}
										<option value={cat.id}>{cat.full_path}</option>
									{/each}
								</select>
							</div>
						</div>
					</div>
				{/each}
			</div>

			<!-- 더 보기 -->
			{#if hasMore}
				<div class="flex justify-center border-t py-3">
					<button
						onclick={() => loadFiles(false)}
						disabled={loadingMore}
						class="inline-flex items-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-50 transition-colors"
					>
						{#if loadingMore}
							<Loader2 class="size-4 animate-spin" />
							로딩 중...
						{:else}
							더 보기 ({files.length}/{totalCount})
						{/if}
					</button>
				</div>
			{/if}
		{/if}
	</div>
</div>

<!-- 카테고리 선택 모달 -->
{#if showCategoryPicker}
	<div
		role="button"
		tabindex="-1"
		class="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
		onclick={() => (showCategoryPicker = false)}
		onkeydown={(e) => e.key === 'Escape' && (showCategoryPicker = false)}
	></div>
	<div
		class="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card p-4 shadow-2xl"
	>
		<h3 class="mb-3 text-sm font-semibold text-foreground">카테고리 선택</h3>
		{#if categories.length === 0}
			<p class="text-xs text-muted-foreground">카테고리가 없습니다.</p>
		{:else}
			<div class="max-h-60 space-y-1 overflow-y-auto">
				{#each flatCategories as cat}
					<button
						onclick={() => assignCategory(cat.id)}
						class="flex w-full items-center rounded-md px-3 py-2 text-left text-xs font-medium text-foreground hover:bg-accent"
					>
						{cat.full_path}
					</button>
				{/each}
			</div>
		{/if}
		<button
			onclick={() => (showCategoryPicker = false)}
			class="mt-3 w-full rounded-md border border-border bg-card py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
		>
			취소
		</button>
	</div>
{/if}
