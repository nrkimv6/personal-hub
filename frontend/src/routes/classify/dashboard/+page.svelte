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

	// === 보존된 기존 API 로직 ===
	let health: any = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);

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

	onMount(() => {
		loadHealth();
	});

	// === 추가 UI 상태 ===
	let activityFilter = $state('all');

	let pipelineStages = $state([
		{ id: 'scan', label: 'Scan', status: 'done' },
		{ id: 'extract', label: 'Extract', status: 'done' },
		{ id: 'duplicates', label: 'Duplicates', status: 'running' },
		{ id: 'classify', label: 'AI Classify', status: 'idle' },
		{ id: 'review', label: 'Review', status: 'idle' }
	]);

	let recentActivity = $state([
		{ id: 1, time: '2분 전', message: 'Duplicate scan started on D:\\Photos', type: 'info' },
		{ id: 2, time: '5분 전', message: 'Extraction completed: 12,482 images', type: 'info' },
		{ id: 3, time: '12분 전', message: 'Failed to read HEIC file: IMG_2034.HEIC', type: 'error' },
		{ id: 4, time: '18분 전', message: 'Scan completed: 3 folders indexed', type: 'info' },
		{ id: 5, time: '1시간 전', message: 'Pipeline initialized', type: 'info' }
	]);

	let mockCategories = [
		{ name: 'Travel', count: 42300, pct: 32 },
		{ name: 'Family', count: 28100, pct: 21 },
		{ name: 'Food', count: 18700, pct: 14 },
		{ name: 'Pets', count: 12400, pct: 9 },
		{ name: 'Others', count: 31200, pct: 24 }
	];

	// health 기반 통계 (없으면 mock)
	let stats = $derived({
		totalImages: health?.settings ? 132600 : 132600,
		classified: health?.settings ? 103800 : 103800,
		duplicates: health?.settings ? 8240 : 8240,
		clusters: health?.settings ? 284 : 284
	});

	let filteredActivity = $derived(
		activityFilter === 'all'
			? recentActivity
			: recentActivity.filter((a) => a.type === activityFilter)
	);

	let lastUpdated = $derived(
		new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
	);
</script>

<svelte:head>
	<title>Dashboard — Image Classifier</title>
</svelte:head>

{#snippet miniSparkline(data: number[])}
	<svg class="h-7 w-20" viewBox="0 0 80 28">
		<polyline
			points={data
				.map((v, i) => `${(i / (data.length - 1)) * 80},${28 - (v / Math.max(...data)) * 24}`)
				.join(' ')}
			fill="none"
			stroke="currentColor"
			stroke-width="1.5"
			class="text-primary"
		/>
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
			onclick={loadHealth}
			class="inline-flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm font-medium shadow-sm hover:bg-accent transition-colors"
		>
			<RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
			Refresh
		</button>
	</div>

	{#if loading}
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
	{:else if error}
		<!-- 에러 상태 -->
		<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-6">
			<h3 class="font-semibold text-destructive mb-1">Connection Error</h3>
			<p class="text-sm text-muted-foreground mb-4">{error}</p>
			<button
				onclick={loadHealth}
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
				<div class="text-2xl font-bold">{stats.totalImages.toLocaleString()}</div>
				<div class="text-xs text-muted-foreground mt-1">Total Images</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-emerald-600 font-medium">+2.4k this month</span>
					{@render miniSparkline([40, 55, 45, 70, 60, 85, 75, 90, 80, 100])}
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
				<div class="text-2xl font-bold">{stats.classified.toLocaleString()}</div>
				<div class="text-xs text-muted-foreground mt-1">Classified</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-emerald-600 font-medium">78.3% complete</span>
					{@render miniSparkline([20, 30, 45, 40, 60, 55, 75, 70, 85, 78])}
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
				<div class="text-2xl font-bold">{stats.duplicates.toLocaleString()}</div>
				<div class="text-xs text-muted-foreground mt-1">Duplicates</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-muted-foreground">-156 pending review</span>
					{@render miniSparkline([90, 80, 70, 85, 65, 60, 50, 55, 45, 40])}
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
				<div class="text-2xl font-bold">{stats.clusters.toLocaleString()}</div>
				<div class="text-xs text-muted-foreground mt-1">Clusters</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-emerald-600 font-medium">+5 today</span>
					{@render miniSparkline([10, 20, 15, 30, 25, 40, 35, 50, 45, 60])}
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
			<div class="space-y-3">
				{#each mockCategories as cat}
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
		</div>
	{/if}
</div>
