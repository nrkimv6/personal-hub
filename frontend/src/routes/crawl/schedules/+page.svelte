<script lang="ts">
	import { onMount } from 'svelte';
	import { crawlApi } from '$lib/api';
	import type { CrawlSchedule, CrawlRunStats } from '$lib/types';

	let schedules: CrawlSchedule[] = [];
	let loading = true;
	let error: string | null = null;
	let statsMap: Map<number, CrawlRunStats> = new Map();

	// 필터
	let targetType: string = '';
	let enabledOnly: boolean = false;

	async function fetchSchedules() {
		try {
			loading = true;
			schedules = await crawlApi.getSchedules({
				target_type: targetType || undefined,
				enabled_only: enabledOnly
			});
			error = null;

			// 각 스케줄의 통계 로드
			for (const schedule of schedules) {
				try {
					const stats = await crawlApi.getScheduleStats(schedule.id, 7);
					statsMap.set(schedule.id, stats);
				} catch {
					// 통계 로드 실패 시 무시
				}
			}
			statsMap = statsMap; // 반응성 트리거
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

	function formatDateTime(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
				year: 'numeric',
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

	onMount(() => {
		fetchSchedules();
	});
</script>

<div class="p-6 max-w-7xl mx-auto">
	<div class="mb-6">
		<h2 class="text-2xl font-bold text-foreground">크롤링 스케줄</h2>
		<p class="text-sm text-muted-foreground mt-1">정기 크롤링 스케줄 관리</p>
	</div>

	<!-- 필터 -->
	<div class="card mb-6">
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
		<div class="card text-center py-12">
			<p class="text-muted-foreground">스케줄이 없습니다</p>
		</div>
	{:else}
		<div class="grid gap-4">
			{#each schedules as schedule}
				{@const stats = statsMap.get(schedule.id)}
				<div class="card">
					<div class="flex justify-between items-start">
						<div class="flex-1">
							<div class="flex items-center gap-3 mb-2">
								<h3 class="text-lg font-semibold text-foreground">
									{schedule.display_name || schedule.name}
								</h3>
								<span class="px-2 py-1 text-xs rounded-full {schedule.enabled ? 'bg-success-light text-success' : 'bg-muted text-muted-foreground'}">
									{schedule.enabled ? '활성' : '비활성'}
								</span>
							</div>
							<div class="flex flex-wrap gap-4 text-sm text-muted-foreground">
								<span>대상: {getTargetTypeLabel(schedule.target_type)}</span>
								<span>주기: {getScheduleTypeLabel(schedule.schedule_type)}</span>
								{#if schedule.last_run_at}
									<span>마지막 실행: {formatDateTime(schedule.last_run_at)}</span>
								{/if}
								{#if schedule.next_run_at}
									<span>다음 실행: {formatDateTime(schedule.next_run_at)}</span>
								{/if}
							</div>

							{#if stats}
								<div class="mt-3 flex gap-6 text-sm">
									<span class="text-muted-foreground">
										7일 통계:
										<span class="font-medium text-foreground">{stats.total_runs}</span>회 실행,
										<span class="font-medium text-success">{stats.success_rate.toFixed(0)}%</span> 성공률,
										<span class="font-medium text-primary">{stats.total_saved}</span>건 저장
									</span>
								</div>
							{/if}
						</div>

						<div class="flex gap-2">
							<a
								href="/crawl/schedules/{schedule.id}/runs"
								class="btn btn-secondary btn-sm"
							>
								실행 이력
							</a>
							<button
								onclick={() => handleToggle(schedule.id, !schedule.enabled)}
								class="btn btn-sm {schedule.enabled ? 'btn-danger' : 'btn-primary'}"
							>
								{schedule.enabled ? '비활성화' : '활성화'}
							</Button>
						</div>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
