<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { llmApi, type LLMPerformanceStats, type LLMWorkerStatus } from '$lib/api';
	import Chart from 'chart.js/auto';

	// 상태
	let stats: LLMPerformanceStats | null = null;
	let workerStatus: LLMWorkerStatus | null = null;
	let loading = true;
	let error: string | null = null;

	// 기간 선택
	let hours = 24;
	const hourOptions = [
		{ value: 6, label: '6시간' },
		{ value: 12, label: '12시간' },
		{ value: 24, label: '24시간' },
		{ value: 48, label: '2일' },
		{ value: 168, label: '7일' }
	];

	// 차트 참조
	let chartCanvas: HTMLCanvasElement;
	let chartInstance: Chart | null = null;

	export async function fetchData() {
		loading = true;
		error = null;
		try {
			const [perfStats, worker] = await Promise.all([
				llmApi.getPerformanceStats(hours),
				llmApi.getWorkerStatus()
			]);
			stats = perfStats;
			workerStatus = worker;
			updateChart();
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	function updateChart() {
		if (!stats || !chartCanvas) return;

		if (chartInstance) {
			chartInstance.destroy();
		}

		const ctx = chartCanvas.getContext('2d');
		if (!ctx) return;

		chartInstance = new Chart(ctx, {
			type: 'bar',
			data: {
				labels: stats.by_hour.map((h) => h.hour),
				datasets: [
					{
						label: '요청 수',
						data: stats.by_hour.map((h) => h.count),
						backgroundColor: 'rgba(59, 130, 246, 0.5)',
						borderColor: 'rgb(59, 130, 246)',
						borderWidth: 1,
						yAxisID: 'y'
					},
					{
						label: '평균 처리 시간 (초)',
						data: stats.by_hour.map((h) => h.avg_time),
						type: 'line',
						borderColor: 'rgb(239, 68, 68)',
						backgroundColor: 'rgba(239, 68, 68, 0.1)',
						borderWidth: 2,
						fill: false,
						yAxisID: 'y1'
					}
				]
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				interaction: {
					mode: 'index',
					intersect: false
				},
				scales: {
					y: {
						type: 'linear',
						display: true,
						position: 'left',
						title: {
							display: true,
							text: '요청 수'
						}
					},
					y1: {
						type: 'linear',
						display: true,
						position: 'right',
						title: {
							display: true,
							text: '처리 시간 (초)'
						},
						grid: {
							drawOnChartArea: false
						}
					}
				}
			}
		});
	}

	function formatTime(seconds: number): string {
		if (seconds < 60) {
			return `${seconds.toFixed(1)}초`;
		}
		const minutes = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${minutes}분 ${secs.toFixed(0)}초`;
	}

	function formatDateTime(isoString: string): string {
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function handlePeriodChange() {
		fetchData();
	}

	onMount(() => {
		fetchData();
	});

	onDestroy(() => {
		if (chartInstance) {
			chartInstance.destroy();
		}
	});
</script>

<div>
	<!-- 기간 선택 헤더 -->
	<div class="mb-6 flex justify-between items-center">
		<div>
			<p class="text-sm text-muted-foreground">LLM 처리 시간 및 파이프라인 성능 분석</p>
		</div>
		<div class="flex gap-3 items-center">
			<select
				bind:value={hours}
				onchange={handlePeriodChange}
				class="px-3 py-2 border border-border rounded-lg text-sm"
			>
				{#each hourOptions as opt}
					<option value={opt.value}>{opt.label}</option>
				{/each}
			</select>
			<button onclick={() => fetchData()} class="btn btn-secondary btn-sm">새로고침</button>
		</div>
	</div>

	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">{error}</div>
	{:else if stats}
		<!-- 요약 카드 -->
		<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-6">
			<!-- 워커 상태 -->
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">워커 상태</div>
				<div
					class="text-lg font-bold {workerStatus?.status === 'healthy'
						? 'text-green-600'
						: workerStatus?.status === 'warning'
							? 'text-yellow-600'
							: workerStatus?.status === 'no_worker'
								? 'text-muted-foreground'
								: 'text-red-600'}"
				>
					{workerStatus?.status === 'healthy'
						? '정상'
						: workerStatus?.status === 'warning'
							? '지연'
							: workerStatus?.status === 'no_worker'
								? '없음'
								: '비정상'}
				</div>
				{#if workerStatus?.state}
					<div class="text-xs text-muted-foreground">{workerStatus.state}</div>
				{/if}
				{#if workerStatus?.message && workerStatus?.status !== 'healthy'}
					<div class="text-xs text-muted-foreground">{workerStatus.message}</div>
				{/if}
			</div>

			<!-- 총 요청 -->
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">총 요청</div>
				<div class="text-2xl font-bold text-foreground">{stats.llm_stats.total_requests}</div>
				<div class="text-xs text-muted-foreground">최근 {hours}시간</div>
			</div>

			<!-- 실패 -->
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">실패</div>
				<div class="text-2xl font-bold text-red-600">{stats.llm_stats.failed_count}</div>
			</div>

			<!-- 평균 처리 시간 -->
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">평균 처리 시간</div>
				<div class="text-2xl font-bold text-blue-600">
					{formatTime(stats.llm_stats.avg_processing_time)}
				</div>
			</div>

			<!-- P50 -->
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">P50</div>
				<div class="text-2xl font-bold text-green-600">{formatTime(stats.llm_stats.p50)}</div>
			</div>

			<!-- P95 -->
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">P95</div>
				<div class="text-2xl font-bold text-orange-600">{formatTime(stats.llm_stats.p95)}</div>
			</div>
		</div>

		<!-- 처리 시간 범위 -->
		<div class="card p-4 mb-6">
			<h3 class="text-lg font-bold text-foreground mb-3">처리 시간 분포</h3>
			<div class="flex items-center gap-8">
				<div class="flex items-center gap-2">
					<span class="text-sm text-muted-foreground">최소:</span>
					<span class="font-medium">{formatTime(stats.llm_stats.min_time)}</span>
				</div>
				<div class="flex-1 h-2 bg-secondary rounded-full relative">
					<div
						class="absolute inset-y-0 left-0 bg-blue-500 rounded-full"
						style="width: {stats.llm_stats.max_time > 0
							? (stats.llm_stats.avg_processing_time / stats.llm_stats.max_time) * 100
							: 0}%"
					></div>
				</div>
				<div class="flex items-center gap-2">
					<span class="text-sm text-muted-foreground">최대:</span>
					<span class="font-medium">{formatTime(stats.llm_stats.max_time)}</span>
				</div>
			</div>
		</div>

		<!-- 시간대별 차트 -->
		<div class="card p-4 mb-6">
			<h3 class="text-lg font-bold text-foreground mb-3">시간대별 분포</h3>
			<div class="h-64">
				<canvas bind:this={chartCanvas}></canvas>
			</div>
		</div>

		<!-- 느린 요청 목록 -->
		{#if stats.slow_requests.length > 0}
			<div class="card p-4">
				<h3 class="text-lg font-bold text-foreground mb-3">느린 요청 (상위 10개)</h3>
				<div class="overflow-x-auto">
					<table class="w-full">
						<thead class="bg-background border-b border-border">
							<tr>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">ID</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">타입</th>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
									>호출자 ID</th
								>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
									>처리 시간</th
								>
								<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase"
									>요청 시간</th
								>
							</tr>
						</thead>
						<tbody class="divide-y divide-border">
							{#each stats.slow_requests as req}
								<tr class="hover:bg-muted">
									<td class="px-4 py-3 text-sm text-foreground">{req.id}</td>
									<td class="px-4 py-3 text-sm text-muted-foreground">{req.caller_type}</td>
									<td class="px-4 py-3 text-sm text-muted-foreground">{req.caller_id}</td>
									<td class="px-4 py-3">
										<span
											class="px-2 py-1 text-xs rounded-full {req.processing_time > 60
												? 'bg-red-100 text-red-800'
												: 'bg-yellow-100 text-yellow-800'}"
										>
											{formatTime(req.processing_time)}
										</span>
									</td>
									<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(req.requested_at)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		{:else}
			<div class="card p-4 text-center text-muted-foreground">
				<p>분석 기간 내 완료된 요청이 없습니다.</p>
			</div>
		{/if}
	{/if}
</div>
