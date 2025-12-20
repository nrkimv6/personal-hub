<script lang="ts">
	import { onMount } from 'svelte';
	import { instagramApi } from '$lib/api';
	import type {
		InstagramScheduleConfig,
		InstagramTimeWindow,
		InstagramTodayScheduleItem
	} from '$lib/types';

	let config: InstagramScheduleConfig | null = null;
	let todaySchedule: InstagramTodayScheduleItem[] = [];
	let loading = true;
	let saving = false;
	let error: string | null = null;
	let successMessage: string | null = null;

	// 편집용 상태
	let editEnabled = false;
	let editDailyRuns = 3;
	let editTimeWindows: InstagramTimeWindow[] = [];
	let editMaxPosts = 50;
	let editScrollCount = 5;

	async function fetchData() {
		loading = true;
		try {
			const [configData, scheduleData] = await Promise.all([
				instagramApi.getSchedule(),
				instagramApi.todaySchedule()
			]);
			config = configData;
			todaySchedule = scheduleData;

			// 편집용 상태 초기화
			editEnabled = configData.enabled;
			editDailyRuns = configData.daily_runs;
			editTimeWindows = [...configData.time_windows];
			editMaxPosts = configData.max_posts;
			editScrollCount = configData.scroll_count;

			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	async function saveConfig() {
		saving = true;
		successMessage = null;
		try {
			await instagramApi.updateSchedule({
				enabled: editEnabled,
				daily_runs: editDailyRuns,
				time_windows: editTimeWindows,
				max_posts: editMaxPosts,
				scroll_count: editScrollCount
			});
			successMessage = '설정이 저장되었습니다';
			await fetchData();
		} catch (e) {
			error = e instanceof Error ? e.message : '저장 실패';
		} finally {
			saving = false;
		}
	}

	function addTimeWindow() {
		editTimeWindows = [...editTimeWindows, { start: '09:00', end: '12:00' }];
	}

	function removeTimeWindow(index: number) {
		editTimeWindows = editTimeWindows.filter((_, i) => i !== index);
	}

	function getScheduleStatusColor(status: string): string {
		switch (status) {
			case 'completed':
				return 'bg-green-100 text-green-800';
			case 'running':
				return 'bg-blue-100 text-blue-800';
			case 'pending':
				return 'bg-yellow-100 text-yellow-800';
			case 'missed':
				return 'bg-red-100 text-red-800';
			default:
				return 'bg-gray-100 text-gray-800';
		}
	}

	function getScheduleStatusLabel(status: string): string {
		switch (status) {
			case 'completed':
				return '완료';
			case 'running':
				return '실행 중';
			case 'pending':
				return '대기 중';
			case 'missed':
				return '놓침';
			default:
				return status;
		}
	}

	onMount(() => {
		fetchData();
	});
</script>

<div class="p-6">
	<div class="mb-6 flex justify-between items-center">
		<h2 class="text-2xl font-bold text-gray-900">수집 설정</h2>
		<button onclick={fetchData} class="btn btn-secondary btn-sm"> 새로고침 </button>
	</div>

	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
			{error}
		</div>
	{:else}
		{#if successMessage}
			<div
				class="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg mb-4"
			>
				{successMessage}
			</div>
		{/if}

		<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
			<!-- 설정 폼 -->
			<div class="card">
				<h3 class="text-lg font-semibold text-gray-900 mb-4">스케줄 설정</h3>

				<div class="space-y-4">
					<!-- 활성화 -->
					<div class="flex items-center justify-between">
						<label for="enabled" class="font-medium text-gray-700">자동 수집</label>
						<label class="relative inline-flex items-center cursor-pointer">
							<input
								id="enabled"
								type="checkbox"
								bind:checked={editEnabled}
								class="sr-only peer"
							/>
							<div
								class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"
							></div>
						</label>
					</div>

					<!-- 일일 실행 횟수 -->
					<div>
						<label for="dailyRuns" class="block font-medium text-gray-700 mb-1"
							>일일 수집 횟수</label
						>
						<input
							id="dailyRuns"
							type="number"
							bind:value={editDailyRuns}
							min="1"
							max="10"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg"
						/>
						<p class="text-xs text-gray-500 mt-1">하루에 몇 번 수집할지 설정합니다</p>
					</div>

					<!-- 시간 윈도우 -->
					<div>
						<label class="block font-medium text-gray-700 mb-2">수집 시간대</label>
						<div class="space-y-2">
							{#each editTimeWindows as window, idx}
								<div class="flex items-center gap-2">
									<input
										type="time"
										bind:value={window.start}
										class="px-3 py-2 border border-gray-300 rounded-lg"
									/>
									<span>~</span>
									<input
										type="time"
										bind:value={window.end}
										class="px-3 py-2 border border-gray-300 rounded-lg"
									/>
									<button
										onclick={() => removeTimeWindow(idx)}
										class="text-red-500 hover:text-red-700 text-xl"
									>
										&times;
									</button>
								</div>
							{/each}
						</div>
						<button
							onclick={addTimeWindow}
							class="mt-2 text-sm text-blue-600 hover:text-blue-800"
						>
							+ 시간대 추가
						</button>
						<p class="text-xs text-gray-500 mt-1">
							각 시간대 내에서 랜덤한 시간에 수집합니다
						</p>
					</div>

					<!-- 최대 게시물 수 -->
					<div>
						<label for="maxPosts" class="block font-medium text-gray-700 mb-1"
							>최대 수집 게시물</label
						>
						<input
							id="maxPosts"
							type="number"
							bind:value={editMaxPosts}
							min="10"
							max="200"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg"
						/>
					</div>

					<!-- 스크롤 횟수 -->
					<div>
						<label for="scrollCount" class="block font-medium text-gray-700 mb-1"
							>스크롤 횟수</label
						>
						<input
							id="scrollCount"
							type="number"
							bind:value={editScrollCount}
							min="1"
							max="20"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg"
						/>
						<p class="text-xs text-gray-500 mt-1">더 많은 게시물을 로드하기 위한 스크롤 횟수</p>
					</div>

					<!-- 저장 버튼 -->
					<button onclick={saveConfig} disabled={saving} class="btn btn-primary w-full">
						{saving ? '저장 중...' : '설정 저장'}
					</button>
				</div>
			</div>

			<!-- 오늘 스케줄 -->
			<div class="card">
				<h3 class="text-lg font-semibold text-gray-900 mb-4">오늘 수집 스케줄</h3>

				{#if todaySchedule.length === 0}
					<p class="text-gray-500 text-center py-8">
						{editEnabled ? '스케줄이 아직 생성되지 않았습니다' : '자동 수집이 비활성화되어 있습니다'}
					</p>
				{:else}
					<div class="space-y-3">
						{#each todaySchedule as item, idx}
							<div
								class="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
							>
								<div class="flex items-center gap-3">
									<span
										class="w-8 h-8 flex items-center justify-center bg-blue-100 text-blue-800 rounded-full font-medium"
									>
										{idx + 1}
									</span>
									<span class="font-medium">{item.scheduled_time}</span>
								</div>
								<span
									class="px-3 py-1 text-sm rounded-full {getScheduleStatusColor(item.status)}"
								>
									{getScheduleStatusLabel(item.status)}
								</span>
							</div>
						{/each}
					</div>
				{/if}

				<div class="mt-6 pt-4 border-t border-gray-200">
					<p class="text-sm text-gray-500 mb-2">
						수집 시간은 매일 랜덤하게 결정됩니다. 같은 날짜에는 동일한 시간에 수집합니다.
					</p>
				</div>
			</div>
		</div>
	{/if}
</div>
