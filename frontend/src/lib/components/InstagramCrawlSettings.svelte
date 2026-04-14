<script lang="ts">
	import { onMount } from 'svelte';
	import { collectApi } from '$lib/api';
	import type {
		InstagramScheduleConfig,
		InstagramTimeWindow,
		InstagramTodayScheduleItem,
		InstagramCrawlRequest,
		ServiceAccountWithProfile
	} from '$lib/types';
	import { Button } from '$lib/components/ui';

	let config: InstagramScheduleConfig | null = null;
	let todaySchedule: InstagramTodayScheduleItem[] = [];
	let pendingRequests: InstagramCrawlRequest[] = [];
	let accounts: ServiceAccountWithProfile[] = [];
	let loading = true;
	let saving = false;
	let requesting = false;
	let openingBrowser = false;
	let checkingLogin = false;
	let error: string | null = null;
	let successMessage: string | null = null;

	// 편집용 상태
	let editEnabled = false;
	let editDailyRuns = 3;
	let editTimeWindows: InstagramTimeWindow[] = [];
	let editMaxPosts = 50;
	let editScrollCount = 5;
	let editAccountId: number | null = null;
	// 고급 설정
	let editMinIntervalHours = 2;
	let editDuplicateStopCount = 5;
	let editMaxRetries = 3;
	let editRetryIntervalMinutes = 5;
	let showAdvanced = false;

	export async function fetchData() {
		loading = true;
		try {
			const [configData, scheduleData, pendingData, accountsData] = await Promise.all([
				collectApi.getInstagramSchedule(),
				collectApi.todaySchedule(),
				collectApi.getPendingRequests(5),
				collectApi.getAccounts()
			]);
			config = configData;
			todaySchedule = scheduleData;
			pendingRequests = pendingData;
			accounts = accountsData;

			// 편집용 상태 초기화
			editEnabled = configData.enabled;
			editDailyRuns = configData.daily_runs;
			editTimeWindows = [...configData.time_windows];
			editMaxPosts = configData.max_posts;
			editScrollCount = configData.scroll_count;
			editAccountId = configData.service_account_id;
			// 고급 설정
			editMinIntervalHours = configData.min_interval_hours ?? 2;
			editDuplicateStopCount = configData.duplicate_stop_count ?? 5;
			editMaxRetries = configData.max_retries ?? 3;
			editRetryIntervalMinutes = configData.retry_interval_minutes ?? 5;

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
			await collectApi.updateInstagramSchedule({
				enabled: editEnabled,
				daily_runs: editDailyRuns,
				time_windows: editTimeWindows,
				max_posts: editMaxPosts,
				scroll_count: editScrollCount,
				min_interval_hours: editMinIntervalHours,
				duplicate_stop_count: editDuplicateStopCount,
				max_retries: editMaxRetries,
				retry_interval_minutes: editRetryIntervalMinutes,
				service_account_id: editAccountId
			});
			successMessage = '설정이 저장되었습니다';
			await fetchData();
		} catch (e) {
			error = e instanceof Error ? e.message : '저장 실패';
		} finally {
			saving = false;
		}
	}

	async function requestManualCrawl() {
		if (!editAccountId) {
			error = '계정을 먼저 선택해주세요';
			return;
		}
		requesting = true;
		successMessage = null;
		try {
			const result = await collectApi.requestManualCrawl(editAccountId);
			successMessage = `수집 요청 #${result.id}이(가) 추가되었습니다`;
			await fetchData();
		} catch (e) {
			error = e instanceof Error ? e.message : '요청 실패';
		} finally {
			requesting = false;
		}
	}

	async function openLoginBrowser() {
		if (!editAccountId) {
			error = '계정을 먼저 선택해주세요';
			return;
		}
		openingBrowser = true;
		successMessage = null;
		try {
			const result = await collectApi.openLoginBrowser(editAccountId);
			successMessage = result.message;
		} catch (e) {
			error = e instanceof Error ? e.message : '브라우저 열기 실패';
		} finally {
			openingBrowser = false;
		}
	}

	async function checkLoginStatus() {
		if (!editAccountId) {
			error = '계정을 먼저 선택해주세요';
			return;
		}
		checkingLogin = true;
		successMessage = null;
		error = null;
		try {
			const result = await collectApi.checkLoginStatus(editAccountId);
			if (result.is_logged_in) {
				successMessage = `${result.account_name}: 로그인 확인됨`;
			} else {
				error = `${result.account_name}: 로그인 필요`;
			}
			await fetchData();
		} catch (e) {
			error = e instanceof Error ? e.message : '로그인 상태 확인 실패';
		} finally {
			checkingLogin = false;
		}
	}

	$: selectedAccount = accounts.find((a) => a.id === editAccountId);

	function addTimeWindow() {
		editTimeWindows = [...editTimeWindows, { start: '09:00', end: '12:00' }];
	}

	function removeTimeWindow(index: number) {
		editTimeWindows = editTimeWindows.filter((_, i) => i !== index);
	}

	function getScheduleStatusColor(status: string): string {
		switch (status) {
			case 'completed':
				return 'bg-success-light text-success';
			case 'running':
				return 'bg-primary-light text-primary';
			case 'pending':
				return 'bg-warning-light text-warning-foreground';
			case 'missed':
				return 'bg-error-light text-error';
			default:
				return 'bg-muted text-foreground';
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

<div>
	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg mb-4">
			{error}
		</div>
	{:else}
		{#if successMessage}
			<div class="bg-success-light border border-green-200 text-success px-4 py-3 rounded-lg mb-4">
				{successMessage}
			</div>
		{/if}

		<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
			<!-- 설정 폼 -->
			<div class="card">
				<h3 class="text-lg font-semibold text-foreground mb-4">스케줄 설정</h3>

				<div class="space-y-4">
					<!-- 계정 선택 -->
					<div>
						<label for="account" class="block font-medium text-foreground mb-1">크롤링 계정</label>
						<div class="flex gap-2">
							<select
								id="account"
								bind:value={editAccountId}
								class="flex-1 px-3 py-2 border border-border rounded-lg"
							>
								<option value={null}>-- 계정 선택 --</option>
								{#each accounts as account}
									<option value={account.id}>
										{account.profile_name}
										{account.is_logged_in ? '(로그인됨)' : '(로그인 필요)'}
									</option>
								{/each}
							</select>
							<Button
								variant="secondary"
								size="sm"
								onclick={openLoginBrowser}
								disabled={!editAccountId || openingBrowser}
								class="whitespace-nowrap"
							>
								{openingBrowser ? '열기...' : '로그인'}
							</Button>
							<Button
								variant="outline"
								size="sm"
								onclick={checkLoginStatus}
								disabled={!editAccountId || checkingLogin}
								class="whitespace-nowrap"
								title="로그인 후 이 버튼을 눌러 상태를 확인하세요"
							>
								{checkingLogin ? '확인중...' : '확인'}
							</Button>
						</div>
						{#if !editAccountId}
							<p class="text-xs text-warning mt-1">
								계정이 선택되지 않으면 크롤링이 실행되지 않습니다
							</p>
						{:else if selectedAccount && !selectedAccount.is_logged_in}
							<p class="text-xs text-warning mt-1">
								선택한 계정으로 Instagram 로그인이 필요합니다
							</p>
						{/if}
					</div>

					<!-- 활성화 -->
					<div class="flex items-center justify-between">
						<label for="enabled" class="font-medium text-foreground">자동 수집</label>
						<label class="relative inline-flex items-center cursor-pointer">
							<input id="enabled" type="checkbox" bind:checked={editEnabled} class="sr-only peer" />
							<div
								class="w-11 h-6 bg-secondary peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"
							></div>
						</label>
					</div>

					<!-- 일일 실행 횟수 -->
					<div>
						<label for="dailyRuns" class="block font-medium text-foreground mb-1"
							>일일 수집 횟수</label
						>
						<input
							id="dailyRuns"
							type="number"
							bind:value={editDailyRuns}
							min="1"
							max="10"
							class="w-full px-3 py-2 border border-border rounded-lg"
						/>
						<p class="text-xs text-muted-foreground mt-1">하루에 몇 번 수집할지 설정합니다</p>
					</div>

					<!-- 시간 윈도우 -->
					<div>
						<label class="block font-medium text-foreground mb-2">수집 시간대</label>
						<div class="space-y-2">
							{#each editTimeWindows as window, idx}
								<div class="flex items-center gap-2">
									<input
										type="time"
										bind:value={window.start}
										class="px-3 py-2 border border-border rounded-lg"
									/>
									<span>~</span>
									<input
										type="time"
										bind:value={window.end}
										class="px-3 py-2 border border-border rounded-lg"
									/>
									<button
										onclick={() => removeTimeWindow(idx)}
										class="text-error hover:text-error text-xl"
									>
										&times;
									</button>
								</div>
							{/each}
						</div>
						<button onclick={addTimeWindow} class="mt-2 text-sm text-primary hover:text-primary-hover">
							+ 시간대 추가
						</button>
						<p class="text-xs text-muted-foreground mt-1">각 시간대 내에서 랜덤한 시간에 수집합니다</p>
					</div>

					<!-- 최대 게시물 수 -->
					<div>
						<label for="maxPosts" class="block font-medium text-foreground mb-1"
							>최대 수집 게시물</label
						>
						<input
							id="maxPosts"
							type="number"
							bind:value={editMaxPosts}
							min="10"
							max="200"
							class="w-full px-3 py-2 border border-border rounded-lg"
						/>
					</div>

					<!-- 스크롤 횟수 -->
					<div>
						<label for="scrollCount" class="block font-medium text-foreground mb-1">스크롤 횟수</label
						>
						<input
							id="scrollCount"
							type="number"
							bind:value={editScrollCount}
							min="1"
							max="20"
							class="w-full px-3 py-2 border border-border rounded-lg"
						/>
						<p class="text-xs text-muted-foreground mt-1">더 많은 게시물을 로드하기 위한 스크롤 횟수</p>
					</div>

					<!-- 고급 설정 토글 -->
					<div class="border-t border-border pt-4">
						<button
							type="button"
							onclick={() => (showAdvanced = !showAdvanced)}
							class="text-sm text-primary hover:text-primary-hover flex items-center gap-1"
						>
							{showAdvanced ? '▼' : '▶'} 고급 설정
						</button>

						{#if showAdvanced}
							<div class="mt-4 space-y-4 bg-background p-4 rounded-lg">
								<div>
									<label for="minInterval" class="block font-medium text-foreground mb-1"
										>최소 실행 간격 (시간)</label
									>
									<input
										id="minInterval"
										type="number"
										bind:value={editMinIntervalHours}
										min="0"
										max="24"
										class="w-full px-3 py-2 border border-border rounded-lg"
									/>
									<p class="text-xs text-muted-foreground mt-1">
										마지막 수집 후 최소 대기 시간 (0이면 비활성화)
									</p>
								</div>

								<div>
									<label for="duplicateStop" class="block font-medium text-foreground mb-1"
										>중복 감지 중단</label
									>
									<input
										id="duplicateStop"
										type="number"
										bind:value={editDuplicateStopCount}
										min="0"
										max="50"
										class="w-full px-3 py-2 border border-border rounded-lg"
									/>
									<p class="text-xs text-muted-foreground mt-1">연속 N개 중복 시 수집 중단 (0이면 비활성화)</p>
								</div>

								<div>
									<label for="maxRetries" class="block font-medium text-foreground mb-1"
										>최대 재시도</label
									>
									<input
										id="maxRetries"
										type="number"
										bind:value={editMaxRetries}
										min="0"
										max="10"
										class="w-full px-3 py-2 border border-border rounded-lg"
									/>
									<p class="text-xs text-muted-foreground mt-1">실패 시 최대 재시도 횟수</p>
								</div>

								<div>
									<label for="retryInterval" class="block font-medium text-foreground mb-1"
										>재시도 간격 (분)</label
									>
									<input
										id="retryInterval"
										type="number"
										bind:value={editRetryIntervalMinutes}
										min="1"
										max="60"
										class="w-full px-3 py-2 border border-border rounded-lg"
									/>
									<p class="text-xs text-muted-foreground mt-1">재시도 기본 간격 (지수 백오프 적용)</p>
								</div>
							</div>
						{/if}
					</div>

					<!-- 저장 버튼 -->
					<Button variant="primary" onclick={saveConfig} disabled={saving} class="w-full">
						{saving ? '저장 중...' : '설정 저장'}
					</Button>
				</div>
			</div>

			<!-- 오늘 스케줄 -->
			<div class="card">
				<div class="flex justify-between items-center mb-4">
					<h3 class="text-lg font-semibold text-foreground">오늘 수집 스케줄</h3>
					<Button
						variant="primary"
						size="sm"
						onclick={requestManualCrawl}
						disabled={!editAccountId || requesting || pendingRequests.length > 0}
						title={!editAccountId ? '계정을 먼저 선택하세요' : ''}
					>
						{#if requesting}
							수집 요청 중...
						{:else if pendingRequests.length > 0}
							대기 중 ({pendingRequests.length})
						{:else if !editAccountId}
							계정 선택 필요
						{:else}
							지금 수집
						{/if}
					</Button>
				</div>

				{#if pendingRequests.length > 0}
					<div class="mb-4 p-3 bg-warning-light border border-yellow-200 rounded-lg">
						<p class="text-sm text-warning-foreground">대기 중인 요청: {pendingRequests.length}개</p>
					</div>
				{/if}

				{#if todaySchedule.length === 0}
					<p class="text-muted-foreground text-center py-8">
						{editEnabled ? '스케줄이 아직 생성되지 않았습니다' : '자동 수집이 비활성화되어 있습니다'}
					</p>
				{:else}
					<div class="space-y-3">
						{#each todaySchedule as item, idx}
							<div class="flex items-center justify-between p-3 bg-background rounded-lg">
								<div class="flex items-center gap-3">
									<span
										class="w-8 h-8 flex items-center justify-center bg-primary-light text-primary rounded-full font-medium"
									>
										{idx + 1}
									</span>
									<span class="font-medium">{item.scheduled_time}</span>
								</div>
								<span class="px-3 py-1 text-sm rounded-full {getScheduleStatusColor(item.status)}">
									{getScheduleStatusLabel(item.status)}
								</span>
							</div>
						{/each}
					</div>
				{/if}

				<div class="mt-6 pt-4 border-t border-border">
					<p class="text-sm text-muted-foreground mb-2">
						수집 시간은 매일 랜덤하게 결정됩니다. 같은 날짜에는 동일한 시간에 수집합니다.
					</p>
				</div>
			</div>
		</div>
	{/if}
</div>
