<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { Clock, Calendar, RotateCcw, Tag, Eye, CheckCircle2, FileImage, X, Play } from 'lucide-svelte';

	interface Cluster {
		cluster_id: number;
		start_time: string;
		end_time: string;
		file_count: number;
		duration_minutes: number;
		category_path: string | null;
		reviewed?: boolean;
		preview_file_ids?: number[];
		files?: any[];
	}

	interface Category { id: number; name: string; }

	let clusters: Cluster[] = $state([]);
	let selectedCluster: Cluster | null = $state(null);
	let loading = $state(false);
	let gapMinutes = $state(60);
	let dateFrom = $state('');
	let dateTo = $state('');

	let categories = $state<Category[]>([]);
	let showCategoryPicker = $state(false);
	let categoryTarget: Cluster | null = $state(null);

	// 전체 보기 모달
	let showDetail = $state(false);
	let detailCluster: any = $state(null);
	let detailLoading = $state(false);

	// 클러스터링 실행 상태
	let clusterRunning = $state(false);
	let clusterRunPollTimer: ReturnType<typeof setInterval> | null = null;
	let clusterRunProcessed = $state(0);
	let clusterRunTotal = $state(0);

	onMount(() => {
		loadClusters();
		checkClusteringStatus();
	});

	async function runClustering(mode: 'all' | 'new') {
		if (!confirm(mode === 'all'
			? '기존 클러스터를 삭제하고 전체 재클러스터링합니다. 진행하시겠습니까?'
			: '미분류 파일만 클러스터링합니다. 진행하시겠습니까?'))
			return;

		try {
			const res = await fetchWithTimeout(
				`/api/ic/clusters/run?mode=${mode}&gap_minutes=${gapMinutes}`,
				{ method: 'POST' }
			);
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.detail || `HTTP ${res.status}`);
			}
			clusterRunning = true;
			startClusterPolling();
		} catch (err: any) {
			alert(`클러스터링 시작 실패: ${err.message}`);
		}
	}

	async function checkClusteringStatus() {
		try {
			const res = await fetchWithTimeout('/api/ic/clusters/run/status');
			if (!res.ok) return;
			const data = await res.json();
			clusterRunning = data.is_running;
			clusterRunProcessed = data.processed;
			clusterRunTotal = data.total;
			if (clusterRunning) startClusterPolling();
		} catch { /* ignore */ }
	}

	function startClusterPolling() {
		if (clusterRunPollTimer) return;
		clusterRunPollTimer = setInterval(async () => {
			try {
				const res = await fetchWithTimeout('/api/ic/clusters/run/status');
				if (!res.ok) return;
				const data = await res.json();
				clusterRunning = data.is_running;
				clusterRunProcessed = data.processed;
				clusterRunTotal = data.total;
				if (!data.is_running) {
					clearInterval(clusterRunPollTimer!);
					clusterRunPollTimer = null;
					loadClusters();
				}
			} catch { /* ignore */ }
		}, 2000);
	}

	async function loadClusters() {
		loading = true;
		try {
			const params = new URLSearchParams();
			if (gapMinutes) params.set('gap_minutes', String(gapMinutes));
			if (dateFrom) params.set('date_from', dateFrom);
			if (dateTo) params.set('date_to', dateTo);
			const response = await fetchWithTimeout(`/api/ic/clusters?${params}`);
			if (response.ok) {
				clusters = await response.json();
			}
		} catch (err) {
			console.error('클러스터 로드 실패:', err);
		} finally {
			loading = false;
		}
	}

	async function loadCategories() {
		try {
			const res = await fetchWithTimeout('/api/ic/categories');
			if (res.ok) categories = await res.json();
		} catch { /* ignore */ }
	}

	function selectCluster(cluster: Cluster) {
		categoryTarget = cluster;
		loadCategories();
		showCategoryPicker = true;
	}

	async function assignCategory(categoryId: number) {
		if (!categoryTarget) return;
		try {
			const res = await fetchWithTimeout(`/api/ic/clusters/${categoryTarget.cluster_id}/assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ category_id: categoryId }),
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			showCategoryPicker = false;
			categoryTarget = null;
			loadClusters();
		} catch (err: any) {
			alert(`카테고리 지정 실패: ${err.message}`);
		}
	}

	async function viewClusterDetail(clusterId: number) {
		detailLoading = true;
		showDetail = true;
		try {
			const res = await fetchWithTimeout(`/api/ic/clusters/${clusterId}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			detailCluster = await res.json();
		} catch (err: any) {
			alert(`클러스터 상세 로드 실패: ${err.message}`);
			showDetail = false;
		} finally {
			detailLoading = false;
		}
	}

	async function reviewCluster(clusterId: number) {
		try {
			const res = await fetchWithTimeout(`/api/ic/clusters/${clusterId}/review`, { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			loadClusters();
		} catch (err: any) {
			alert(`검토 완료 실패: ${err.message}`);
		}
	}
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<Clock class="size-5 text-primary" />
				<h2 class="text-xl font-bold tracking-tight">클러스터</h2>
			</div>
			<p class="mt-1 text-sm text-muted-foreground">
				1시간 이내 촬영된 사진을 시간대별로 묶어 검토합니다.
			</p>
		</div>
		<div class="flex items-center gap-2">
			{#if clusterRunning}
				<span class="text-xs text-muted-foreground">
					{clusterRunProcessed}/{clusterRunTotal}
				</span>
			{/if}
			<button
				onclick={() => runClustering('new')}
				disabled={clusterRunning}
				class="flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50 transition-colors"
			>
				<Play class="size-3.5 {clusterRunning ? 'animate-pulse' : ''}" />
				{clusterRunning ? '실행 중...' : '신규만'}
			</button>
			<button
				onclick={() => runClustering('all')}
				disabled={clusterRunning}
				class="flex items-center gap-1.5 rounded-lg border border-amber-500/30 px-3 py-2 text-sm font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50 transition-colors dark:text-amber-400 dark:hover:bg-amber-950/20"
			>
				<RotateCcw class="size-3.5" />
				전체 재생성
			</button>
		</div>
	</div>

	<!-- 컨트롤 카드 -->
	<div class="rounded-xl border bg-card p-4">
		<div class="flex flex-wrap items-end gap-4">
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium text-muted-foreground" for="date-from">시작 날짜</label>
				<input
					id="date-from"
					type="date"
					bind:value={dateFrom}
					class="w-40 rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
				/>
			</div>
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium text-muted-foreground" for="date-to">종료 날짜</label>
				<input
					id="date-to"
					type="date"
					bind:value={dateTo}
					class="w-40 rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
				/>
			</div>
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium text-muted-foreground" for="gap-range">
					클러스터 간격 — <span class="text-foreground font-semibold">{gapMinutes}min</span>
				</label>
				<input
					id="gap-range"
					type="range"
					min="5"
					max="120"
					step="5"
					bind:value={gapMinutes}
					class="w-40 accent-primary"
				/>
			</div>
			<button
				onclick={loadClusters}
				disabled={loading}
				class="flex items-center gap-1.5 rounded-lg border bg-card px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
			>
				<RotateCcw class="size-3.5" />
				재클러스터링
			</button>
		</div>
	</div>

	<!-- 로딩 -->
	{#if loading}
		<div class="flex items-center justify-center py-16 text-sm text-muted-foreground">
			<div class="flex items-center gap-2">
				<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
				로딩 중...
			</div>
		</div>
	{:else if clusters.length === 0}
		<div class="rounded-xl border bg-card py-16 text-center text-sm text-muted-foreground">
			클러스터를 찾을 수 없습니다. 간격이나 날짜 범위를 조정해보세요.
		</div>
	{:else}
		<!-- 클러스터 카드 리스트 -->
		<div class="space-y-3">
			{#each clusters as cluster}
				<div class="rounded-xl border bg-card transition-shadow hover:shadow-md">
					<!-- 카드 헤더 -->
					<div class="flex items-center justify-between border-b px-4 py-3">
						<div class="flex items-center gap-2">
							<Calendar class="size-4 text-muted-foreground" />
							<span class="text-sm font-semibold">{new Date(cluster.start_time).toLocaleDateString('ko-KR')}</span>
							<span class="text-xs text-muted-foreground">
								{new Date(cluster.start_time).toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit'})} – {new Date(cluster.end_time).toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit'})}
							</span>
							<span class="text-xs text-muted-foreground">({cluster.duration_minutes}분)</span>
						</div>
						<div class="flex items-center gap-2">
							<span class="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium">
								{cluster.file_count}장
							</span>
							{#if cluster.category_path}
								<span class="rounded-full bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-600">
									{cluster.category_path}
								</span>
							{/if}
						</div>
					</div>

					<!-- 카드 바디 -->
					<div class="p-4">
						<div class="flex gap-2">
							{#each (cluster.preview_file_ids ?? []) as fileId}
								<div class="size-16 rounded-md overflow-hidden bg-muted/50 flex items-center justify-center shrink-0">
									<img
										src="/api/ic/files/{fileId}/thumbnail"
										alt=""
										class="size-16 object-cover"
										onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; (e.target as HTMLImageElement).nextElementSibling?.classList.remove('hidden'); }}
									/>
									<div class="hidden flex-col items-center justify-center text-muted-foreground">
										<FileImage class="size-5" />
									</div>
								</div>
							{/each}
							{#if cluster.file_count > (cluster.preview_file_ids?.length ?? 0)}
								<div class="flex size-16 items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground">
									+{cluster.file_count - (cluster.preview_file_ids?.length ?? 0)}
								</div>
							{/if}
						</div>
					</div>

					<!-- 카드 푸터 -->
					<div class="flex gap-2 px-4 pb-4">
						<button
							onclick={() => selectCluster(cluster)}
							class="flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
						>
							<Tag class="size-3" />
							카테고리 지정
						</button>
						<button
							onclick={() => viewClusterDetail(cluster.cluster_id)}
							class="flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
						>
							<Eye class="size-3" />
							전체 보기
						</button>
						<button
							onclick={() => reviewCluster(cluster.cluster_id)}
							disabled={cluster.reviewed}
							class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors {cluster.reviewed ? 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30' : 'bg-card hover:bg-muted'} disabled:cursor-not-allowed"
						>
							<CheckCircle2 class="size-3" />
							{cluster.reviewed ? '검토됨' : '검토 완료'}
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}

</div>

<!-- Category Picker Modal -->
{#if showCategoryPicker}
	<div
		role="button"
		tabindex="-1"
		class="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
		onclick={() => (showCategoryPicker = false)}
		onkeydown={(e) => e.key === 'Escape' && (showCategoryPicker = false)}
	></div>
	<div class="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card p-4 shadow-2xl">
		<h3 class="mb-3 text-sm font-semibold text-foreground">
			클러스터 #{categoryTarget?.cluster_id} 카테고리 선택
		</h3>
		{#if categories.length === 0}
			<p class="text-xs text-muted-foreground">카테고리가 없습니다.</p>
		{:else}
			<div class="max-h-60 space-y-1 overflow-y-auto">
				{#each categories as cat}
					<button
						onclick={() => assignCategory(cat.id)}
						class="flex w-full items-center rounded-md px-3 py-2 text-left text-xs font-medium text-foreground hover:bg-accent"
					>
						{cat.name}
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

<!-- Cluster Detail Modal -->
{#if showDetail}
	<div
		role="button"
		tabindex="-1"
		class="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
		onclick={() => (showDetail = false)}
		onkeydown={(e) => e.key === 'Escape' && (showDetail = false)}
	></div>
	<div class="fixed left-1/2 top-1/2 z-50 w-full max-w-2xl max-h-[80vh] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card shadow-2xl overflow-hidden flex flex-col">
		<div class="flex items-center justify-between border-b px-4 py-3">
			<h3 class="text-sm font-semibold">클러스터 상세</h3>
			<button onclick={() => (showDetail = false)} class="rounded-md p-1 hover:bg-muted">
				<X class="size-4" />
			</button>
		</div>
		{#if detailLoading}
			<div class="flex items-center justify-center py-16 text-sm text-muted-foreground">
				<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
			</div>
		{:else if detailCluster}
			<div class="overflow-y-auto p-4">
				<p class="text-xs text-muted-foreground mb-3">
					{detailCluster.category_path ?? '미분류'} · {detailCluster.files?.length ?? 0}장
				</p>
				<div class="grid grid-cols-4 gap-2">
					{#each (detailCluster.files ?? []) as file}
						<div class="group relative">
							<div class="aspect-square rounded-md overflow-hidden bg-muted/50 flex items-center justify-center">
								<img
									src={file.thumbnail_url}
									alt=""
									class="w-full h-full object-cover"
									onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; (e.target as HTMLImageElement).nextElementSibling?.classList.remove('hidden'); }}
								/>
								<div class="hidden flex-col items-center justify-center text-muted-foreground">
									<FileImage class="size-6" />
								</div>
							</div>
							<p class="mt-1 text-[10px] text-muted-foreground truncate" title={file.file_path}>
								{file.file_path?.split(/[/\\]/).pop()}
							</p>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</div>
{/if}
