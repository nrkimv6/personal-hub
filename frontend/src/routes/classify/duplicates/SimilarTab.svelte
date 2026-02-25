<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { createSelection } from '$lib/utils/selection.svelte';
	import { getErrorMessage } from '$lib/utils/error';
	import { loadCategoryMap as loadCategoryMapUtil } from '../lib/categoryUtils';
	import { Search, RefreshCw, Tag, ArrowRight, Cpu, AlertTriangle, Eye, FolderOpen, Clipboard } from 'lucide-svelte';

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
	const selection = createSelection();
	let threshold = $state(0.85);
	let loading = $state(false);
	let error = $state('');
	let matchCount = $state(50);
	let totalUnclassified = $state(0);
	let buildingIndex = $state(false);
	let toastMessage = $state<string | null>(null);
	let toastTimer: ReturnType<typeof setTimeout> | null = null;

	// 카테고리 맵 (폴백용)
	let categoryMap = $state(new Map<number, string>());

	async function loadCategoryMap() {
		try {
			categoryMap = await loadCategoryMapUtil();
		} catch { /* ignore */ }
	}

	function showToast(msg: string) {
		toastMessage = msg;
		if (toastTimer) clearTimeout(toastTimer);
		toastTimer = setTimeout(() => { toastMessage = null; }, 3000);
	}

	// CLIP 임베딩 상태
	let clipReady = $state(false);
	let clipChecking = $state(true);
	let clipRunning = $state(false);
	let clipProcessed = $state(0);
	let clipTotal = $state(0);
	let clipPollTimer: ReturnType<typeof setInterval> | null = null;
	let clipPollFailCount = 0;

	async function checkClipStatus() {
		try {
			const res = await fetchWithTimeout('/api/ic/scan/clip/status');
			if (!res.ok) return;
			const data = await res.json();
			clipRunning = data.is_running;
			clipProcessed = data.processed;
			clipTotal = data.total;
			clipPollFailCount = 0;

			// CLIP이 실행 완료된 적이 있는지 pipeline에서 확인
			const pipeRes = await fetchWithTimeout('/api/ic/stats/pipeline');
			if (pipeRes.ok) {
				const pipeline = await pipeRes.json();
				const clipStage = pipeline.clip;
				// last_run이 있거나 실행 중이면 CLIP이 준비된 것
				if (clipStage?.last_run || clipStage?.is_running) {
					clipReady = true;
				} else {
					// DB에서 clip_embedding 존재 여부 직접 확인
					const statsRes = await fetchWithTimeout('/api/ic/stats');
					if (statsRes.ok) {
						const stats = await statsRes.json();
						// clip_embeddings 카운트가 있으면 준비됨
						clipReady = (stats.clip_embeddings ?? 0) > 0;
					}
				}
			}
		} catch {
			clipPollFailCount += 1;
			if (clipPollFailCount >= 3 && clipPollTimer) {
				clearInterval(clipPollTimer);
				clipPollTimer = setInterval(checkClipStatus, 15000);
			}
		} finally {
			clipChecking = false;
		}
	}

	async function startClipEmbedding() {
		try {
			const res = await fetchWithTimeout('/api/ic/scan/clip', { method: 'POST' });
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.detail || `HTTP ${res.status}`);
			}
			clipRunning = true;
			startClipPolling();
		} catch (err: any) {
			alert(`CLIP 임베딩 계산 시작 실패: ${getErrorMessage(err)}`);
		}
	}

	function startClipPolling() {
		if (clipPollTimer) return;
		clipPollTimer = setInterval(async () => {
			try {
				const res = await fetchWithTimeout('/api/ic/scan/clip/status');
				if (!res.ok) return;
				const data = await res.json();
				clipRunning = data.is_running;
				clipProcessed = data.processed;
				clipTotal = data.total;

				if (!data.is_running) {
					stopClipPolling();
					clipReady = true;
					if (data.error) {
						alert(`CLIP 임베딩 오류: ${data.error}`);
					}
				}
			} catch {
				// 무시
			}
		}, 3000);
	}

	function stopClipPolling() {
		if (clipPollTimer) {
			clearInterval(clipPollTimer);
			clipPollTimer = null;
		}
	}

	async function buildFaissIndex() {
		buildingIndex = true;
		try {
			const res = await fetchWithTimeout('/api/ic/similar/build-index', { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			alert('FAISS 인덱스 빌드 완료!');
		} catch (err: any) {
			alert(`인덱스 빌드 실패: ${getErrorMessage(err)}`);
		} finally {
			buildingIndex = false;
		}
	}

	onMount(async () => {
		void loadCategoryMap();
		await checkClipStatus();
		if (clipRunning) {
			startClipPolling();
		}
		if (clipReady) {
			loadSimilarSuggestions();
		}
	});

	onDestroy(() => {
		stopClipPolling();
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
						category_path: s.suggested_category_path || (categoryMap.get(s.suggested_category_id) ?? '(카테고리 정보 없음)'),
						suggestions: []
					});
				}
				groupMap.get(s.suggested_category_id)!.suggestions.push(s);
			}

			groups = Array.from(groupMap.values());
		} catch (err: any) {
			error = getErrorMessage(err);
		} finally {
			loading = false;
		}
	}

	function toggleGroup(group: SuggestionGroup) {
		selection.selectAll(group.suggestions.map((s) => s.file_id));
	}

	async function applyGroupClassification(group: SuggestionGroup) {
		const fileIds = group.suggestions
			.filter((s) => selection.has(s.file_id))
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

			showToast(`${fileIds.length}개 파일이 "${group.category_path}"로 분류되었습니다.`);
			selection.clear();
			await loadSimilarSuggestions();
		} catch (err: any) {
			error = getErrorMessage(err);
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

	async function openLocalViewer(fileId: number) {
		try {
			const res = await fetchWithTimeout('/api/ic/files/open-local', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_id: fileId })
			});
			if (!res.ok) {
				const err = await res.json();
				alert(err.detail || '뷰어 열기 실패');
			}
		} catch (err: any) {
			alert(`뷰어 열기 실패: ${getErrorMessage(err)}`);
		}
	}

	async function openInExplorer(fileId: number) {
		try {
			const res = await fetchWithTimeout('/api/ic/files/open-folder', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_id: fileId })
			});
			if (!res.ok) {
				const err = await res.json();
				alert(err.detail || '탐색기 열기 실패');
			}
		} catch (err: any) {
			alert(`탐색기 열기 실패: ${getErrorMessage(err)}`);
		}
	}

	async function copyToClipboard(text: string) {
		try {
			await navigator.clipboard.writeText(text);
		} catch {
			alert('클립보드 복사 실패');
		}
	}

	function getFileName(path: string): string {
		return path.split(/[/\\]/).pop() ?? path;
	}

	function getFolderPath(path: string): string {
		const idx = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
		return idx >= 0 ? path.substring(0, idx) : path;
	}
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
		<div class="flex items-center gap-2">
			<button
				onclick={startClipEmbedding}
				disabled={clipRunning || clipChecking}
				class="flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50 transition-colors"
			>
				<Cpu class="size-3.5 {clipRunning ? 'animate-pulse' : ''}" />
				{clipRunning ? `CLIP ${clipTotal > 0 ? Math.round(clipProcessed / clipTotal * 100) : 0}%` : 'CLIP 계산'}
			</button>
			<button
				onclick={buildFaissIndex}
				disabled={buildingIndex || !clipReady}
				class="flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50 transition-colors"
			>
				<RefreshCw class="size-3.5 {buildingIndex ? 'animate-spin' : ''}" />
				{buildingIndex ? '빌드 중...' : '인덱스 빌드'}
			</button>
		</div>
	</div>

	<!-- CLIP 임베딩 미계산 배너 -->
	{#if clipChecking}
		<div class="flex items-center gap-2 rounded-lg border bg-muted/50 px-4 py-3 text-sm text-muted-foreground">
			<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
			CLIP 임베딩 상태 확인 중...
		</div>
	{:else if clipRunning}
		<div class="rounded-lg border border-primary/30 bg-primary/5 px-4 py-3">
			<div class="flex items-center gap-2 text-sm font-medium text-primary">
				<Cpu class="size-4 animate-pulse" />
				CLIP 임베딩 계산 중... ({clipProcessed}/{clipTotal})
			</div>
			{#if clipTotal > 0}
				<div class="mt-2 h-2 w-full rounded-full bg-muted">
					<div
						class="h-2 rounded-full bg-primary transition-all"
						style="width: {Math.round(clipProcessed / clipTotal * 100)}%"
					></div>
				</div>
			{/if}
		</div>
	{:else if !clipReady}
		<div class="rounded-lg border border-amber-500/30 bg-amber-50 px-4 py-3 dark:bg-amber-950/20">
			<div class="flex items-center gap-2 text-sm font-medium text-amber-700 dark:text-amber-400">
				<AlertTriangle class="size-4" />
				CLIP 임베딩이 필요합니다
			</div>
			<p class="mt-1 text-xs text-amber-600 dark:text-amber-500">
				유사 이미지 검색을 위해 CLIP 임베딩을 먼저 계산해야 합니다. 상단의 "CLIP 계산" 버튼을 클릭하세요.
			</p>
		</div>
	{/if}

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
				disabled={loading || !clipReady}
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
								{group.suggestions.every((s) => selection.has(s.file_id))
									? '전체 해제'
									: '전체 선택'}
							</button>
							<button
								onclick={() => applyGroupClassification(group)}
								disabled={!group.suggestions.some((s) => selection.has(s.file_id))}
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
								class="cursor-pointer overflow-hidden rounded-lg border transition-all {selection.has(item.file_id) ? 'ring-2 ring-primary' : 'hover:ring-1 hover:ring-primary/50'}"
								onclick={() => selection.toggle(item.file_id)}
							>
								<div class="relative aspect-square">
									<img
										src={getThumbnailUrl(item.file_id)}
										alt={item.file_path}
										loading="lazy"
										decoding="async"
										class="h-full w-full object-cover"
									/>

									<!-- 체크박스 -->
									<div class="absolute left-2 top-2 {selection.has(item.file_id) ? 'opacity-100' : 'opacity-0 hover:opacity-100'} transition-opacity">
										<input
											type="checkbox"
											checked={selection.has(item.file_id)}
											onchange={() => selection.toggle(item.file_id)}
											class="size-4 accent-primary"
										/>
									</div>

									<!-- 점수 뱃지 -->
									<div class="absolute right-2 top-2">
										<span class="rounded px-1.5 py-0.5 text-[10px] font-bold {getScoreBadgeClass(item.similarity)}">
											{(item.similarity * 100).toFixed(0)}%
										</span>
									</div>
								</div>

								<!-- 파일 정보 -->
								<div class="p-1.5 space-y-0.5 bg-card">
									<p class="truncate text-[10px] font-medium text-foreground" title={item.file_path}>
										{getFileName(item.file_path)}
									</p>
									<p class="truncate text-[9px] text-muted-foreground" title={getFolderPath(item.file_path)}>
										{getFolderPath(item.file_path).length > 28
											? '...' + getFolderPath(item.file_path).slice(-25)
											: getFolderPath(item.file_path)}
									</p>
									{#if item.reference_file_path}
										<p class="truncate text-[9px] text-primary/70" title={`참조: ${item.reference_file_path}`}>
											참조: {getFileName(item.reference_file_path)}
										</p>
									{/if}
									<!-- svelte-ignore a11y_click_events_have_key_events -->
									<!-- svelte-ignore a11y_no_static_element_interactions -->
									<div class="flex gap-0.5 pt-0.5" onclick={(e) => e.stopPropagation()}>
										<button
											onclick={() => openLocalViewer(item.file_id)}
											class="flex-1 flex items-center justify-center rounded py-0.5 text-[9px] text-muted-foreground hover:bg-muted transition-colors"
											title="뷰어로 열기"
										>
											<Eye class="size-3" />
										</button>
										<button
											onclick={() => openInExplorer(item.file_id)}
											class="flex-1 flex items-center justify-center rounded py-0.5 text-[9px] text-muted-foreground hover:bg-muted transition-colors"
											title="탐색기로 열기"
										>
											<FolderOpen class="size-3" />
										</button>
										<button
											onclick={() => copyToClipboard(item.file_path)}
											class="flex-1 flex items-center justify-center rounded py-0.5 text-[9px] text-muted-foreground hover:bg-muted transition-colors"
											title="경로 복사"
										>
											<Clipboard class="size-3" />
										</button>
									</div>
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
{#if selection.count > 0}
	<div class="fixed bottom-10 left-1/2 z-50 -translate-x-1/2">
		<div class="flex items-center gap-4 rounded-full border bg-card px-5 py-2.5 shadow-xl">
			<span class="text-sm font-semibold">{selection.count}개 선택됨</span>
			<button
				onclick={() => { selection.clear(); }}
				class="rounded-full border px-4 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
			>
				전체 해제
			</button>
		</div>
	</div>
{/if}

<!-- Toast -->
{#if toastMessage}
	<div class="fixed bottom-6 left-1/2 z-[60] -translate-x-1/2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-medium text-foreground shadow-lg">
		{toastMessage}
	</div>
{/if}
