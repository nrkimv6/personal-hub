<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { Clock, Calendar, RotateCcw, Tag, Eye, CheckCircle2 } from 'lucide-svelte';

	interface Cluster {
		id: number;
		date: string;
		start_time: string;
		end_time: string;
		file_count: number;
		category_name: string | null;
		is_classified: boolean;
		files: any[];
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
			const response = await fetchWithTimeout('/api/ic/clusters');
			if (response.ok) {
				clusters = await response.json();
			}
		} catch (err) {
			console.error('Failed to load clusters:', err);
		} finally {
			loading = false;
		}
	}

	function selectCluster(cluster: Cluster) {
		selectedCluster = cluster;
	}
</script>

<div class="mx-auto max-w-5xl space-y-6 p-6">
	<!-- 헤더 -->
	<div>
		<div class="flex items-center gap-2">
			<Clock class="size-6 text-primary" />
			<h1 class="text-2xl font-bold tracking-tight">Time Clusters</h1>
		</div>
		<p class="mt-1 text-sm text-muted-foreground">
			1시간 이내 촬영된 사진을 시간대별로 묶어 검토합니다.
		</p>
	</div>

	<!-- 컨트롤 카드 -->
	<div class="rounded-xl border bg-card p-4">
		<div class="flex flex-wrap items-end gap-4">
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium text-muted-foreground" for="date-from">Date From</label>
				<input
					id="date-from"
					type="date"
					bind:value={dateFrom}
					class="w-40 rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
				/>
			</div>
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium text-muted-foreground" for="date-to">Date To</label>
				<input
					id="date-to"
					type="date"
					bind:value={dateTo}
					class="w-40 rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
				/>
			</div>
			<div class="flex flex-col gap-1">
				<label class="text-xs font-medium text-muted-foreground" for="gap-range">
					Cluster Gap — <span class="text-foreground font-semibold">{gapMinutes}min</span>
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
				Re-cluster
			</button>
		</div>
	</div>

	<!-- 로딩 -->
	{#if loading}
		<div class="flex items-center justify-center py-16 text-sm text-muted-foreground">
			<div class="flex items-center gap-2">
				<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
				Loading clusters...
			</div>
		</div>
	{:else if clusters.length === 0}
		<div class="rounded-xl border bg-card py-16 text-center text-sm text-muted-foreground">
			No clusters found. Try adjusting the gap or date range.
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
							<span class="text-sm font-semibold">{cluster.date}</span>
							<span class="text-xs text-muted-foreground">
								{cluster.start_time} – {cluster.end_time}
							</span>
						</div>
						<div class="flex items-center gap-2">
							<span class="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium">
								{cluster.file_count} images
							</span>
							{#if cluster.is_classified}
								<span class="rounded-full bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-600">
									Reviewed
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
							Assign Category
						</button>
						<button
							class="flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
						>
							<Eye class="size-3" />
							View All
						</button>
						<button
							disabled={cluster.is_classified}
							class="flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
						>
							<CheckCircle2 class="size-3" />
							Mark Reviewed
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}

	<!-- 선택된 클러스터 상세 -->
	{#if selectedCluster}
		<div class="rounded-xl border bg-card p-4">
			<h2 class="mb-1 text-sm font-semibold">Cluster #{selectedCluster.id}</h2>
			<p class="text-xs text-muted-foreground">
				{selectedCluster.date} · {selectedCluster.start_time} – {selectedCluster.end_time} · {selectedCluster.file_count} images
			</p>
		</div>
	{/if}
</div>
