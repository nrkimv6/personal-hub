<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
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
		Loader2,
		LayoutDashboard,
		AlertCircle,
		Terminal,
		ChevronDown,
		ChevronUp,
		Timer
	} from 'lucide-svelte';

	function getStatusLabel(status: string): string {
		if (status === 'done') return '완료';
		if (status === 'running') return '실행 중';
		if (status === 'error') return '오류';
		return '대기';
	}

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

	// === 파이프라인 상세 상태 (통합 API) ===
	interface StageDetail {
		is_running: boolean;
		processed: number;
		total: number;
		progress_percent: number;
		current_item: string | null;
		eta: { eta_display: string; elapsed_seconds: number; items_per_second: number } | null;
		last_run: {
			status: string;
			total_items: number;
			processed_items: number;
			completed_at: string | null;
			started_at: string | null;
		} | null;
		[key: string]: any;
	}

	interface PipelineDetail {
		scan: StageDetail;
		thumbnail: StageDetail;
		phash: StageDetail;
		duplicate: StageDetail;
		classify: StageDetail;
		logs: { stage: string; message: string; timestamp: string }[];
	}

	let pipelineDetail: PipelineDetail | null = $state(null);
	let pipelinePollingId: ReturnType<typeof setInterval> | null = null;

	/** 파이프라인 API에서 상세 데이터 가져와 pipelineDetail + pipelineStages 업데이트 */
	async function pollPipelineStatus() {
		try {
			const res = await fetchWithTimeout('/api/ic/stats/pipeline');
			if (!res.ok) return;
			pipelineDetail = await res.json();

			// pipelineStages 동기화
			if (pipelineDetail) {
				const stageMap: Record<string, StageDetail> = {
					scan: pipelineDetail.scan,
					extract: pipelineDetail.thumbnail,
					phash: pipelineDetail.phash,
					duplicates: pipelineDetail.duplicate,
					classify: pipelineDetail.classify
				};

				pipelineStages = pipelineStages.map((s) => {
					const detail = stageMap[s.id];
					if (!detail) return s;

					let status = s.status;
					// 폴링 중 실행상태 감지: 파이프라인 실행 중이면 pollUntilDone이 관리하므로 스킵
					if (!pipelineRunning) {
						if (detail.is_running) {
							status = 'running';
						} else if (detail.last_run) {
							if (detail.last_run.status === 'completed') status = 'done';
							else if (detail.last_run.status === 'failed') status = 'error';
						}
					}
					return { ...s, status };
				});
			}
		} catch {
			// 폴링 실패 무시
		}
	}

	function startPipelinePolling() {
		if (pipelinePollingId) return;
		pollPipelineStatus();
		pipelinePollingId = setInterval(pollPipelineStatus, 2000);
	}

	function stopPipelinePolling() {
		if (pipelinePollingId) {
			clearInterval(pipelinePollingId);
			pipelinePollingId = null;
		}
	}

	onMount(() => {
		loadHealth();
		loadStats();
		loadActivity();
		// 초기 로드: 이전 진행률 복원
		pollPipelineStatus();
	});

	onDestroy(() => {
		stopPipelinePolling();
	});

	// === UI 상태 ===
	let activityFilter = $state('all');

	let pipelineStages = $state([
		{ id: 'scan', label: '스캔', status: 'idle' },
		{ id: 'extract', label: '추출', status: 'idle' },
		{ id: 'phash', label: 'pHash', status: 'idle' },
		{ id: 'duplicates', label: '중복 검출', status: 'idle' },
		{ id: 'classify', label: 'AI 분류', status: 'idle' },
		{ id: 'review', label: '검토', status: 'idle' }
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
		await Promise.all([loadHealth(), loadStats(), loadActivity(), pollPipelineStatus()]);
	}

	// === 파이프라인 실행 ===
	let pipelineRunning = $state(false);
	let pipelineAbort: AbortController | null = $state(null);

	const stageStatusUrls: Record<string, string> = {
		scan: '/api/ic/scan/status',
		extract: '/api/ic/scan/thumbnails/status',
		phash: '/api/ic/scan/phash/status',
		duplicates: '/api/ic/duplicates/detect/status',
		classify: '/api/ic/classify/status'
	};

	function updateStage(id: string, status: string) {
		pipelineStages = pipelineStages.map((s) => (s.id === id ? { ...s, status } : s));
	}

	function resetStages() {
		pipelineStages = pipelineStages.map((s) => ({ ...s, status: 'idle' }));
		clientLogs = [];
	}

	async function pollUntilDone(stageId: string, signal?: AbortSignal): Promise<boolean> {
		const url = stageStatusUrls[stageId];
		if (!url) return true;

		updateStage(stageId, 'running');

		while (true) {
			if (signal?.aborted) return false;
			await new Promise((r) => setTimeout(r, 2000));

			try {
				const res = await fetchWithTimeout(url);
				if (!res.ok) continue;
				const data = await res.json();

				// 각 API의 running 판정 필드가 다름
				const isRunning =
					data.is_running === true || data.running === true || data.status === 'running';

				if (!isRunning) {
					const hasError = data.error || data.error_message || data.status === 'failed';
					updateStage(stageId, hasError ? 'error' : 'done');
					return !hasError;
				}
			} catch {
				// 네트워크 에러는 무시하고 재시도
			}
		}
	}

	async function startFullPipeline() {
		if (pipelineRunning) return;
		pipelineRunning = true;
		const abort = new AbortController();
		pipelineAbort = abort;
		resetStages();
		logPanelExpanded = true;

		// 폴링 시작
		startPipelinePolling();

		const steps = [
			{ id: 'scan', url: '/api/ic/scan/start', method: 'POST' },
			{ id: 'extract', url: '/api/ic/scan/thumbnails', method: 'POST' },
			{ id: 'phash', url: '/api/ic/scan/phash', method: 'POST' },
			{ id: 'duplicates', url: '/api/ic/duplicates/detect', method: 'POST' },
			{ id: 'classify', url: '/api/ic/classify/start', method: 'POST' }
		];

		try {
			for (const step of steps) {
				if (abort.signal.aborted) break;
				updateStage(step.id, 'running');

				const res = await fetchWithTimeout(step.url, { method: step.method });
				if (!res.ok) {
					const detail = await res.text().catch(() => '');
					addClientLog(step.id, `${res.status} ${res.statusText}${detail ? ' — ' + detail.slice(0, 200) : ''}`);
					updateStage(step.id, 'error');
					break;
				}

				const ok = await pollUntilDone(step.id, abort.signal);
				if (!ok) break;
			}
		} finally {
			pipelineRunning = false;
			pipelineAbort = null;
			stopPipelinePolling();
			// 최종 상태 반영
			await pollPipelineStatus();
			loadStats();
		}
	}

	function stopPipeline() {
		pipelineAbort?.abort();
		pipelineRunning = false;
		pipelineAbort = null;
		stopPipelinePolling();
	}

	let classifyRunning = $state(false);
	async function startClassification() {
		if (classifyRunning) return;
		classifyRunning = true;
		updateStage('classify', 'running');
		startPipelinePolling();
		try {
			const res = await fetchWithTimeout('/api/ic/classify/start', { method: 'POST' });
			if (!res.ok) {
				const detail = await res.text().catch(() => '');
				addClientLog('classify', `${res.status} ${res.statusText}${detail ? ' — ' + detail.slice(0, 200) : ''}`);
				logPanelExpanded = true;
				updateStage('classify', 'error');
				return;
			}
			await pollUntilDone('classify');
		} finally {
			classifyRunning = false;
			stopPipelinePolling();
			loadStats();
		}
	}

	let duplicateRunning = $state(false);
	async function startDuplicateDetect() {
		if (duplicateRunning) return;
		duplicateRunning = true;
		updateStage('duplicates', 'running');
		startPipelinePolling();
		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/detect', { method: 'POST' });
			if (!res.ok) {
				const detail = await res.text().catch(() => '');
				addClientLog('duplicate', `${res.status} ${res.statusText}${detail ? ' — ' + detail.slice(0, 200) : ''}`);
				logPanelExpanded = true;
				updateStage('duplicates', 'error');
				return;
			}
			await pollUntilDone('duplicates');
		} finally {
			duplicateRunning = false;
			stopPipelinePolling();
			loadStats();
		}
	}

	// === 로그 패널 ===
	let logPanelExpanded = $state(false);
	let clientLogs = $state<{ stage: string; message: string; timestamp: string }[]>([]);

	function addClientLog(stage: string, message: string) {
		clientLogs.push({ stage, message, timestamp: new Date().toISOString() });
	}

	let mergedLogs = $derived(
		[...((pipelineDetail as PipelineDetail | null)?.logs ?? []), ...clientLogs].sort((a, b) =>
			a.timestamp.localeCompare(b.timestamp)
		)
	);

	// 단계별 상세 데이터 헬퍼
	function getStageDetail(stageId: string): StageDetail | null {
		if (!pipelineDetail) return null;
		const map: Record<string, StageDetail> = {
			scan: pipelineDetail.scan,
			extract: pipelineDetail.thumbnail,
			phash: pipelineDetail.phash,
			duplicates: pipelineDetail.duplicate,
			classify: pipelineDetail.classify
		};
		return map[stageId] ?? null;
	}

	function getStageProgressText(stageId: string): string {
		const detail = getStageDetail(stageId);
		if (!detail) return '';

		if (detail.is_running) {
			if (stageId === 'scan') {
				return `${detail.processed}/${detail.total} 폴더`;
			}
			return `${detail.processed.toLocaleString()}/${detail.total.toLocaleString()}`;
		}

		// 비실행 시 last_run 요약
		if (detail.last_run && detail.last_run.processed_items > 0) {
			return `${detail.last_run.processed_items.toLocaleString()}건 처리 완료`;
		}
		return '';
	}

	function getStageCurrentItem(stageId: string): string {
		const detail = getStageDetail(stageId);
		if (!detail?.is_running || !detail.current_item) return '';
		// 파일명만 추출
		const parts = detail.current_item.replace(/\\/g, '/').split('/');
		const name = parts[parts.length - 1];
		return name.length > 30 ? name.slice(0, 27) + '...' : name;
	}

	function getStageEta(stageId: string): string {
		const detail = getStageDetail(stageId);
		if (!detail?.is_running) return '';
		if (detail.eta) return detail.eta.eta_display;
		if (detail.processed > 0) return '계산 중...';
		return '';
	}

	function getStageProgressPercent(stageId: string): number {
		const detail = getStageDetail(stageId);
		if (!detail) return 0;
		if (detail.is_running) return detail.progress_percent;
		if (detail.last_run?.status === 'completed') return 100;
		return 0;
	}
