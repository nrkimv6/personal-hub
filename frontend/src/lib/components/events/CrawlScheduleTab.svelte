<script lang="ts">
	import { Button } from '$lib/components/ui';

	/**
	 * 스케줄 크롤링 탭 컴포넌트
	 * 정기 크롤링 스케줄 관리
	 */
	import { onMount } from 'svelte';
	import { crawlApi } from '$lib/api';
	import type { CrawlSchedule, CrawlRunStats, CrawlScheduleRun } from '$lib/types';
	import { isAdmin } from '$lib/stores/auth';

	// Props
	interface Props {
		onTotalChange?: (total: number) => void;
	}

	let { onTotalChange }: Props = $props();

	let schedules: CrawlSchedule[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let statsMap: Map<number, CrawlRunStats> = $state(new Map());

	// 필터
	let targetType = $state('');
	let enabledOnly = $state(false);

	// 실행 이력 모달
	let showRunsModal = $state(false);
	let selectedSchedule: CrawlSchedule | null = $state(null);
	let runs: CrawlScheduleRun[] = $state([]);
	let loadingRuns = $state(false);

	$effect(() => {
		onTotalChange?.(schedules.length);
	});

	export async function fetchSchedules() {
		try {
			loading = true;
			schedules = await crawlApi.getSchedules({
				target_type: targetType || undefined,
				enabled_only: enabledOnly
			});
			error = null;

			// 각 스케줄의 통계 로드
			const newStatsMap = new Map<number, CrawlRunStats>();
			for (const schedule of schedules) {
				try {
					const stats = await crawlApi.getScheduleStats(schedule.id, 7);
					newStatsMap.set(schedule.id, stats);
				} catch {
					// 통계 로드 실패 시 무시
				}
			}
			statsMap = newStatsMap;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	function handleFilterChange() {
		fetchSchedules();
	}

	async function handleToggle(scheduleId: number, enabled: boolean) {
		try {
			await crawlApi.toggleSchedule(scheduleId, enabled);
			fetchSchedules();
		} catch (e) {
			error = e instanceof Error ? e.message : '토글 실패';
		}
	}

	async function openRunsModal(schedule: CrawlSchedule) {
		selectedSchedule = schedule;
		showRunsModal = true;
		loadingRuns = true;
		runs = [];

		try {
			const response = await crawlApi.getScheduleRuns(schedule.id, { page: 1, limit: 20 });
			runs = response.items;
		} catch (e) {
			console.error('실행 이력 로드 실패:', e);
		} finally {
			loadingRuns = false;
		}
	}

	function formatDateTime(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function getTargetTypeLabel(type: string): string {
		switch (type) {
			case 'instagram_feed': return 'Instagram 피드';
			case 'naver_blog': return '네이버 블로그';
			case 'google_search': return 'Google 검색';
			default: return type;
		}
	}

	function getScheduleTypeLabel(type: string): string {
		switch (type) {
			case 'cron': return 'Cron';
			case 'interval': return '간격';
			case 'time_window': return '시간대';
			case 'manual': return '수동';
			default: return type;
		}
	}

	function getStatusBadge(status: string) {
		switch (status) {
			case 'pending': return 'bg-warning-light text-warning-foreground';
			case 'running': return 'bg-primary-light text-primary';
			case 'completed': return 'bg-success-light text-success';
			case 'failed': return 'bg-error-light text-error';
			default: return 'bg-muted text-foreground';
		}
	}

	function getStatusText(status: string) {
		switch (status) {
			case 'pending': return '대기';
			case 'running': return '실행 중';
			case 'completed': return '완료';
			case 'failed': return '실패';
			default: return status;
		}
	}

	onMount(() => {
		fetchSchedules();
	});
</script>

<!-- 필터 -->
<div class="mb-4 space-y-2">
	<div class="flex flex-wrap gap-4 items-center">
		<div>
			<label for="targetType" class="block text-sm font-medium text-foreground mb-1">대상 타입</label>
			<select
				id="targetType"
				bind:value={targetType}
				onchange={handleFilterChange}
				class="input input-sm w-44"
			>
				<option value="">전체</option>
				<option value="instagram_feed">Instagram 피드</option>
				<option value="naver_blog">네이버 블로그</option>
				<option value="google_search">Google 검색</option>
			</select>
		</div>
		<div class="flex items-center gap-2 mt-5">
			<input
				type="checkbox"
				id="enabledOnly"
				bind:checked={enabledOnly}
				onchange={handleFilterChange}
				class="rounded border-border"
			/>
			<label for="enabledOnly" class="text-sm text-foreground">활성화된 것만</label>
		</div>
	</div>
</div>

<!-- 스케줄 목록 -->
{#if loading}
	<div class="flex justify-center items-center h-64">
		<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
	</div>
{:else if error}
	<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">
		{error}
	</div>
{:else if !schedules || schedules.length === 0}
	<div class="text-center py-12 text-muted-foreground">
		<p class="text-lg">스케줄이 없습니다</p>
	</div>
{:else}
	<!-- 모바일 카드 뷰 -->
	<div class="md:hidden space-y-3">
		{#each schedules as schedule}
			{@const stats = statsMap.get(schedule.id)}
			<div class="bg-card border rounded-lg p-4">
				<div class="flex items-center justify-between mb-2">
					<h3 class="font-semibold text-foreground truncate flex-1">
						{schedule.display_name || schedule.name}
					</h3>
					<span class="px-2 py-0.5 text-xs rounded-full {schedule.enabled ? 'bg-success-light text-success' : 'bg-muted text-muted-foreground'}">
						{schedule.enabled ? '활성' : '비활성'}
					</span>
				</div>
				<div class="text-sm text-muted-foreground space-y-1">
					<div class="flex gap-2">
						<span class="px-2 py-0.5 text-xs rounded bg-muted">{getTargetTypeLabel(schedule.target_type)}</span>
						<span class="px-2 py-0.5 text-xs rounded bg-muted">{getScheduleTypeLabel(schedule.schedule_type)}</span>
					</div>
					{#if schedule.last_run_at}
						<p class="text-xs">마지막: {formatDateTime(schedule.last_run_at)}</p>
					{/if}
					{#if stats}
						<p class="text-xs">
							7일: {stats.total_runs}회,
							<span class="text-success">{stats.success_rate.toFixed(0)}%</span> 성공,
							<span class="text-primary">{stats.total_saved}</span>건
						</p>
					{/if}
				</div>
				<div class="mt-3 flex gap-2">
					<Button variant="secondary" size="sm" on:click={() => openRunsModal(schedule)}
					>
						실행 이력
					</Button>
					{#if $isAdmin}
						<Button
							variant={schedule.enabled ? 'destructive' : 'primary'}
							size="sm"
							on:click={() => handleToggle(schedule.id, !schedule.enabled)}
						>
							{schedule.enabled ? '비활성화' : '활성화'}
						</Button>
					{/if}
				</div>
			</div>
		{/each}
	</div>

	<!-- 데스크톱 테이블 뷰 -->
	<div class="hidden md:block overflow-x-auto">
		<table class="w-full">
			<thead>
				<tr class="border-b text-left text-sm text-muted-foreground">
					<th class="pb-3 font-medium">스케줄</th>
					<th class="pb-3 font-medium">대상</th>
					<th class="pb-3 font-medium">주기</th>
					<th class="pb-3 font-medium">상태</th>
					<th class="pb-3 font-medium">마지막 실행</th>
					<th class="pb-3 font-medium">7일 통계</th>
					<th class="pb-3 font-medium"></th>
				</tr>
			</thead>
			<tbody>
				{#each schedules as schedule}
					{@const stats = statsMap.get(schedule.id)}
					<tr class="border-b hover:bg-muted">
						<td class="py-3">
							<span class="font-medium text-foreground">{schedule.display_name || schedule.name}</span>
						</td>
						<td class="py-3">
							<span class="px-2 py-1 text-xs rounded bg-muted">{getTargetTypeLabel(schedule.target_type)}</span>
						</td>
						<td class="py-3 text-sm text-muted-foreground">
							{getScheduleTypeLabel(schedule.schedule_type)}
						</td>
						<td class="py-3">
							<span class="px-2 py-1 text-xs rounded-full {schedule.enabled ? 'bg-success-light text-success' : 'bg-muted text-muted-foreground'}">
								{schedule.enabled ? '활성' : '비활성'}
							</span>
						</td>
						<td class="py-3 text-sm text-muted-foreground">
							{formatDateTime(schedule.last_run_at)}
						</td>
						<td class="py-3 text-sm">
							{#if stats}
								<span class="text-muted-foreground">{stats.total_runs}회</span>
								<span class="text-success ml-1">{stats.success_rate.toFixed(0)}%</span>
								<span class="text-primary ml-1">{stats.total_saved}건</span>
							{:else}
								<span class="text-muted-foreground">-</span>
							{/if}
						</td>
						<td class="py-3">
							<div class="flex gap-2">
								<button
									onclick={() => openRunsModal(schedule)}
									class="text-sm text-primary hover:underline"
								>
									실행 이력
								</button>
								{#if $isAdmin}
									<button
										onclick={() => handleToggle(schedule.id, !schedule.enabled)}
										class="text-sm {schedule.enabled ? 'text-error' : 'text-success'} hover:underline"
									>
										{schedule.enabled ? '비활성화' : '활성화'}
									</button>
								{/if}
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<!-- 실행 이력 모달 -->
{#if showRunsModal && selectedSchedule}
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={() => (showRunsModal = false)}
		onkeydown={(e) => e.key === 'Escape' && (showRunsModal = false)}
		role="dialog"
		tabindex="-1"
	>
		<div
			class="bg-white rounded-xl w-full max-w-3xl max-h-[90dvh] overflow-auto p-6"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="flex justify-between items-center mb-4">
				<div>
					<h3 class="text-lg font-bold">실행 이력</h3>
					<p class="text-sm text-muted-foreground">{selectedSchedule.display_name || selectedSchedule.name}</p>
				</div>
				<button onclick={() => (showRunsModal = false)} class="text-muted-foreground hover:text-muted-foreground text-2xl">
					&times;
				</button>
			</div>

			{#if loadingRuns}
				<div class="flex justify-center py-8">
					<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
				</div>
			{:else if runs.length === 0}
				<div class="text-center py-8 text-muted-foreground">
					실행 이력이 없습니다
				</div>
			{:else}
				<div class="space-y-2">
					{#each runs as run}
						<div class="border rounded-lg p-3 {run.status === 'failed' ? 'border-red-200 bg-error-light' : ''}">
							<div class="flex items-center justify-between">
								<div class="flex items-center gap-2">
									<span class="px-2 py-0.5 text-xs rounded-full {getStatusBadge(run.status)}">
										{getStatusText(run.status)}
									</span>
									<span class="text-sm text-muted-foreground">{formatDateTime(run.started_at)}</span>
								</div>
								<div class="text-sm">
									<span class="text-muted-foreground">발견: {run.collected_count}</span>
									<span class="text-primary ml-2">저장: {run.saved_count}</span>
								</div>
							</div>
							{#if run.error_message}
								<p class="mt-2 text-sm text-error bg-error-light rounded p-2">
									{run.error_message}
								</p>
							{/if}
						</div>
					{/each}
				</div>
			{/if}

			<div class="mt-6 flex justify-end">
				<Button variant="secondary" size="sm" on:click={() => (showRunsModal = false)}>닫기</Button>
			</div>
		</div>
	</div>
{/if}
