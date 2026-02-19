<svelte:head><title>검토 — 이미지 분류기</title></svelte:head>

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

	let files: FileReview[] = $state([]);
	let selectedFiles: Set<number> = $state(new Set());
	let loading = $state(false);
	let sortBy = $state('confidence');
	let sortDir = $state('asc');

	onMount(() => {
		loadFiles();
	});

	async function loadFiles() {
		loading = true;
		try {
			const params = new URLSearchParams({
				status: 'ai_classified',
				order_by: sortBy === 'date' ? 'extracted_date' : 'ai_confidence',
				order_dir: sortDir,
				limit: '100'
			});
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

	function getThumbnailUrl(fileId: number): string {
		return `/api/ic/files/${fileId}/thumbnail`;
	}

	function getConfidenceColor(conf: number | null): string {
		if (!conf) return 'text-muted-foreground';
		if (conf >= 0.9) return 'text-green-600';
		if (conf >= 0.7) return 'text-yellow-600';
		return 'text-destructive';
	}
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<CheckCircle2 class="size-5 text-primary" />
				<h1 class="text-2xl font-bold tracking-tight">검토 및 승인</h1>
			</div>
			<p class="mt-1 text-sm text-muted-foreground">AI가 분류한 결과를 검토하고 승인합니다.</p>
		</div>
		<div class="flex items-center gap-2">
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
						class="relative aspect-square cursor-pointer overflow-hidden rounded-lg border transition-all {isSelected ? 'ring-2 ring-primary' : 'hover:ring-1 hover:ring-primary/50'}"
						onclick={() => toggleFile(file.id)}
					>
						<img
							src={getThumbnailUrl(file.id)}
							alt={file.file_path}
							loading="lazy"
							decoding="async"
							class="h-full w-full object-cover"
						/>

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
						<div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-2">
							<p class="truncate text-[10px] text-white">
								{file.file_path.split(/[/\\]/).pop() ?? `file_${file.id}`}
							</p>
							<p class="text-[9px] text-white/70">
								카테고리: {file.final_category_id ?? '—'}
							</p>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
