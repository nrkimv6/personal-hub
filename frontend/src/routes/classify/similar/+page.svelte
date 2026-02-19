<svelte:head><title>유사 이미지 — Image Classifier</title></svelte:head>

<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { Search, RefreshCw, Tag, ArrowRight, ImageIcon } from 'lucide-svelte';

	interface SimilarFile {
		file_id: number;
		file_path: string;
		similarity: number;
		current_category: string | null;
		suggested_category: string;
	}

	interface SimilarGroup {
		category: string;
		category_name: string;
		file_count: number;
		similar_count: number;
		similar_files: SimilarFile[];
	}

	let groups: SimilarGroup[] = $state([]);
	let selectedFiles: Set<number> = $state(new Set());
	let threshold = $state(0.85);
	let loading = $state(false);
	let error = $state('');
	let referenceImageId = $state<number | null>(null);
	let matchCount = $state(50);

	onMount(() => {
		loadSimilarSuggestions();
	});

	async function loadSimilarSuggestions() {
		loading = true;
		error = '';

		try {
			const response = await fetchWithTimeout(`/api/ic/similar/bulk-suggest?threshold=${threshold}`);

			if (!response.ok) {
				throw new Error('Failed to load similar suggestions');
			}

			const data = await response.json();
			groups = data.groups || [];
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

	function toggleGroup(group: SimilarGroup) {
		const allSelected = group.similar_files.every((f) => selectedFiles.has(f.file_id));

		if (allSelected) {
			group.similar_files.forEach((f) => selectedFiles.delete(f.file_id));
		} else {
			group.similar_files.forEach((f) => selectedFiles.add(f.file_id));
		}
		selectedFiles = selectedFiles;
	}

	async function applyClassification(category: string) {
		const fileIds = Array.from(selectedFiles);

		if (fileIds.length === 0) {
			alert('파일을 선택해주세요.');
			return;
		}

		if (!confirm(`선택한 ${fileIds.length}개 파일을 "${category}"로 분류하시겠습니까?`)) {
			return;
		}

		loading = true;
		error = '';

		try {
			const response = await fetchWithTimeout('/api/ic/similar/apply', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: fileIds, category_id: category })
			});

			if (!response.ok) {
				throw new Error('Failed to apply classification');
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

	let totalResults = $derived(groups.reduce((sum, g) => sum + g.similar_count, 0));
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<Search class="size-5 text-primary" />
				<h1 class="text-2xl font-bold tracking-tight">유사 이미지</h1>
			</div>
			<p class="mt-1 text-sm text-muted-foreground">
				이미 분류된 이미지와 유사한 미분류 이미지를 찾아 자동으로 분류 제안합니다.
			</p>
		</div>
	</div>

	<!-- 상단 3열 카드 -->
	<div class="grid gap-4 lg:grid-cols-3">
		<!-- Reference Image 카드 -->
		<div class="rounded-xl border bg-card p-4">
			<h3 class="mb-3 text-sm font-semibold">기준 이미지</h3>
			<div class="relative aspect-video overflow-hidden rounded-lg bg-muted">
				{#if referenceImageId !== null}
					<img
						src={getThumbnailUrl(referenceImageId)}
						alt="Reference"
						class="h-full w-full object-cover"
					/>
				{:else}
					<div class="flex h-full flex-col items-center justify-center gap-2">
						<ImageIcon class="size-8 text-muted-foreground/50" />
						<span class="text-xs text-muted-foreground">선택 없음</span>
					</div>
				{/if}
			</div>
			{#if referenceImageId !== null}
				<div class="mt-2 space-y-0.5">
					<p class="text-xs font-medium">이미지 #{referenceImageId}</p>
					<p class="text-[10px] text-muted-foreground">ID: {referenceImageId}</p>
				</div>
			{/if}
			<button
				onclick={() => (referenceImageId = null)}
				class="mt-3 w-full rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
			>
				기준 이미지 변경
			</button>
		</div>

		<!-- Search Controls 카드 -->
		<div class="rounded-xl border bg-card p-4 lg:col-span-2">
			<h3 class="mb-4 text-sm font-semibold">검색 설정</h3>
			<div class="space-y-4">
				<div>
					<div class="mb-1.5 flex items-center justify-between">
						<label class="text-xs font-medium" for="threshold-range">유사도 기준</label>
						<span class="text-sm font-bold {getThresholdColorClass(threshold)}">
							{(threshold * 100).toFixed(0)}%
						</span>
					</div>
					<input
						id="threshold-range"
						type="range"
						min="0.70"
						max="1.00"
						step="0.01"
						bind:value={threshold}
						class="w-full accent-primary"
					/>
					<div class="mt-1 flex justify-between text-[10px] text-muted-foreground">
						<span>70% (낮음)</span>
						<span>100% (정확)</span>
					</div>
				</div>

				<div class="flex items-end gap-3">
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
					<p class="text-xs text-muted-foreground">
						{groups.length}개 그룹에서 {totalResults}개 유사 이미지 발견
					</p>
				{/if}
			</div>
		</div>
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
							<span class="font-semibold text-sm">{group.category_name}</span>
						</div>
						<div class="flex items-center gap-2 text-xs text-muted-foreground">
							<span>유사 {group.similar_count}개</span>
							<span>·</span>
							<span>분류 {group.file_count}개</span>
						</div>
						<div class="ml-auto flex items-center gap-2">
							<button
								onclick={() => toggleGroup(group)}
								class="rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
							>
								{group.similar_files.every((f) => selectedFiles.has(f.file_id))
									? '전체 해제'
									: '전체 선택'}
							</button>
							<button
								onclick={() => applyClassification(group.category)}
								disabled={!group.similar_files.some((f) => selectedFiles.has(f.file_id))}
								class="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
							>
								<Tag class="size-3" />
								{group.category_name}에 적용
							</button>
						</div>
					</div>

					<!-- 이미지 그리드 -->
					<div class="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
						{#each group.similar_files as file}
							<div
								class="relative aspect-square cursor-pointer overflow-hidden rounded-lg border transition-all {selectedFiles.has(file.file_id) ? 'ring-2 ring-primary' : 'hover:ring-1 hover:ring-primary/50'}"
								onclick={() => toggleFile(file.file_id)}
							>
								<img
									src={getThumbnailUrl(file.file_id)}
									alt={file.file_path}
									loading="lazy"
									decoding="async"
									class="h-full w-full object-cover"
								/>

								<!-- 체크박스 -->
								<div class="absolute left-2 top-2 opacity-0 transition-opacity {selectedFiles.has(file.file_id) ? 'opacity-100' : 'group-hover:opacity-100'}">
									<input
										type="checkbox"
										checked={selectedFiles.has(file.file_id)}
										onchange={() => toggleFile(file.file_id)}
										class="size-4 accent-primary"
									/>
								</div>

								<!-- 점수 뱃지 -->
								<div class="absolute right-2 top-2">
									<span class="rounded px-1.5 py-0.5 text-[10px] font-bold {getScoreBadgeClass(file.similarity)}">
										{(file.similarity * 100).toFixed(0)}%
									</span>
								</div>

								<!-- 하단 정보 -->
								<div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-2">
									<p class="truncate text-[10px] text-white">
										{file.file_path.split('/').pop() ?? file.file_path}
									</p>
									{#if file.current_category}
										<span class="rounded bg-white/20 px-1 py-0.5 text-[9px] text-white">
											{file.current_category}
										</span>
									{/if}
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
				onclick={() => applyClassification('')}
				class="flex items-center gap-1.5 rounded-full bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
			>
				<Tag class="size-3" />
				적용
			</button>
			<button
				onclick={() => { selectedFiles.clear(); selectedFiles = selectedFiles; }}
				class="rounded-full border px-4 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
			>
				전체 해제
			</button>
		</div>
	</div>
{/if}
