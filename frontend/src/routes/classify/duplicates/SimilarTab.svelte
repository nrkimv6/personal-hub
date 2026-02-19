<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { Search, RefreshCw, Tag, ArrowRight } from 'lucide-svelte';

	interface SimilarSuggestion {
		file_id: number;
		file_path: string;
		suggested_category_id: number;
		suggested_category_path: string;
		similarity: number;
		reference_file_id: number;
		reference_file_path: string;
	}

	interface SuggestionGroup {
		category_id: number;
		category_path: string;
		suggestions: SimilarSuggestion[];
	}

	let groups: SuggestionGroup[] = $state([]);
	let selectedFiles: Set<number> = $state(new Set());
	let threshold = $state(0.85);
	let loading = $state(false);
	let error = $state('');
	let matchCount = $state(50);
	let totalUnclassified = $state(0);

	onMount(() => {
		loadSimilarSuggestions();
	});

	async function loadSimilarSuggestions() {
		loading = true;
		error = '';

		try {
			const response = await fetchWithTimeout(
				`/api/ic/similar/bulk-suggest?threshold=${threshold}&max_results=${matchCount}`
			);

			if (!response.ok) {
				throw new Error('유사 이미지 로드 실패');
			}

			const data = await response.json();
			totalUnclassified = data.total_unclassified ?? 0;

			// suggestions를 category별로 그룹핑
			const suggestions: SimilarSuggestion[] = data.suggestions || [];
			const groupMap = new Map<number, SuggestionGroup>();

			for (const s of suggestions) {
				if (!groupMap.has(s.suggested_category_id)) {
					groupMap.set(s.suggested_category_id, {
						category_id: s.suggested_category_id,
						category_path: s.suggested_category_path || `카테고리 ${s.suggested_category_id}`,
						suggestions: []
					});
				}
				groupMap.get(s.suggested_category_id)!.suggestions.push(s);
			}

			groups = Array.from(groupMap.values());
		} catch (err: any) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	function toggleFile(fileId: number) {
		if (selectedFiles.has(fileId)) {
			selectedFiles.delete(fileId);
		} else {
			selectedFiles.add(fileId);
		}
		selectedFiles = selectedFiles;
	}

	function toggleGroup(group: SuggestionGroup) {
		const allSelected = group.suggestions.every((s) => selectedFiles.has(s.file_id));

		if (allSelected) {
			group.suggestions.forEach((s) => selectedFiles.delete(s.file_id));
		} else {
			group.suggestions.forEach((s) => selectedFiles.add(s.file_id));
		}
		selectedFiles = selectedFiles;
	}

	async function applyGroupClassification(group: SuggestionGroup) {
		const fileIds = group.suggestions
			.filter((s) => selectedFiles.has(s.file_id))
			.map((s) => s.file_id);

		if (fileIds.length === 0) {
			alert('파일을 선택해주세요.');
			return;
		}

		if (!confirm(`선택한 ${fileIds.length}개 파일을 "${group.category_path}"로 분류하시겠습니까?`)) {
			return;
		}

		loading = true;
		error = '';

		try {
			for (const fileId of fileIds) {
				const response = await fetchWithTimeout('/api/ic/similar/apply', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({
						file_id: fileId,
						suggested_category_id: group.category_id
					})
				});

				if (!response.ok) {
					throw new Error(`파일 ${fileId} 분류 실패`);
				}
			}

			alert(`${fileIds.length}개 파일이 분류되었습니다.`);
			selectedFiles.clear();
			selectedFiles = selectedFiles;
			await loadSimilarSuggestions();
		} catch (err: any) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	function getThumbnailUrl(fileId: number): string {
		return `/api/ic/files/${fileId}/thumbnail`;
	}

	function getScoreBadgeClass(similarity: number): string {
		if (similarity >= 0.9) return 'bg-green-500/90 text-white';
		if (similarity >= 0.8) return 'bg-primary/90 text-primary-foreground';
		return 'bg-amber-500/90 text-white';
	}

	function getThresholdColorClass(val: number): string {
		if (val >= 0.95) return 'text-green-600';
		if (val >= 0.85) return 'text-primary';
		return 'text-amber-500';
	}

	let totalResults = $derived(groups.reduce((sum, g) => sum + g.suggestions.length, 0));
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<Search class="size-5 text-primary" />
				<h2 class="text-xl font-bold tracking-tight">유사 이미지</h2>
			</div>
			<p class="mt-1 text-sm text-muted-foreground">
				이미 분류된 이미지와 유사한 미분류 이미지를 찾아 자동으로 분류 제안합니다.
			</p>
		</div>
	</div>

	<!-- 검색 설정 -->
	<div class="rounded-xl border bg-card p-4">
		<h3 class="mb-4 text-sm font-semibold">검색 설정</h3>
		<div class="flex flex-wrap items-end gap-4">
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium" for="threshold-range">
					유사도 기준 — <span class="font-bold {getThresholdColorClass(threshold)}">{(threshold * 100).toFixed(0)}%</span>
				</label>
				<input
					id="threshold-range"
					type="range"
					min="0.70"
					max="1.00"
					step="0.01"
					bind:value={threshold}
					class="w-48 accent-primary"
				/>
			</div>
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium" for="match-count">최대 결과 수</label>
				<input
					id="match-count"
					type="number"
					bind:value={matchCount}
					min="10"
					max="500"
					step="10"
					class="w-28 rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
				/>
			</div>
			<button
				onclick={loadSimilarSuggestions}
				disabled={loading}
				class="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
			>
				<RefreshCw class="size-3.5 {loading ? 'animate-spin' : ''}" />
				{loading ? '검색 중...' : '검색'}
			</button>
		</div>
		{#if !loading}
			<p class="mt-2 text-xs text-muted-foreground">
				미분류 {totalUnclassified}개 중 {totalResults}개 유사 이미지 발견 ({groups.length}개 그룹)
			</p>
		{/if}
	</div>

	<!-- 에러 -->
	{#if error}
		<div class="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
			{error}
		</div>
	{/if}

	<!-- 로딩 -->
	{#if loading}
		<div class="flex items-center justify-center py-16 text-sm text-muted-foreground">
			<div class="flex items-center gap-2">
				<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
				유사 이미지 검색 중...
			</div>
		</div>
	{:else if groups.length === 0}
		<div class="rounded-xl border bg-card py-16 text-center text-sm text-muted-foreground">
			유사 이미지를 찾을 수 없습니다. 임계값을 낮춰보세요.
		</div>
	{:else}
		<!-- 그룹별 결과 -->
		<div class="space-y-6">
			{#each groups as group}
				<div class="rounded-xl border bg-card">
					<!-- 그룹 헤더 -->
					<div class="flex flex-wrap items-center gap-3 border-b px-4 py-3">
						<div class="flex items-center gap-1.5">
							<ArrowRight class="size-4 text-primary" />
							<span class="font-semibold text-sm">{group.category_path}</span>
						</div>
						<div class="flex items-center gap-2 text-xs text-muted-foreground">
							<span>유사 {group.suggestions.length}개</span>
						</div>
						<div class="ml-auto flex items-center gap-2">
							<button
								onclick={() => toggleGroup(group)}
								class="rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
							>
								{group.suggestions.every((s) => selectedFiles.has(s.file_id))
									? '전체 해제'
									: '전체 선택'}
							</button>
							<button
								onclick={() => applyGroupClassification(group)}
								disabled={!group.suggestions.some((s) => selectedFiles.has(s.file_id))}
								class="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
							>
								<Tag class="size-3" />
								{group.category_path}에 적용
							</button>
						</div>
					</div>

					<!-- 이미지 그리드 -->
					<div class="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
						{#each group.suggestions as item}
							<div
								class="relative aspect-square cursor-pointer overflow-hidden rounded-lg border transition-all {selectedFiles.has(item.file_id) ? 'ring-2 ring-primary' : 'hover:ring-1 hover:ring-primary/50'}"
								onclick={() => toggleFile(item.file_id)}
							>
								<img
									src={getThumbnailUrl(item.file_id)}
									alt={item.file_path}
									loading="lazy"
									decoding="async"
									class="h-full w-full object-cover"
								/>

								<!-- 체크박스 -->
								<div class="absolute left-2 top-2 {selectedFiles.has(item.file_id) ? 'opacity-100' : 'opacity-0 hover:opacity-100'} transition-opacity">
									<input
										type="checkbox"
										checked={selectedFiles.has(item.file_id)}
										onchange={() => toggleFile(item.file_id)}
										class="size-4 accent-primary"
									/>
								</div>

								<!-- 점수 뱃지 -->
								<div class="absolute right-2 top-2">
									<span class="rounded px-1.5 py-0.5 text-[10px] font-bold {getScoreBadgeClass(item.similarity)}">
										{(item.similarity * 100).toFixed(0)}%
									</span>
								</div>

								<!-- 하단 정보 -->
								<div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-2">
									<p class="truncate text-[10px] text-white">
										{item.file_path.split(/[/\\]/).pop() ?? item.file_path}
									</p>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- Sticky 액션 바 -->
{#if selectedFiles.size > 0}
	<div class="fixed bottom-10 left-1/2 z-50 -translate-x-1/2">
		<div class="flex items-center gap-4 rounded-full border bg-card px-5 py-2.5 shadow-xl">
			<span class="text-sm font-semibold">{selectedFiles.size}개 선택됨</span>
			<button
				onclick={() => { selectedFiles.clear(); selectedFiles = selectedFiles; }}
				class="rounded-full border px-4 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
			>
				전체 해제
			</button>
		</div>
	</div>
{/if}
