<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { CheckCircle2, RefreshCw } from 'lucide-svelte';

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
	let categories: Category[] = $state([]);
	let categoryMap = $state(new Map<number, string>());
	let flatCategories = $state<Category[]>([]);
	let selectedFiles: Set<number> = $state(new Set());
	let loading = $state(false);
	let sortBy = $state('confidence');
	let sortDir = $state('asc');
	let filterCategoryId = $state<number | ''>('');

	onMount(async () => {
		await loadCategories();
		await loadFiles();
	});

	async function loadCategories() {
		try {
			const res = await fetchWithTimeout('/api/ic/categories?include_tree=true');
			if (res.ok) {
				const data = await res.json();
				categories = data.categories || [];
				// 평탄화 + ID→full_path 맵 생성
				const flat: Category[] = [];
				const map = new Map<number, string>();
				function flatten(cats: Category[]) {
					for (const cat of cats) {
						flat.push(cat);
						map.set(cat.id, cat.full_path);
						if (cat.children?.length) flatten(cat.children);
					}
				}
				flatten(categories);
				flatCategories = flat;
				categoryMap = map;
			}
		} catch (err) {
			console.error('카테고리 로드 실패:', err);
		}
	}

	async function loadFiles() {
		loading = true;
		try {
			const params = new URLSearchParams({
				status: 'ai_classified',
				order_by: sortBy === 'date' ? 'extracted_date' : 'ai_confidence',
				order_dir: sortDir,
				limit: '100'
			});
			if (filterCategoryId !== '') {
				params.append('category_id', String(filterCategoryId));
			}
			const response = await fetchWithTimeout(`/api/ic/files?${params}`);
			if (response.ok) {
				const data = await response.json();
				files = data.files || [];
			}
		} catch (err) {
			console.error('파일 로드 실패:', err);
		} finally {
			loading = false;
		}
	}

	function toggleFile(id: number) {
		if (selectedFiles.has(id)) {
			selectedFiles.delete(id);
		} else {
			selectedFiles.add(id);
		}
		selectedFiles = selectedFiles;
	}

	async function approveSelected() {
		const ids = Array.from(selectedFiles);
		if (ids.length === 0) return;

		try {
			const res = await fetchWithTimeout('/api/ic/files/approve', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: ids })
			});
			if (!res.ok) throw new Error('승인 실패');
			alert(`${ids.length}개 파일이 승인되었습니다.`);
			selectedFiles.clear();
			selectedFiles = selectedFiles;
			await loadFiles();
		} catch (err) {
			alert('승인 실패');
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

	function getConfidenceColor(conf: number | null): string {
		if (!conf) return 'text-muted-foreground';
		if (conf >= 0.9) return 'text-green-600';
		if (conf >= 0.7) return 'text-yellow-600';
		return 'text-destructive';
	}

	function getCategoryName(catId: number | null): string {
		if (!catId) return '—';
		return categoryMap.get(catId) ?? `#${catId}`;
	}
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<CheckCircle2 class="size-5 text-primary" />
				<h2 class="text-xl font-bold tracking-tight">검토 및 승인</h2>
			</div>
			<p class="mt-1 text-sm text-muted-foreground">AI가 분류한 결과를 검토하고 승인합니다.</p>
		</div>
		<div class="flex items-center gap-2">
			<!-- 카테고리 필터 -->
			<select
				bind:value={filterCategoryId}
				onchange={loadFiles}
				class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
			>
				<option value="">전체 카테고리</option>
				{#each flatCategories as cat}
					<option value={cat.id}>{cat.full_path}</option>
				{/each}
			</select>
			<select
				bind:value={sortBy}
				onchange={loadFiles}
				class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
			>
				<option value="confidence">신뢰도순</option>
				<option value="date">날짜순</option>
			</select>
			<select
				bind:value={sortDir}
				onchange={loadFiles}
				class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
			>
				<option value="asc">오름차순</option>
				<option value="desc">내림차순</option>
			</select>
			<button
				onclick={approveSelected}
				disabled={selectedFiles.size === 0}
				class="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
			>
				<CheckCircle2 class="size-4" />
				승인 ({selectedFiles.size})
			</button>
		</div>
	</div>

	<!-- 콘텐츠 -->
	<div class="rounded-xl border bg-card">
		{#if loading}
			<div class="flex items-center justify-center py-16 text-sm text-muted-foreground">
				<div class="flex items-center gap-2">
					<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
					로딩 중...
				</div>
			</div>
		{:else if files.length === 0}
			<div class="py-16 text-center text-sm text-muted-foreground">
				검토할 파일이 없습니다.
			</div>
		{:else}
			<div class="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
				{#each files as file}
					{@const isSelected = selectedFiles.has(file.id)}
					<div
						class="relative cursor-pointer overflow-hidden rounded-lg border transition-all {isSelected ? 'ring-2 ring-primary' : 'hover:ring-1 hover:ring-primary/50'}"
						onclick={() => toggleFile(file.id)}
					>
						<div class="aspect-square">
							<img
								src={getThumbnailUrl(file.id)}
								alt={file.file_path}
								loading="lazy"
								decoding="async"
								class="h-full w-full object-cover"
							/>
						</div>

						<!-- 체크박스 -->
						<div class="absolute left-2 top-2 {isSelected ? 'opacity-100' : 'opacity-0 hover:opacity-100'} transition-opacity">
							<input
								type="checkbox"
								checked={isSelected}
								onchange={() => toggleFile(file.id)}
								class="size-4 accent-primary"
							/>
						</div>

						<!-- 신뢰도 -->
						{#if file.ai_confidence}
							<div class="absolute right-2 top-2">
								<span class="rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-bold {getConfidenceColor(file.ai_confidence)}">
									{Math.round(file.ai_confidence * 100)}%
								</span>
							</div>
						{/if}

						<!-- 하단 정보 -->
						<div class="inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2">
							<p class="truncate text-[10px] text-white" title={file.file_path}>
								{file.file_path.split(/[/\\]/).pop() ?? `file_${file.id}`}
							</p>
							<p class="truncate text-[9px] text-white/70" title={getCategoryName(file.final_category_id)}>
								{getCategoryName(file.final_category_id)}
							</p>
							<!-- 카테고리 변경 드롭다운 -->
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
		{/if}
	</div>
</div>
