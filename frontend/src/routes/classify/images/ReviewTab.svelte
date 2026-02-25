<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { createSelection } from '$lib/utils/selection.svelte';
	import { createOffsetPagination } from '$lib/utils/pagination.svelte';
	import { loadCategoryMap, getCategoryName, type Category } from '../lib/categoryUtils';
	import CategoryPickerModal from '../components/CategoryPicker.svelte';
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
	import { toast } from '$lib/stores/toast';

	interface FileReview {
		id: number;
		file_path: string;
		final_category_id: number | null;
		category_path: string | null;
		ai_confidence: number | null;
		status: string;
	}

	let files: FileReview[] = $state([]);
	let totalCount = $state(0);
	const selection = createSelection();
	let loading = $state(false);
	let loadingMore = $state(false);
	let sortBy = $state('confidence');
	let sortDir = $state('asc');
	let confidenceFilter = $state<'all' | 'low' | 'mid' | 'high'>('all');
	let filterCategoryId = $state<number | ''>('');

	const pager = createOffsetPagination(100);

	// 카테고리 목록 (이름 표시용)
	let categories = $state<Category[]>([]);
	let flatCategories = $state<Category[]>([]);
	let categoryMap = $state(new Map<number, string>());

	// 카테고리 변�?모달
	let showCategoryPicker = $state(false);

	onMount(() => {
		loadCategories();
		loadFiles(true);
	});

	async function loadCategories() {
		try {
			// 공통 유틸로 categoryMap 로드 (/api/ic/categories/tree)
			categoryMap = await loadCategoryMap();
			// CategoryPicker용 트리/플랫 목록은 별도 엔드포인트 유지
			const res = await fetchWithTimeout('/api/ic/categories?include_tree=true');
			if (res.ok) {
				const data = await res.json();
				categories = data.categories ?? [];
				// 인라인 플랫 변환 (CategoryPicker 전용)
				const flat: Category[] = [];
				function walkFlat(cats: Category[]) {
					for (const cat of cats) {
						flat.push(cat);
						if (cat.children?.length) walkFlat(cat.children);
					}
				}
				walkFlat(categories);
				flatCategories = flat;
			}
		} catch {
			/* ignore */
		}
	}

	async function loadFiles(reset = false) {
		if (reset) {
			loading = true;
			pager.reset();
			files = [];
		} else {
			loadingMore = true;
		}

		try {
			const params = new URLSearchParams({
				status: 'ai_classified',
				order_by: sortBy === 'date' ? 'extracted_date' : 'ai_confidence',
				order_dir: sortDir,
				...pager.toParams()
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
				pager.advance(newFiles.length, data.total ?? files.length);
				totalCount = pager.total;
			}
		} catch (err) {
			console.error('파일 로드 실패:', err);
		} finally {
			loading = false;
			loadingMore = false;
		}
	}

	// ?�뢰???�터�?(?�라?�언??
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

	let allSelected = $derived(
		filteredFiles.length > 0 && selection.isAllSelected(filteredFiles.map((f) => f.id))
	);

	async function approveSelected() {
		if (selection.count === 0) return;
		try {
			const res = await fetchWithTimeout('/api/ic/files/approve', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: selection.toArray() })
			});
			if (!res.ok) throw new Error('?�인 ?�패');
			selection.clear();
			await loadFiles(true);
		} catch (err) {
			toast.error('승인 실패');
		}
	}

	async function deleteSelected() {
		if (selection.count === 0) return;
		if (!confirm(`?�택??${selection.count}�??��?지�???��?�시겠습?�까?`)) return;
		try {
			const res = await fetchWithTimeout('/api/ic/files/bulk-delete', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: selection.toArray() })
			});
			if (!res.ok) throw new Error('??�� ?�패');
			selection.clear();
			await loadFiles(true);
		} catch (err: unknown) {
			toast.error(`삭제 실패: ${(err as Error).message}`);
		}
	}

	async function assignCategory(categoryId: number) {
		if (selection.count === 0) return;
		try {
			const res = await fetchWithTimeout('/api/ic/files/bulk-classify', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: selection.toArray(), category_id: categoryId })
			});
			if (!res.ok) throw new Error('카테고리 지???�패');
			selection.clear();
			showCategoryPicker = false;
			await loadFiles(true);
		} catch (err: unknown) {
			toast.error(`카테고리 지정 실패: ${(err as Error).message}`);
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
			if (!res.ok) throw new Error('카테고리 변�??�패');
			file.final_category_id = newCategoryId;
			files = [...files];
		} catch (err) {
			console.error('카테고리 변�??�패:', err);
		}
	}

	function getThumbnailUrl(fileId: number): string {
		return `/api/ic/files/${fileId}/thumbnail`;
	}

	function getCategoryDisplay(file: FileReview): string {
		if (file.category_path) return file.category_path;
		if (file.final_category_id) return getCategoryName(categoryMap, file.final_category_id);
		return '미분류';
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

	// ?�렬/?�터 변�????�로??
	function handleFilterChange() {
		loadFiles(true);
	}
</script>

<div class="space-y-4">
	<!-- ?�더 -->
	<div class="flex flex-wrap items-center justify-between gap-3">
		<div>
			<div class="flex items-center gap-2">
				<CheckCircle2 class="size-5 text-primary" />
				<h2 class="text-xl font-bold tracking-tight">검??�??�인</h2>
				{#if totalCount > 0}
					<span class="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
						{totalCount.toLocaleString()}�?
					</span>
				{/if}
			</div>
			<p class="mt-1 text-sm text-muted-foreground">AI가 분류??결과�?검?�하�??�인?�니??</p>
		</div>
		<button
			onclick={() => loadFiles(true)}
			disabled={loading}
			class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50 transition-colors"
		>
			<RefreshCw class="size-3.5 {loading ? 'animate-spin' : ''}" />
			?�로고침
		</button>
	</div>

	<!-- ?�터 �?-->
	<div class="rounded-xl border border-border bg-card p-3">
		<div class="flex flex-wrap items-center gap-3">
			<!-- ?�뢰???�터 -->
			<div class="flex items-center gap-0.5 rounded-md border border-border bg-muted p-0.5">
				{#each [
					{ key: 'all', label: '?�체' },
					{ key: 'low', label: '??�� <70%', color: 'text-red-600' },
					{ key: 'mid', label: '중간 70-90%', color: 'text-yellow-600' },
					{ key: 'high', label: '?�음 ??0%', color: 'text-green-600' }
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

			<!-- 카테고리 ?�터 -->
			<select
				bind:value={filterCategoryId}
				onchange={() => handleFilterChange()}
				class="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
			>
				<option value="">?�체 카테고리</option>
				{#each flatCategories as cat}
					<option value={cat.id}>{cat.full_path}</option>
				{/each}
			</select>

			<!-- ?�렬 -->
			<select
				bind:value={sortBy}
				onchange={handleFilterChange}
				class="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
			>
				<option value="confidence">?�뢰?�순</option>
				<option value="date">?�짜??/option>
			</select>
			<select
				bind:value={sortDir}
				onchange={handleFilterChange}
				class="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
			>
				<option value="asc">?�름차순</option>
				<option value="desc">?�림차순</option>
			</select>

			<!-- ?�체 ?�택 -->
			<button
				onclick={() => selection.selectAll(filteredFiles.map((f) => f.id))}
				class="ml-auto flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-accent transition-colors"
			>
				{#if allSelected}
					<SquareCheck class="size-3.5 text-primary" />
					?�체 ?�제
				{:else}
					<Square class="size-3.5" />
					?�체 ?�택 ({filteredFiles.length})
				{/if}
			</button>
		</div>
	</div>

	<!-- 벌크 ?�션 �?-->
	{#if selection.count > 0}
		<div class="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
			<span class="text-xs font-medium text-primary">{selection.count}�??�택??/span>
			<div class="mx-1 h-4 w-px bg-border"></div>
			<button
				onclick={approveSelected}
				class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
			>
				<Check class="size-3" />
				?�인
			</button>
			<button
				onclick={() => {
					loadCategories();
					showCategoryPicker = true;
				}}
				class="flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-accent"
			>
				<Tag class="size-3" />
				카테고리 변�?
			</button>
			<button
				onclick={deleteSelected}
				class="flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/10"
			>
				<Trash2 class="size-3" />
				??��
			</button>
			<button
				onclick={() => selection.clear()}
				class="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
			>
				<X class="size-3" />
				?�택 ?�제
			</button>
		</div>
	{/if}

	<!-- 콘텐�?-->
	<div class="rounded-xl border bg-card">
		{#if loading}
			<div class="flex items-center justify-center py-16 text-sm text-muted-foreground gap-2">
				<Loader2 class="size-4 animate-spin" />
				로딩 �?..
			</div>
		{:else if filteredFiles.length === 0}
			<div class="py-16 text-center text-sm text-muted-foreground">
				{confidenceFilter !== 'all' ? '?�당 ?�뢰??범위???�일???�습?�다.' : '검?�할 ?�일???�습?�다.'}
			</div>
		{:else}
			<div
				class="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
			>
				{#each filteredFiles as file (file.id)}
					{@const isSelected = selection.has(file.id)}
					<div
						role="button"
						tabindex="0"
						class="group relative aspect-square cursor-pointer overflow-hidden rounded-lg border bg-muted transition-all {isSelected
							? 'ring-2 ring-primary'
							: 'hover:ring-1 hover:ring-primary/50'}"
						onclick={() => selection.toggle(file.id)}
						onkeydown={(e) => e.key === 'Enter' && selection.toggle(file.id)}
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
								selection.toggle(file.id);
							}}
							aria-label="Select image"
						>
							{#if isSelected}
								<Check class="size-3" />
							{/if}
						</button>

						<!-- ?�뢰??-->
						{#if file.ai_confidence}
							<div class="absolute right-1.5 top-1.5">
								<span
									class="rounded px-1.5 py-0.5 text-[10px] font-bold {getConfidenceBgColor(file.ai_confidence)} {getConfidenceColor(file.ai_confidence)}"
								>
									{Math.round(file.ai_confidence * 100)}%
								</span>
							</div>
						{/if}

						<!-- ?�단 ?�보 -->
						<div
							class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent p-1.5 pt-5"
						>
							<p class="truncate text-[10px] font-medium text-white">
								{file.file_path.split(/[/\\]/).pop() ?? `file_${file.id}`}
							</p>
							<p class="truncate text-[9px] text-white/70">
								{getCategoryDisplay(file)}
							</p>
							<!-- 개별 카테고리 변�??�롭?�운 -->
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
									<option value="">??변�???/option>
									{#each flatCategories as cat}
										<option value={cat.id}>{cat.full_path}</option>
									{/each}
								</select>
							</div>
						</div>
					</div>
				{/each}
			</div>

			<!-- ??보기 -->
			{#if pager.hasMore}
				<div class="flex justify-center border-t py-3">
					<button
						onclick={() => loadFiles(false)}
						disabled={loadingMore}
						class="inline-flex items-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-50 transition-colors"
					>
						{#if loadingMore}
							<Loader2 class="size-4 animate-spin" />
							로딩 �?..
						{:else}
							??보기 ({files.length}/{totalCount})
						{/if}
					</button>
				</div>
			{/if}
		{/if}
	</div>
</div>

<!-- 카테고리 ?�택 모달 -->
{#if showCategoryPicker}
	<CategoryPickerModal
		{categories}
		{flatCategories}
		onSelect={assignCategory}
		onClose={() => (showCategoryPicker = false)}
	/>
{/if}
