<svelte:head><title>클러스터 — 이미지 분류기</title></svelte:head>

<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { Clock, Calendar, RotateCcw, Tag, Eye, CheckCircle2 } from 'lucide-svelte';

	interface Cluster {
		cluster_id: number;
		start_time: string;
		end_time: string;
		file_count: number;
		duration_minutes: number;
		category_path: string | null;
		files?: any[];
	}

	let clusters: Cluster[] = $state([]);
	let selectedCluster: Cluster | null = $state(null);
	let loading = $state(false);
	let gapMinutes = $state(60);
	let dateFrom = $state('');
	let dateTo = $state('');

	onMount(() => {
		loadClusters();
	});

	async function loadClusters() {
		loading = true;
		try {
			const params = new URLSearchParams();
			if (gapMinutes) params.set('gap_minutes', String(gapMinutes));
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

	function selectCluster(cluster: Cluster) {
		selectedCluster = cluster;
	}
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<Clock class="size-5 text-primary" />
				<h1 class="text-2xl font-bold tracking-tight">클러스터</h1>
			</div>
			<p class="mt-1 text-sm text-muted-foreground">
				1시간 이내 촬영된 사진을 시간대별로 묶어 검토합니다.
			</p>
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
							{#each { length: Math.min(5, cluster.file_count) } as _}
								<div class="flex size-16 items-center justify-center rounded-md bg-muted">
									<span class="text-[10px] text-muted-foreground">IMG</span>
								</div>
							{/each}
							{#if cluster.file_count > 5}
								<div class="flex size-16 items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground">
									+{cluster.file_count - 5}
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
							class="flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
						>
							<Eye class="size-3" />
							전체 보기
						</button>
						<button
							disabled={!!cluster.category_path}
							class="flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
						>
							<CheckCircle2 class="size-3" />
							검토 완료
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}

	<!-- 선택된 클러스터 상세 -->
	{#if selectedCluster}
		<div class="rounded-xl border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">클러스터 #{selectedCluster.cluster_id}</h2>
			<p class="text-xs text-muted-foreground">
				{new Date(selectedCluster.start_time).toLocaleDateString('ko-KR')} · {new Date(selectedCluster.start_time).toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit'})} – {new Date(selectedCluster.end_time).toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit'})} · {selectedCluster.file_count}장
			</p>
		</div>
	{/if}
</div>
