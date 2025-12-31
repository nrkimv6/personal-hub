<script lang="ts">
	import { onMount } from 'svelte';
	import { collectApi } from '$lib/api';
	import type { CrawlSchedule } from '$lib/types';
	import InstagramCrawlSettings from '$lib/components/InstagramCrawlSettings.svelte';

	let schedules: CrawlSchedule[] = [];
	let loading = true;
	let error: string | null = null;
	let successMessage: string | null = null;

	let togglingId: number | null = null;
	let runningId: number | null = null;

	// 설정 모달 상태
	let showSettingsModal = false;
	let selectedSchedule: CrawlSchedule | null = null;
	let settingsRef: InstagramCrawlSettings | null = null;

	function openSettings(schedule: CrawlSchedule) {
		selectedSchedule = schedule;
		showSettingsModal = true;
	}

	function closeSettings() {
		showSettingsModal = false;
		selectedSchedule = null;
		// 설정 저장 후 목록 새로고침
		fetchSchedules();
	}

	async function fetchSchedules() {
		loading = true;
		error = null;
		try {
			schedules = await collectApi.getSchedules();
		} catch (e) {
			error = e instanceof Error ? e.message : '스케줄 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function toggleSchedule(schedule: CrawlSchedule) {
		togglingId = schedule.id;
		successMessage = null;
		error = null;
		try {
			const result = await collectApi.toggleSchedule(schedule.id, !schedule.enabled);
			if (result.success) {
				successMessage = `${schedule.display_name || schedule.name}: ${result.enabled ? '활성화' : '비활성화'}됨`;
				await fetchSchedules();
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '스케줄 토글 실패';
		} finally {
			togglingId = null;
		}
	}

	async function runSchedule(schedule: CrawlSchedule) {
		runningId = schedule.id;
		successMessage = null;
		error = null;
		try {
			const result = await collectApi.runSchedule(schedule.id);
			if (result.success) {
				successMessage = result.message;
			} else {
				error = result.message;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '즉시 실행 실패';
		} finally {
			runningId = null;
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

	function getTargetTypeBadge(type: string): { class: string; text: string } {
		switch (type) {
			case 'instagram_feed':
				return { class: 'bg-pink-100 text-pink-800', text: 'Instagram' };
			case 'universal_crawl':
				return { class: 'bg-blue-100 text-blue-800', text: 'Web' };
			case 'google_search':
				return { class: 'bg-yellow-100 text-yellow-800', text: 'Google' };
			default:
				return { class: 'bg-gray-100 text-gray-800', text: type };
		}
	}

	function getScheduleTypeBadge(type: string): { class: string; text: string } {
		switch (type) {
			case 'daily':
				return { class: 'bg-green-50 text-green-700', text: '일일' };
			case 'interval':
				return { class: 'bg-blue-50 text-blue-700', text: '간격' };
			case 'cron':
				return { class: 'bg-purple-50 text-purple-700', text: 'Cron' };
			case 'time_window':
				return { class: 'bg-orange-50 text-orange-700', text: '시간대' };
			default:
				return { class: 'bg-gray-50 text-gray-700', text: type };
		}
	}

	onMount(() => {
		fetchSchedules();
	});
</script>

<div>
	{#if successMessage}
		<div class="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg mb-4">
			{successMessage}
		</div>
	{/if}

	{#if error}
		<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
			{error}
		</div>
	{/if}

	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if schedules.length === 0}
		<div class="card text-center py-12">
			<p class="text-gray-500">등록된 스케줄이 없습니다</p>
		</div>
	{:else}
		<div class="space-y-4">
			{#each schedules as schedule}
				{@const targetBadge = getTargetTypeBadge(schedule.target_type)}
				{@const scheduleBadge = getScheduleTypeBadge(schedule.schedule_type)}
				<div class="card">
					<div class="flex items-center justify-between">
						<!-- 스케줄 정보 -->
						<div class="flex items-center gap-4">
							<!-- 활성화 토글 -->
							<button
								onclick={() => toggleSchedule(schedule)}
								disabled={togglingId === schedule.id}
								class="relative inline-flex items-center h-6 rounded-full w-11 transition-colors {schedule.enabled
									? 'bg-blue-600'
									: 'bg-gray-200'}"
							>
								<span
									class="inline-block w-4 h-4 transform bg-white rounded-full transition-transform {schedule.enabled
										? 'translate-x-6'
										: 'translate-x-1'}"
								></span>
							</button>

							<div>
								<div class="flex items-center gap-2">
									<span class="font-medium text-gray-900">
										{schedule.display_name || schedule.name}
									</span>
									<span class="px-2 py-0.5 text-xs rounded-full {targetBadge.class}">
										{targetBadge.text}
									</span>
									<span class="px-2 py-0.5 text-xs rounded-full {scheduleBadge.class}">
										{scheduleBadge.text}
									</span>
								</div>
								<div class="text-sm text-gray-500 mt-1 flex gap-4">
									<span>마지막 실행: {formatDateTime(schedule.last_run_at)}</span>
									{#if schedule.enabled && schedule.next_run_at}
										<span>다음 실행: {formatDateTime(schedule.next_run_at)}</span>
									{/if}
								</div>
							</div>
						</div>

						<!-- 버튼 그룹 -->
						<div class="flex items-center gap-2">
							<!-- 실행 이력 버튼 -->
							<a
								href="/crawl/schedules/{schedule.id}/runs"
								class="btn btn-secondary btn-sm"
								title="실행 이력 보기"
							>
								이력
							</a>

							<!-- 설정 버튼 (Instagram만) -->
							{#if schedule.target_type === 'instagram_feed'}
								<button
									onclick={() => openSettings(schedule)}
									class="btn btn-secondary btn-sm"
									title="상세 설정"
								>
									설정
								</button>
							{/if}

							<!-- 즉시 실행 버튼 -->
							<button
								onclick={() => runSchedule(schedule)}
								disabled={runningId === schedule.id || !schedule.enabled}
								class="btn btn-primary btn-sm"
								title={!schedule.enabled ? '스케줄을 먼저 활성화하세요' : '즉시 실행'}
							>
								{#if runningId === schedule.id}
									실행 중...
								{:else}
									즉시 실행
								{/if}
							</button>
						</div>
					</div>
				</div>
			{/each}
		</div>

		<div class="mt-6 p-4 bg-gray-50 rounded-lg">
			<p class="text-sm text-gray-600">
				<strong>안내:</strong> Instagram 스케줄은 "설정" 버튼을 클릭하여 상세 설정을 변경할 수 있습니다.
			</p>
		</div>
	{/if}
</div>

<!-- Instagram 설정 모달 -->
{#if showSettingsModal && selectedSchedule?.target_type === 'instagram_feed'}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
			<!-- 모달 헤더 -->
			<div class="flex items-center justify-between px-6 py-4 border-b border-gray-200">
				<h2 class="text-xl font-bold text-gray-900">
					Instagram 수집 설정
				</h2>
				<button
					onclick={closeSettings}
					class="text-gray-400 hover:text-gray-600 text-2xl leading-none"
				>
					&times;
				</button>
			</div>

			<!-- 모달 컨텐츠 -->
			<div class="p-6 overflow-y-auto max-h-[calc(90vh-80px)]">
				<InstagramCrawlSettings bind:this={settingsRef} />
			</div>
		</div>
	</div>
{/if}