</script>

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
			<div class="flex items-center gap-2">
				<LayoutDashboard class="size-5 text-primary" />
				<h2 class="text-xl font-bold tracking-tight">파이프라인</h2>
			</div>
			<p class="text-sm text-muted-foreground mt-1">마지막 업데이트 {lastUpdated}</p>
		</div>
		<button
			onclick={handleRefresh}
			class="inline-flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm font-medium shadow-sm hover:bg-accent transition-colors"
		>
			<RefreshCw class="h-4 w-4 {loading || statsLoading ? 'animate-spin' : ''}" />
			새로고침
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
			<h3 class="font-semibold text-destructive mb-1">연결 오류</h3>
			<p class="text-sm text-muted-foreground mb-4">{error}</p>
			<button
				onclick={handleRefresh}
				class="inline-flex items-center gap-2 rounded-md bg-destructive px-3 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 transition-colors"
			>
				<RefreshCw class="h-4 w-4" />
				다시 시도
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
				<div class="text-xs text-muted-foreground mt-1">전체 이미지</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-muted-foreground">&nbsp;</span>
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
				<div class="text-xs text-muted-foreground mt-1">분류 완료</div>
				<div class="flex items-center justify-between mt-3">
					{#if stats.totalImages > 0}
						<span class="text-xs text-emerald-600 font-medium">
							{Math.round((stats.classified / stats.totalImages) * 100)}% 완료
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
				<div class="text-xs text-muted-foreground mt-1">중복</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-muted-foreground">&nbsp;</span>
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
				<div class="text-xs text-muted-foreground mt-1">클러스터</div>
				<div class="flex items-center justify-between mt-3">
					<span class="text-xs text-muted-foreground">&nbsp;</span>
					{@render miniSparkline([])}
				</div>
			</div>
		</div>

		<!-- Pipeline Status (확장된 진행률 UI) -->
		<div class="rounded-lg border bg-card p-5">
			<h3 class="text-sm font-semibold mb-4">파이프라인 상태</h3>
			<div class="flex flex-col gap-3">
				<div class="flex items-center gap-0 overflow-x-auto">
					{#each pipelineStages as stage, i}
						<div class="flex flex-col items-center min-w-fit">
							<div
								class="flex items-center gap-2 rounded-md border px-3 py-2 text-sm
								{stage.status === 'done'
									? 'bg-emerald-500/10 border-emerald-500/30'
									: stage.status === 'running'
										? 'bg-primary/10 border-primary/30'
										: stage.status === 'error'
											? 'bg-destructive/10 border-destructive/30'
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
								{:else if stage.status === 'error'}
									<AlertCircle class="h-4 w-4 text-destructive shrink-0" />
								{:else}
									<div class="h-4 w-4 shrink-0 rounded-full border-2 border-muted-foreground/30"></div>
								{/if}
								<span
									class="font-medium
									{stage.status === 'done'
										? 'text-emerald-700'
										: stage.status === 'running'
											? 'text-primary'
											: stage.status === 'error'
												? 'text-destructive'
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
											: stage.status === 'error'
												? 'bg-destructive/20 text-destructive'
												: 'bg-muted text-muted-foreground'}"
								>
									{getStatusLabel(stage.status)}
								</span>
							</div>
							<!-- 진행률 상세 (running 또는 done일 때) -->
							{#if stage.id !== 'review' && (stage.status === 'running' || stage.status === 'done')}
								{@const progressText = getStageProgressText(stage.id)}
								{@const currentItem = getStageCurrentItem(stage.id)}
								{@const eta = getStageEta(stage.id)}
								{@const pct = getStageProgressPercent(stage.id)}
								<div class="mt-1.5 w-full px-1 space-y-0.5">
									<!-- 프로그레스바 -->
									<div class="h-1.5 w-full rounded-full bg-muted overflow-hidden">
										<div
											class="h-full rounded-full transition-all duration-500
											{stage.status === 'done' ? 'bg-emerald-500' : 'bg-primary'}"
											style="width: {pct}%"
										></div>
									</div>
									<!-- 진행 텍스트 -->
									{#if progressText}
										<div class="flex items-center justify-between text-[10px] text-muted-foreground">
											<span>{progressText}</span>
											{#if eta}
												<span class="flex items-center gap-0.5">
													<Timer class="h-2.5 w-2.5" />
													{eta}
												</span>
											{/if}
										</div>
									{/if}
									<!-- 현재 처리 항목 -->
									{#if currentItem}
										<div class="text-[10px] text-muted-foreground/70 truncate" title={getStageDetail(stage.id)?.current_item ?? ''}>
											{currentItem}
										</div>
									{/if}
								</div>
							{/if}
						</div>
						{#if i < pipelineStages.length - 1}
							<div class="flex items-center px-2 text-muted-foreground self-start mt-2.5">
								<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
								</svg>
							</div>
						{/if}
					{/each}
				</div>
			</div>
		</div>

		<!-- 파이프라인 로그 패널 (실행 중이거나 로그가 있을 때) -->
		{#if pipelineRunning || mergedLogs.length > 0}
			<div class="rounded-lg border bg-card">
				<button
					onclick={() => (logPanelExpanded = !logPanelExpanded)}
					class="flex w-full items-center justify-between px-5 py-3 text-sm font-semibold hover:bg-accent/50 transition-colors"
				>
					<div class="flex items-center gap-2">
						<Terminal class="h-4 w-4 text-muted-foreground" />
						<span>파이프라인 로그</span>
						{#if mergedLogs.length > 0}
							<span class="text-xs text-muted-foreground font-normal">
								({mergedLogs.length}건)
							</span>
						{/if}
					</div>
					{#if logPanelExpanded}
						<ChevronUp class="h-4 w-4 text-muted-foreground" />
					{:else}
						<ChevronDown class="h-4 w-4 text-muted-foreground" />
					{/if}
				</button>
				{#if logPanelExpanded}
					<div class="border-t px-5 py-3 max-h-[200px] overflow-y-auto">
						<div class="space-y-1 font-mono text-xs">
							{#each mergedLogs as log}
								{@const isError = /^\d{3}\s/.test(log.message)}
								{@const stageColor = isError
									? 'text-red-500'
									: log.stage === 'scan'
										? 'text-blue-500'
										: log.stage === 'thumbnail'
											? 'text-violet-500'
											: log.stage === 'duplicate'
												? 'text-amber-500'
												: 'text-emerald-500'}
								<div class="flex gap-2 {isError ? 'bg-red-500/10 rounded px-1 -mx-1' : ''}">
									<span class="text-muted-foreground/50 shrink-0">
										{log.timestamp?.slice(11, 19) ?? ''}
									</span>
									<span class="{stageColor} shrink-0 w-16">[{log.stage}]</span>
									<span class="{isError ? 'text-red-400' : 'text-foreground/80'}">{log.message}</span>
								</div>
							{/each}
							{#if mergedLogs.length === 0}
								<p class="text-muted-foreground text-center py-2">로그 없음</p>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		{/if}

		<!-- 하단 3열 -->
		<div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
			<!-- Quick Actions -->
			<div class="rounded-lg border bg-card p-5 col-span-1">
				<h3 class="text-sm font-semibold mb-4">빠른 실행</h3>
				<div class="space-y-2">
					{#if pipelineRunning}
						<button
							onclick={stopPipeline}
							class="w-full inline-flex items-center justify-center gap-2 rounded-md bg-destructive px-3 py-2.5 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 transition-colors"
						>
							<Loader2 class="h-4 w-4 animate-spin" />
							파이프라인 중지
						</button>
					{:else}
						<button
							onclick={startFullPipeline}
							disabled={classifyRunning || duplicateRunning}
							class="w-full inline-flex items-center justify-center gap-2 rounded-md bg-primary px-3 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
						>
							<Play class="h-4 w-4" />
							전체 파이프라인 시작
						</button>
					{/if}
					<button
						onclick={startClassification}
						disabled={classifyRunning || pipelineRunning}
						class="w-full inline-flex items-center justify-center gap-2 rounded-md border bg-background px-3 py-2.5 text-sm font-medium hover:bg-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					>
						{#if classifyRunning}
							<Loader2 class="h-4 w-4 animate-spin" />
						{:else}
							<Brain class="h-4 w-4" />
						{/if}
						AI 분류 시작
					</button>
					<button
						onclick={startDuplicateDetect}
						disabled={duplicateRunning || pipelineRunning}
						class="w-full inline-flex items-center justify-center gap-2 rounded-md border bg-background px-3 py-2.5 text-sm font-medium hover:bg-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
					>
						{#if duplicateRunning}
							<Loader2 class="h-4 w-4 animate-spin" />
						{:else}
							<Database class="h-4 w-4" />
						{/if}
						중복 이미지 찾기
					</button>
				</div>

				{#if health}
					<div class="mt-4 pt-4 border-t space-y-2 text-xs text-muted-foreground">
						<div class="flex justify-between">
							<span>상태</span>
							<span class="font-medium text-foreground">{health.status}</span>
						</div>
						<div class="flex justify-between">
							<span>데이터베이스</span>
							<span class="font-medium text-foreground">{health.database}</span>
						</div>
						<div class="flex justify-between">
							<span>AI 모드</span>
							<span class="font-medium text-foreground">{health.ai_adapters?.mode ?? '—'}</span>
						</div>
					</div>
				{/if}
			</div>

			<!-- Recent Activity -->
			<div class="rounded-lg border bg-card p-5 col-span-2">
				<div class="flex items-center justify-between mb-4">
					<h3 class="text-sm font-semibold">최근 활동</h3>
					<div class="flex items-center gap-1">
						<Filter class="h-3.5 w-3.5 text-muted-foreground" />
						{#each [{ key: 'all', label: '전체' }, { key: 'info', label: '정보' }, { key: 'error', label: '오류' }] as f}
							<button
								onclick={() => (activityFilter = f.key)}
								class="px-2 py-1 rounded text-xs font-medium transition-colors
								{activityFilter === f.key
									? 'bg-primary text-primary-foreground'
									: 'bg-muted text-muted-foreground hover:bg-accent'}"
							>
								{f.label}
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
						<p class="text-sm text-muted-foreground py-4 text-center">활동 없음</p>
					{/each}
				</div>
			</div>
		</div>

		<!-- Classification Distribution -->
		<div class="rounded-lg border bg-card p-5">
			<h3 class="text-sm font-semibold mb-4">분류 현황</h3>
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
