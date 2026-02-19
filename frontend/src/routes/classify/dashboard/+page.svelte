<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import {
		Images,
		CheckCircle2,
		Copy,
		Clock,
		Play,
		Brain,
		Database,
		ArrowUpRight,
		ArrowDownRight,
		Filter,
		TrendingUp,
		RefreshCw,
		Loader2
	} from 'lucide-svelte';

	// === Health API 상태 ===
	let health: any = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);

	// === Stats API 상태 ===
	let statsData: any = $state(null);
	let statsLoading = $state(true);
	let statsError: string | null = $state(null);

	async function loadHealth() {
		loading = true;
		error = null;
		try {
			const res = await fetchWithTimeout('/api/ic/health');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			health = await res.json();
		} catch (err: any) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	async function loadStats() {
		statsLoading = true;
		statsError = null;
		try {
			const res = await fetchWithTimeout('/api/ic/stats');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			statsData = await res.json();
		} catch (err: any) {
			statsError = err.message;
		} finally {
			statsLoading = false;
		}
	}

	async function loadActivity() {
		try {
			const res = await fetchWithTimeout('/api/ic/stats/activity?limit=10');
			if (!res.ok) return;
			const data = await res.json();
			recentActivity = data.activity ?? [];
		} catch {
			// 실패해도 빈 배열 유지
		}
	}

	onMount(() => {
		loadHealth();
		loadStats();
		loadActivity();
	});

	// === UI 상태 ===
	let activityFilter = $state('all');

	// pipelineStages: 기본 idle, 추후 stats/tasks 기반으로 파생
	let pipelineStages = $state([
		{ id: 'scan', label: 'Scan', status: 'idle' },
		{ id: 'extract', label: 'Extract', status: 'idle' },
		{ id: 'duplicates', label: 'Duplicates', status: 'idle' },
		{ id: 'classify', label: 'AI Classify', status: 'idle' },
		{ id: 'review', label: 'Review', status: 'idle' }
	]);

	let recentActivity = $state<{ id: number; time: string; message: string; type: string }[]>([]);

	// 통계 카드 (API 응답 기반, 없으면 0)
	let stats = $derived({
		totalImages: statsData?.total_images ?? 0,
		classified: statsData?.classified ?? 0,
		duplicates: statsData?.duplicates ?? 0,
		clusters: statsData?.clusters ?? 0
	});

	// 카테고리 분포 (API 응답 기반)
	let categories = $derived<{ name: string; count: number; pct: number }[]>(
		statsData?.category_distribution ?? []
	);

	let filteredActivity = $derived(
		activityFilter === 'all'
			? recentActivity
			: recentActivity.filter((a) => a.type === activityFilter)
	);

	let lastUpdated = $derived(
		new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
	);

	async function handleRefresh() {
		await Promise.all([loadHealth(), loadStats(), loadActivity()]);
	}
</script>

<svelte:head>
	<title>Dashboard — Image Classifier</title>
</svelte:head>

{#snippet miniSparkline(data: number[])}
	<svg class="h-7 w-20" viewBox="0 0 80 28">
		{#if data.length > 1}
			<polyline
				points={data
					.map((v, i) => `${(i / (data.length - 1)) * 80},${28 - (v / Math.max(...data)) * 24}`)
					.join(' ')}
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				class="text-primary"
			/>
		{/if}
	</svg>
{/snippet}

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-2xl font-bold tracking-tight">Dashboard</h1>
			<p class="text-sm text-muted-foreground mt-0.5">Last updated {lastUpdated}</p>
		</div>
		<button
			onclick={handleRefresh}
			class="inline-flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm font-medium shadow-sm hover:bg-accent transition-colors"
		>
			<RefreshCw class="h-4 w-4 {loading || statsLoading ? 'animate-spin' : ''}" />
			Refresh
		</button>
	</div>

	{#if loading && statsLoading}
		<!-- 로딩 상태 -->
		<div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
			{#each [1, 2, 3, 4] as _}
				<div class="rounded-lg border bg-card p-5 animate-pulse">
					<div class="h-4 w-24 bg-muted rounded mb-4"></div>
					<div class="h-8 w-16 bg-muted rounded mb-2"></div>
					<div class="h-3 w-32 bg-muted rounded"></div>
				</div>
			{/each}
		</div>
	{:else if error && statsError}
		<!-- 에러 상태 (health + stats 모두 실패) -->
		<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-6">
			<h3 class="font-semibold text-destructive mb-1">Connection Error</h3>
			<p class="text-sm text-muted-foreground mb-4">{error}</p>
			<button
				onclick={handleRefresh}
				class="inline-flex items-center gap-2 rounded-md bg-destructive px-3 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 transition-colors"
			>
				<RefreshCw class="h-4 w-4" />
				Retry
			</button>
		</div>
	{:else}
		<!-- 통계 카드 4열 -->
		<div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
			<!-- Total Images -->
			<div class="rounded-lg border bg-card p-5">
				<div class="flex items-start justify-between mb-3">
					<div class="rounded-md bg-primary/10 p-2">
						<Images class="h-4 w-4 text-primary" />
					</div>
					<ArrowUpRight class="h-4 w-4 text-muted-foreground" />
				</div>
				{#if statsLoading}
					<div class="h-8 w-16 bg-muted rounded animate-pulse mb-2"></div>
				{:else}
					<div class="text-2xl font-bold">{stats.totalImages.toLocaleString()}</div>
				{/if}
				<div class="text-xs text-muted-foreground mt-1">Total Images</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-muted-foreground">전체 스캔 파일</span>
					{@render miniSparkline([])}
				</div>
			</div>

			<!-- Classified -->
			<div class="rounded-lg border bg-card p-5">
				<div class="flex items-start justify-between mb-3">
					<div class="rounded-md bg-emerald-500/10 p-2">
						<CheckCircle2 class="h-4 w-4 text-emerald-600" />
					</div>
					<ArrowUpRight class="h-4 w-4 text-muted-foreground" />
				</div>
				{#if statsLoading}
					<div class="h-8 w-16 bg-muted rounded animate-pulse mb-2"></div>
				{:else}
					<div class="text-2xl font-bold">{stats.classified.toLocaleString()}</div>
				{/if}
				<div class="text-xs text-muted-foreground mt-1">Classified</div>
				<div class="flex items-center justify-between mt-3">
					{#if stats.totalImages > 0}
						<span class="text-xs text-emerald-600 font-medium">
							{Math.round((stats.classified / stats.totalImages) * 100)}% complete
						</span>
					{:else}
						<span class="text-xs text-muted-foreground">데이터 없음</span>
					{/if}
					{@render miniSparkline([])}
				</div>
			</div>

			<!-- Duplicates -->
			<div class="rounded-lg border bg-card p-5">
				<div class="flex items-start justify-between mb-3">
					<div class="rounded-md bg-amber-500/10 p-2">
						<Copy class="h-4 w-4 text-amber-600" />
					</div>
					<ArrowDownRight class="h-4 w-4 text-muted-foreground" />
				</div>
				{#if statsLoading}
					<div class="h-8 w-16 bg-muted rounded animate-pulse mb-2"></div>
				{:else}
					<div class="text-2xl font-bold">{stats.duplicates.toLocaleString()}</div>
				{/if}
				<div class="text-xs text-muted-foreground mt-1">Duplicates</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-muted-foreground">중복 해시 그룹</span>
					{@render miniSparkline([])}
				</div>
			</div>

			<!-- Clusters -->
			<div class="rounded-lg border bg-card p-5">
				<div class="flex items-start justify-between mb-3">
					<div class="rounded-md bg-violet-500/10 p-2">
						<Clock class="h-4 w-4 text-violet-600" />
					</div>
					<TrendingUp class="h-4 w-4 text-muted-foreground" />
				</div>
				{#if statsLoading}
					<div class="h-8 w-16 bg-muted rounded animate-pulse mb-2"></div>
				{:else}
					<div class="text-2xl font-bold">{stats.clusters.toLocaleString()}</div>
				{/if}
				<div class="text-xs text-muted-foreground mt-1">Clusters</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-muted-foreground">타임 클러스터</span>
					{@render miniSparkline([])}
				</div>
			</div>
		</div>

		<!-- Pipeline Status -->
		<div class="rounded-lg border bg-card p-5">
			<h2 class="text-sm font-semibold mb-4">Pipeline Status</h2>
			<div class="flex items-center gap-0 overflow-x-auto">
				{#each pipelineStages as stage, i}
					<div
						class="flex items-center gap-2 rounded-md border px-3 py-2 min-w-fit text-sm
						{stage.status === 'done'
							? 'bg-emerald-500/10 border-emerald-500/30'
							: stage.status === 'running'
								? 'bg-primary/10 border-primary/30'
								: 'bg-secondary border-border'}"
					>
						{#if stage.status === 'done'}
							<CheckCircle2 class="h-4 w-4 text-emerald-600 shrink-0" />
						{:else if stage.status === 'running'}
							<div class="relative h-4 w-4 shrink-0">
								<Loader2 class="h-4 w-4 text-primary animate-spin" />
								<span
									class="absolute inset-0 rounded-full bg-primary/30 animate-ping"
									style="transform: scale(0.6)"
								></span>
							</div>
						{:else}
							<div class="h-4 w-4 shrink-0 rounded-full border-2 border-muted-foreground/30"></div>
						{/if}
						<span
							class="font-medium
							{stage.status === 'done'
								? 'text-emerald-700'
								: stage.status === 'running'
									? 'text-primary'
									: 'text-muted-foreground'}"
						>
							{stage.label}
						</span>
						<span
							class="text-xs px-1.5 py-0.5 rounded-full
							{stage.status === 'done'
								? 'bg-emerald-100 text-emerald-700'
								: stage.status === 'running'
									? 'bg-primary/20 text-primary'
									: 'bg-muted text-muted-foreground'}"
						>
							{stage.status}
						</span>
					</div>
					{#if i < pipelineStages.length - 1}
						<div class="flex items-center px-2 text-muted-foreground">
							<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
							</svg>
						</div>
					{/if}
				{/each}
			</div>
		</div>

		<!-- 하단 3열 -->
		<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
			<!-- Quick Actions -->
			<div class="rounded-lg border bg-card p-5 col-span-1">
				<h2 class="text-sm font-semibold mb-4">Quick Actions</h2>
				<div class="space-y-2">
					<button
						class="w-full inline-flex items-center justify-center gap-2 rounded-md bg-primary px-3 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
					>
						<Play class="h-4 w-4" />
						Start Full Pipeline
					</button>
					<button
						class="w-full inline-flex items-center justify-center gap-2 rounded-md border bg-background px-3 py-2.5 text-sm font-medium hover:bg-accent transition-colors"
					>
						<Brain class="h-4 w-4" />
						Start AI Classification
					</button>
					<button
						class="w-full inline-flex items-center justify-center gap-2 rounded-md border bg-background px-3 py-2.5 text-sm font-medium hover:bg-accent transition-colors"
					>
						<Database class="h-4 w-4" />
						Find Duplicates
					</button>
				</div>

				{#if health}
					<div class="mt-4 pt-4 border-t space-y-2 text-xs text-muted-foreground">
						<div class="flex justify-between">
							<span>Status</span>
							<span class="font-medium text-foreground">{health.status}</span>
						</div>
						<div class="flex justify-between">
							<span>Database</span>
							<span class="font-medium text-foreground">{health.database}</span>
						</div>
						<div class="flex justify-between">
							<span>AI Mode</span>
							<span class="font-medium text-foreground">{health.ai_adapters?.mode ?? '—'}</span>
						</div>
					</div>
				{/if}
			</div>

			<!-- Recent Activity -->
			<div class="rounded-lg border bg-card p-5 col-span-2">
				<div class="flex items-center justify-between mb-4">
					<h2 class="text-sm font-semibold">Recent Activity</h2>
					<div class="flex items-center gap-1">
						<Filter class="h-3.5 w-3.5 text-muted-foreground" />
						{#each ['all', 'info', 'error'] as f}
							<button
								onclick={() => (activityFilter = f)}
								class="px-2 py-1 rounded text-xs font-medium transition-colors
								{activityFilter === f
									? 'bg-primary text-primary-foreground'
									: 'bg-muted text-muted-foreground hover:bg-accent'}"
							>
								{f}
							</button>
						{/each}
					</div>
				</div>
				<div class="max-h-64 overflow-y-auto divide-y divide-border">
					{#each filteredActivity as item}
						<div class="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
							<div
								class="mt-0.5 h-2 w-2 rounded-full shrink-0
								{item.type === 'error' ? 'bg-destructive' : 'bg-emerald-500'}"
							></div>
							<div class="flex-1 min-w-0">
								<p class="text-xs text-foreground truncate">{item.message}</p>
								<p class="text-xs text-muted-foreground mt-0.5">{item.time}</p>
							</div>
						</div>
					{:else}
						<p class="text-sm text-muted-foreground py-4 text-center">No activity</p>
					{/each}
				</div>
			</div>
		</div>

		<!-- Classification Distribution -->
		<div class="rounded-lg border bg-card p-5">
			<h2 class="text-sm font-semibold mb-4">Classification Distribution</h2>
			{#if statsLoading}
				<div class="space-y-3">
					{#each [1, 2, 3] as _}
						<div class="flex items-center gap-3 animate-pulse">
							<div class="h-4 w-24 bg-muted rounded shrink-0"></div>
							<div class="flex-1 h-2 bg-muted rounded-full"></div>
							<div class="h-3 w-10 bg-muted rounded"></div>
						</div>
					{/each}
				</div>
			{:else if categories.length === 0}
				<p class="text-sm text-muted-foreground text-center py-4">분류된 데이터가 없습니다</p>
			{:else}
				<div class="space-y-3">
					{#each categories as cat}
						<div class="flex items-center gap-3">
							<span class="text-sm text-foreground w-24 shrink-0 truncate">{cat.name}</span>
							<div class="flex-1 h-2 rounded-full bg-muted overflow-hidden">
								<div
									class="h-full rounded-full bg-primary transition-all"
									style="width: {cat.pct}%"
								></div>
							</div>
							<span class="text-xs text-muted-foreground w-10 text-right shrink-0">{cat.pct}%</span>
							<span class="text-xs text-muted-foreground w-16 text-right shrink-0">
								{cat.count.toLocaleString()}
							</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
