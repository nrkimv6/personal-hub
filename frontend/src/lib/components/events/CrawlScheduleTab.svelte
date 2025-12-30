<script lang="ts">
	/**
	 * 스케줄 크롤링 탭 컴포넌트
	 * 정기 크롤링 스케줄 관리
	 */
	import { onMount } from 'svelte';
	import { crawlApi } from '$lib/api';
	import type { CrawlSchedule, CrawlRunStats } from '$lib/types';
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
	let runs: Array<{
		id: number;
		status: string;
		started_at: string;
		completed_at: string | null;
		items_found: number;
		items_saved: number;
		error_message: string | null;
	}> = $state([]);
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
			const response = await crawlApi.getScheduleRuns(schedule.id, { page: 1, page_size: 20 });
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
			case 'pending': return 'bg-yellow-100 text-yellow-800';
			case 'running': return 'bg-blue-100 text-blue-800';
			case 'completed': return 'bg-green-100 text-green-800';
			case 'failed': return 'bg-red-100 text-red-800';
			default: return 'bg-gray-100 text-gray-800';
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
			<label for="targetType" class="block text-sm font-medium text-gray-700 mb-1">대상 타입</label>
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
				class="rounded border-gray-300"
			/>
			<label for="enabledOnly" class="text-sm text-gray-700">활성화된 것만</label>
		</div>
	</div>
</div>

<!-- 스케줄 목록 -->
{#if loading}
	<div class="flex justify-center items-center h-64">
		<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
	</div>
{:else if error}
	<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
		{error}
	</div>
{:else if !schedules || schedules.length === 0}
	<div class="text-center py-12 text-gray-500">
		<p class="text-lg">스케줄이 없습니다</p>
	</div>
{:else}
	<!-- 모바일 카드 뷰 -->
	<div class="md:hidden space-y-3">
		{#each schedules as schedule}
			{@const stats = statsMap.get(schedule.id)}
			<div class="bg-white border rounded-lg p-4">
				<div class="flex items-center justify-between mb-2">
					<h3 class="font-semibold text-gray-900 truncate flex-1">
						{schedule.display_name || schedule.name}
					</h3>
					<span class="px-2 py-0.5 text-xs rounded-full {schedule.enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}">
						{schedule.enabled ? '활성' : '비활성'}
					</span>
				</div>
				<div class="text-sm text-gray-600 space-y-1">
					<div class="flex gap-2">
						<span class="px-2 py-0.5 text-xs rounded bg-gray-100">{getTargetTypeLabel(schedule.target_type)}</span>
						<span class="px-2 py-0.5 text-xs rounded bg-gray-100">{getScheduleTypeLabel(schedule.schedule_type)}</span>
					</div>
					{#if schedule.last_run_at}
						<p class="text-xs">마지막: {formatDateTime(schedule.last_run_at)}</p>
					{/if}
					{#if stats}
						<p class="text-xs">
							7일: {stats.total_runs}회,
							<span class="text-green-600">{stats.success_rate.toFixed(0)}%</span> 성공,
							<span class="text-blue-600">{stats.total_saved}</span>건
						</p>
					{/if}
				</div>
				<div class="mt-3 flex gap-2">
					<button
						onclick={() => openRunsModal(schedule)}
						class="btn btn-secondary btn-sm flex-1"
					>
						실행 이력
					</button>
					{#if $isAdmin}
						<button
							onclick={() => handleToggle(schedule.id, !schedule.enabled)}
							class="btn btn-sm {schedule.enabled ? 'btn-danger' : 'btn-primary'}"
						>
							{schedule.enabled ? '비활성화' : '활성화'}
						</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>

	<!-- 데스크톱 테이블 뷰 -->
	<div class="hidden md:block overflow-x-auto">
		<table class="w-full">
			<thead>
				<tr class="border-b text-left text-sm text-gray-600">
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
					<tr class="border-b hover:bg-gray-50">
						<td class="py-3">
							<span class="font-medium text-gray-900">{schedule.display_name || schedule.name}</span>
						</td>
						<td class="py-3">
							<span class="px-2 py-1 text-xs rounded bg-gray-100">{getTargetTypeLabel(schedule.target_type)}</span>
						</td>
						<td class="py-3 text-sm text-gray-600">
							{getScheduleTypeLabel(schedule.schedule_type)}
						</td>
						<td class="py-3">
							<span class="px-2 py-1 text-xs rounded-full {schedule.enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}">
								{schedule.enabled ? '활성' : '비활성'}
							</span>
						</td>
						<td class="py-3 text-sm text-gray-600">
							{formatDateTime(schedule.last_run_at)}
						</td>
						<td class="py-3 text-sm">
							{#if stats}
								<span class="text-gray-600">{stats.total_runs}회</span>
								<span class="text-green-600 ml-1">{stats.success_rate.toFixed(0)}%</span>
								<span class="text-blue-600 ml-1">{stats.total_saved}건</span>
							{:else}
								<span class="text-gray-400">-</span>
							{/if}
						</td>
						<td class="py-3">
							<div class="flex gap-2">
								<button
									onclick={() => openRunsModal(schedule)}
									class="text-sm text-blue-600 hover:underline"
								>
									실행 이력
								</button>
								{#if $isAdmin}
									<button
										onclick={() => handleToggle(schedule.id, !schedule.enabled)}
										class="text-sm {schedule.enabled ? 'text-red-600' : 'text-green-600'} hover:underline"
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
			class="bg-white rounded-xl w-full max-w-3xl max-h-[90vh] overflow-auto p-6"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="flex justify-between items-center mb-4">
				<div>
					<h3 class="text-lg font-bold">실행 이력</h3>
					<p class="text-sm text-gray-500">{selectedSchedule.display_name || selectedSchedule.name}</p>
				</div>
				<button onclick={() => (showRunsModal = false)} class="text-gray-400 hover:text-gray-600 text-2xl">
					&times;
				</button>
			</div>

			{#if loadingRuns}
				<div class="flex justify-center py-8">
					<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
				</div>
			{:else if runs.length === 0}
				<div class="text-center py-8 text-gray-500">
					실행 이력이 없습니다
				</div>
			{:else}
				<div class="space-y-2">
					{#each runs as run}
						<div class="border rounded-lg p-3 {run.status === 'failed' ? 'border-red-200 bg-red-50' : ''}">
							<div class="flex items-center justify-between">
								<div class="flex items-center gap-2">
									<span class="px-2 py-0.5 text-xs rounded-full {getStatusBadge(run.status)}">
										{getStatusText(run.status)}
									</span>
									<span class="text-sm text-gray-600">{formatDateTime(run.started_at)}</span>
								</div>
								<div class="text-sm">
									<span class="text-gray-600">발견: {run.items_found}</span>
									<span class="text-blue-600 ml-2">저장: {run.items_saved}</span>
								</div>
							</div>
							{#if run.error_message}
								<p class="mt-2 text-sm text-red-600 bg-red-100 rounded p-2">
									{run.error_message}
								</p>
							{/if}
						</div>
					{/each}
				</div>
			{/if}

			<div class="mt-6 flex justify-end">
				<button onclick={() => (showRunsModal = false)} class="btn btn-secondary btn-sm">닫기</button>
			</div>
		</div>
	</div>
{/if}
