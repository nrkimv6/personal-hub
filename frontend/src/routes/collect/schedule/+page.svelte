<script lang="ts">
	import { Button } from '$lib/components/ui';

	import { onMount } from 'svelte';
	import { collectApi } from '$lib/api';
	import type { CrawlSchedule, ServiceAccountWithProfile } from '$lib/types';
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

	// 추가 모달 상태
	let showAddModal = false;
	let addStep = 1; // 1: 타입 선택, 2: 대상 선택, 3: 시간 설정
	let creating = false;

	// 선택값
	let selectedType = ''; // 'instagram_feed' | 'google_search' | 'writing_task'
	let selectedTarget: { id: number; name: string } | null = null;
	let scheduleTimes: string[] = ['09:00', '12:00', '18:00'];

	// 대상 목록
	let serviceAccounts: ServiceAccountWithProfile[] = [];
	let savedSearches: { id: number; name: string; query: string; is_favorite: boolean }[] = [];
	let loadingTargets = false;

	// 삭제 모달 상태
	let showDeleteModal = false;
	let deleteTarget: CrawlSchedule | null = null;
	let deleting = false;

	const scheduleTypes = [
		{ value: 'instagram_feed', label: 'Instagram 피드', icon: '📸', color: 'pink' },
		{ value: 'google_search', label: 'Google 검색', icon: '🔍', color: 'yellow' },
		{ value: 'writing_task', label: '글쓰기 태스크', icon: '✍️', color: 'purple' }
	];

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

	function openAddModal() {
		showAddModal = true;
		addStep = 1;
		selectedType = '';
		selectedTarget = null;
		scheduleTimes = ['09:00', '12:00', '18:00'];
	}

	function closeAddModal() {
		showAddModal = false;
		addStep = 1;
		selectedType = '';
		selectedTarget = null;
	}

	async function selectType(type: string) {
		selectedType = type;

		// writing_task는 대상 선택 불필요
		if (type === 'writing_task') {
			addStep = 3;
			return;
		}

		// 대상 목록 로드
		loadingTargets = true;
		try {
			if (type === 'instagram_feed') {
				serviceAccounts = await collectApi.getAccounts();
			} else if (type === 'google_search') {
				savedSearches = await collectApi.getSavedSearches();
			}
			addStep = 2;
		} catch (e) {
			error = e instanceof Error ? e.message : '대상 목록 로드 실패';
		} finally {
			loadingTargets = false;
		}
	}

	function selectTarget(target: { id: number; name: string }) {
		selectedTarget = target;
		addStep = 3;
	}

	function addTime() {
		scheduleTimes = [...scheduleTimes, '12:00'];
	}

	function removeTime(index: number) {
		scheduleTimes = scheduleTimes.filter((_, i) => i !== index);
	}

	async function createSchedule() {
		if (!selectedType) return;

		creating = true;
		error = null;

		try {
			const data: {
				target_type: string;
				target_config?: Record<string, unknown>;
				schedule_type: string;
				schedule_value: Record<string, unknown>;
			} = {
				target_type: selectedType,
				schedule_type: 'time_window',
				schedule_value: {
					daily_runs: scheduleTimes.length,
					time_windows: scheduleTimes.map((t) => ({ start: t, end: t }))
				}
			};

			if (selectedType === 'instagram_feed' && selectedTarget) {
				data.target_config = { service_account_id: selectedTarget.id };
			} else if (selectedType === 'google_search' && selectedTarget) {
				data.target_config = { saved_search_id: selectedTarget.id };
			}

			await collectApi.createSchedule(data);
			successMessage = '스케줄이 생성되었습니다';
			closeAddModal();
			await fetchSchedules();
		} catch (e) {
			error = e instanceof Error ? e.message : '스케줄 생성 실패';
		} finally {
			creating = false;
		}
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

	function openDeleteModal(schedule: CrawlSchedule) {
		deleteTarget = schedule;
		showDeleteModal = true;
	}

	function closeDeleteModal() {
		showDeleteModal = false;
		deleteTarget = null;
	}

	async function confirmDelete() {
		if (!deleteTarget) return;

		deleting = true;
		error = null;
		try {
			const result = await collectApi.deleteSchedule(deleteTarget.id, true);
			if (result.success) {
				successMessage = result.message;
				closeDeleteModal();
				await fetchSchedules();
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '삭제 실패';
		} finally {
			deleting = false;
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
				return { class: 'bg-pink-light text-pink', text: 'Instagram' };
			case 'universal_crawl':
				return { class: 'bg-primary-light text-primary', text: 'Web' };
			case 'google_search':
				return { class: 'bg-warning-light text-warning-foreground', text: 'Google' };
			case 'writing_task':
				return { class: 'bg-purple-light text-purple-800', text: '글쓰기' };
			default:
				return { class: 'bg-muted text-foreground', text: type };
		}
	}

	function getScheduleTypeBadge(type: string): { class: string; text: string } {
		switch (type) {
			case 'daily':
				return { class: 'bg-success-light text-success', text: '일일' };
			case 'interval':
				return { class: 'bg-primary-light text-primary', text: '간격' };
			case 'cron':
				return { class: 'bg-purple-light text-purple', text: 'Cron' };
			case 'time_window':
				return { class: 'bg-warning-light text-warning', text: '시간대' };
			default:
				return { class: 'bg-background text-foreground', text: type };
		}
	}

	onMount(() => {
		fetchSchedules();
	});
</script>

<div>
	<!-- 헤더 -->
	<div class="flex justify-between items-center mb-6">
		<h2 class="text-xl font-bold text-foreground">스케줄 설정</h2>
		<Button variant="primary" on:click={openAddModal}>
			+ 스케줄 추가
		</Button>
	</div>

	{#if successMessage}
		<div class="bg-success-light border border-green-200 text-success px-4 py-3 rounded-lg mb-4">
			{successMessage}
		</div>
	{/if}

	{#if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg mb-4">
			{error}
		</div>
	{/if}

	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if schedules.length === 0}
		<div class="card text-center py-12">
			<p class="text-muted-foreground">등록된 스케줄이 없습니다</p>
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
									? 'bg-primary'
									: 'bg-secondary'}"
							>
								<span
									class="inline-block w-4 h-4 transform bg-white rounded-full transition-transform {schedule.enabled
										? 'translate-x-6'
										: 'translate-x-1'}"
								></span>
							</button>

							<div>
								<div class="flex items-center gap-2">
									<span class="font-medium text-foreground">
										{schedule.display_name || schedule.name}
									</span>
									<span class="px-2 py-0.5 text-xs rounded-full {targetBadge.class}">
										{targetBadge.text}
									</span>
									<span class="px-2 py-0.5 text-xs rounded-full {scheduleBadge.class}">
										{scheduleBadge.text}
									</span>
								</div>
								<div class="text-sm text-muted-foreground mt-1 flex gap-4">
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
								<Button variant="secondary" size="sm" on:click={() => openSettings(schedule)}
									title="상세 설정"
								>
									설정
								</Button>
							{/if}

							<!-- 즉시 실행 버튼 -->
							<Button
								variant="primary"
								size="sm"
								on:click={() => runSchedule(schedule)}
								disabled={runningId === schedule.id || !schedule.enabled}
								title={!schedule.enabled ? '스케줄을 먼저 활성화하세요' : '즉시 실행'}
							>
								{#if runningId === schedule.id}
									실행 중...
								{:else}
									즉시 실행
								{/if}
							</Button>

							<!-- 삭제 버튼 -->
							<button
								onclick={() => openDeleteModal(schedule)}
								class="btn btn-sm text-error hover:bg-error-light border border-red-200"
								title="스케줄 삭제"
							>
								삭제
							</button>
						</div>
					</div>
				</div>
			{/each}
		</div>

		<div class="mt-6 p-4 bg-background rounded-lg">
			<p class="text-sm text-muted-foreground">
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
			<div class="flex items-center justify-between px-6 py-4 border-b border-border">
				<h2 class="text-xl font-bold text-foreground">
					Instagram 수집 설정
				</h2>
				<button
					onclick={closeSettings}
					class="text-muted-foreground hover:text-muted-foreground text-2xl leading-none"
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

<!-- 스케줄 추가 모달 -->
{#if showAddModal}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-hidden">
			<!-- 모달 헤더 -->
			<div class="flex items-center justify-between px-6 py-4 border-b border-border">
				<div class="flex items-center gap-2">
					<h2 class="text-xl font-bold text-foreground">스케줄 추가</h2>
					{#if addStep > 1}
						<button
							onclick={() => (addStep = addStep === 3 && selectedType === 'writing_task' ? 1 : addStep - 1)}
							class="text-sm text-primary hover:text-primary-hover"
						>
							← 이전
						</button>
					{/if}
				</div>
				<button
					onclick={closeAddModal}
					class="text-muted-foreground hover:text-muted-foreground text-2xl leading-none"
				>
					&times;
				</button>
			</div>

			<!-- 모달 컨텐츠 -->
			<div class="p-6">
				{#if addStep === 1}
					<!-- Step 1: 타입 선택 -->
					<p class="text-muted-foreground mb-4">어떤 종류의 스케줄을 추가하시겠습니까?</p>
					<div class="grid grid-cols-1 gap-3">
						{#each scheduleTypes as st}
							<button
								onclick={() => selectType(st.value)}
								disabled={loadingTargets}
								class="flex items-center gap-3 p-4 border-2 rounded-lg hover:border-blue-500 hover:bg-primary-light transition-colors text-left"
							>
								<span class="text-2xl">{st.icon}</span>
								<div>
									<div class="font-medium text-foreground">{st.label}</div>
									<div class="text-sm text-muted-foreground">
										{#if st.value === 'instagram_feed'}
											Instagram 피드를 주기적으로 수집합니다
										{:else if st.value === 'google_search'}
											저장된 검색 결과를 주기적으로 수집합니다
										{:else}
											글쓰기 태스크를 주기적으로 실행합니다
										{/if}
									</div>
								</div>
							</button>
						{/each}
					</div>

				{:else if addStep === 2}
					<!-- Step 2: 대상 선택 -->
					{#if loadingTargets}
						<div class="flex justify-center py-8">
							<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
						</div>
					{:else if selectedType === 'instagram_feed'}
						<p class="text-muted-foreground mb-4">수집할 Instagram 계정을 선택하세요</p>
						{#if serviceAccounts.length === 0}
							<p class="text-muted-foreground text-center py-4">등록된 계정이 없습니다</p>
						{:else}
							<div class="space-y-2 max-h-64 overflow-y-auto">
								{#each serviceAccounts as account}
									<button
										onclick={() => selectTarget({ id: account.id, name: account.profile_name || account.identifier })}
										class="w-full flex items-center gap-3 p-3 border rounded-lg hover:border-blue-500 hover:bg-primary-light transition-colors text-left"
									>
										<div class="w-10 h-10 bg-pink-light rounded-full flex items-center justify-center text-pink">
											📸
										</div>
										<div>
											<div class="font-medium text-foreground">{account.profile_name || account.identifier}</div>
											<div class="text-sm text-muted-foreground">
												{account.is_logged_in ? '로그인됨' : '로그인 필요'}
											</div>
										</div>
									</button>
								{/each}
							</div>
						{/if}
					{:else if selectedType === 'google_search'}
						<p class="text-muted-foreground mb-4">수집할 저장된 검색을 선택하세요</p>
						{#if savedSearches.length === 0}
							<p class="text-muted-foreground text-center py-4">저장된 검색이 없습니다</p>
						{:else}
							<div class="space-y-2 max-h-64 overflow-y-auto">
								{#each savedSearches as saved}
									<button
										onclick={() => selectTarget({ id: saved.id, name: saved.name })}
										class="w-full flex items-center gap-3 p-3 border rounded-lg hover:border-blue-500 hover:bg-primary-light transition-colors text-left"
									>
										<div class="w-10 h-10 bg-warning-light rounded-full flex items-center justify-center text-warning-foreground">
											{saved.is_favorite ? '⭐' : '🔍'}
										</div>
										<div>
											<div class="font-medium text-foreground">{saved.name}</div>
											<div class="text-sm text-muted-foreground truncate max-w-xs">{saved.query}</div>
										</div>
									</button>
								{/each}
							</div>
						{/if}
					{/if}

				{:else if addStep === 3}
					<!-- Step 3: 시간 설정 -->
					<div class="mb-4">
						<p class="text-muted-foreground mb-2">실행 시간을 설정하세요</p>
						{#if selectedType !== 'writing_task' && selectedTarget}
							<p class="text-sm text-primary">
								선택된 대상: {selectedTarget.name}
							</p>
						{/if}
					</div>

					<div class="space-y-3 mb-4">
						{#each scheduleTimes as time, i}
							<div class="flex items-center gap-2">
								<input
									type="time"
									bind:value={scheduleTimes[i]}
									class="flex-1 px-3 py-2 border rounded-lg focus:ring-2 focus:ring-ring focus:border-ring"
								/>
								{#if scheduleTimes.length > 1}
									<button
										onclick={() => removeTime(i)}
										class="p-2 text-error hover:bg-error-light rounded-lg"
										title="삭제"
									>
										✕
									</button>
								{/if}
							</div>
						{/each}
					</div>

					<button
						onclick={addTime}
						class="w-full py-2 border-2 border-dashed border-border rounded-lg text-muted-foreground hover:border-blue-500 hover:text-primary transition-colors"
					>
						+ 시간 추가
					</button>

					<div class="mt-6 flex justify-end gap-2">
						<Button variant="secondary" on:click={closeAddModal}>
							취소
						</Button>
						<button
							onclick={createSchedule}
							disabled={creating}
							class="btn btn-primary"
						>
							{#if creating}
								생성 중...
							{:else}
								생성
							{/if}
						</button>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- 삭제 확인 모달 -->
{#if showDeleteModal && deleteTarget}
	<div class="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl shadow-2xl max-w-md w-full">
			<!-- 모달 헤더 -->
			<div class="px-6 py-4 border-b border-border">
				<h2 class="text-xl font-bold text-foreground">스케줄 삭제</h2>
			</div>

			<!-- 모달 컨텐츠 -->
			<div class="p-6">
				<p class="text-foreground mb-4">
					<strong>"{deleteTarget.display_name || deleteTarget.name}"</strong> 스케줄을 삭제하시겠습니까?
				</p>
				<p class="text-sm text-error bg-error-light p-3 rounded-lg">
					실행 이력도 함께 삭제됩니다. 이 작업은 되돌릴 수 없습니다.
				</p>
			</div>

			<!-- 모달 푸터 -->
			<div class="px-6 py-4 border-t border-border flex justify-end gap-2">
				<Button variant="secondary" on:click={closeDeleteModal} disabled={deleting}>
					취소
				</Button>
				<button
					onclick={confirmDelete}
					disabled={deleting}
					class="btn bg-error text-white hover:bg-error/90"
				>
					{#if deleting}
						삭제 중...
					{:else}
						삭제
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}
