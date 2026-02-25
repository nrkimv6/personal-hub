<script>
	import { page } from "$app/stores";
	import { onMount } from "svelte";
	import { goto } from "$app/navigation";
  import { fetchWithTimeout } from '$lib/api/client';

	const targetId = $derived($page.params.id);

	/** @type {{ name: string; url: string; [key: string]: unknown } | null} */
	let target = $state(null);
	/** @type {Record<string, unknown>[]} */
	let schedules = $state([]);
	let loading = $state(true);
	/** @type {string | null} */
	let error = $state(null);

	// 새 스케줄 폼
	let showNewScheduleForm = $state(false);
	let newSchedule = $state({
		interval_days: 7, // 기본 주 1회
		enabled: true,
	});

	async function loadData() {
		try {
			loading = true;

			// 대상 정보 로드
			const targetRes = await fetchWithTimeout(`/api/v1/mobile/targets/${targetId}`);
			if (!targetRes.ok) throw new Error("대상 조회 실패");
			target = await targetRes.json();

			// 스케줄 목록 로드 (Mock)
			// 실제로는 /api/v1/schedules?target_type=mobile_crawl&target_id=${targetId} 같은 API를 호출
			schedules = generateMockSchedules();
		} catch (err) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	function generateMockSchedules() {
		// Mock 데이터: 실제로는 TaskSchedule API에서 가져와야 함
		return [
			{
				id: 1,
				target_type: "mobile_crawl",
				target_config: { mobile_crawl_target_id: parseInt(targetId) },
				interval_seconds: 7 * 24 * 3600, // 7일
				enabled: true,
				last_run: new Date(Date.now() - 2 * 24 * 3600000).toISOString(),
				next_run: new Date(Date.now() + 5 * 24 * 3600000).toISOString(),
				created_at: new Date(
					Date.now() - 30 * 24 * 3600000,
				).toISOString(),
			},
		];
	}

	async function createSchedule() {
		try {
			const intervalSeconds = newSchedule.interval_days * 24 * 3600;

			const response = await fetchWithTimeout("/api/v1/schedules", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify({
					target_type: "mobile_crawl",
					target_config: {
						mobile_crawl_target_id: parseInt(targetId),
					},
					interval_seconds: intervalSeconds,
					enabled: newSchedule.enabled,
				}),
			});

			if (!response.ok) throw new Error("스케줄 생성 실패");

			alert("스케줄이 생성되었습니다.");
			showNewScheduleForm = false;
			await loadData();
		} catch (err) {
			alert(`스케줄 생성 실패: ${err.message}`);
		}
	}

	async function toggleSchedule(schedule) {
		try {
			const response = await fetchWithTimeout(`/api/v1/schedules/${schedule.id}`, {
				method: "PUT",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify({
					...schedule,
					enabled: !schedule.enabled,
				}),
			});

			if (!response.ok) throw new Error("스케줄 업데이트 실패");

			alert("스케줄 상태가 변경되었습니다.");
			await loadData();
		} catch (err) {
			alert(`스케줄 업데이트 실패: ${err.message}`);
		}
	}

	async function deleteSchedule(schedule) {
		if (!confirm("스케줄을 삭제하시겠습니까?")) return;

		try {
			const response = await fetchWithTimeout(`/api/v1/schedules/${schedule.id}`, {
				method: "DELETE",
			});

			if (!response.ok) throw new Error("스케줄 삭제 실패");

			alert("스케줄이 삭제되었습니다.");
			await loadData();
		} catch (err) {
			alert(`스케줄 삭제 실패: ${err.message}`);
		}
	}

	function formatInterval(seconds) {
		const days = Math.floor(seconds / 86400);
		const hours = Math.floor((seconds % 86400) / 3600);
		const minutes = Math.floor((seconds % 3600) / 60);

		const parts = [];
		if (days > 0) parts.push(`${days}일`);
		if (hours > 0) parts.push(`${hours}시간`);
		if (minutes > 0) parts.push(`${minutes}분`);

		return parts.join(" ") || "0분";
	}

	onMount(() => {
		loadData();
	});
</script>

<div class="container mx-auto p-4">
	{#if loading}
		<div class="text-center py-8">로딩 중...</div>
	{:else if error}
		<div class="alert alert-error">{error}</div>
	{:else if target}
		<div class="mb-6">
			<div class="breadcrumbs text-sm">
				<ul>
					<li><a href="/mobile/targets">크롤링 대상</a></li>
					<li>
						<a href="/mobile/targets/{targetId}">{target.name}</a>
					</li>
					<li>스케줄 관리</li>
				</ul>
			</div>

			<h1 class="text-2xl font-bold mt-2">{target.name} - 스케줄 관리</h1>
			<p class="text-gray-600 mt-1">주기적 크롤링 스케줄을 설정합니다.</p>
		</div>

		<!-- 새 스케줄 버튼 -->
		<div class="mb-6">
			{#if !showNewScheduleForm}
				<button
					class="btn btn-primary"
					onclick={() => (showNewScheduleForm = true)}
				>
					+ 새 스케줄 추가
				</button>
			{/if}
		</div>

		<!-- 새 스케줄 폼 -->
		{#if showNewScheduleForm}
			<div class="card bg-base-100 shadow mb-6">
				<div class="card-body">
					<h2 class="card-title">새 스케줄</h2>

					<div class="form-control">
						<label class="label">
							<span class="label-text">실행 주기 (일 단위)</span>
						</label>
						<input
							type="number"
							bind:value={newSchedule.interval_days}
							min="1"
							max="365"
							class="input input-bordered w-32"
						/>
						<label class="label">
							<span class="label-text-alt"
								>{formatInterval(
									newSchedule.interval_days * 86400,
								)}</span
							>
						</label>
					</div>

					<div class="form-control">
						<label class="label cursor-pointer justify-start gap-2">
							<input
								type="checkbox"
								bind:checked={newSchedule.enabled}
								class="checkbox"
							/>
							<span class="label-text">활성화</span>
						</label>
					</div>

					<div class="card-actions justify-end">
						<button
							class="btn btn-ghost"
							onclick={() => (showNewScheduleForm = false)}
						>
							취소
						</button>
						<button
							class="btn btn-primary"
							onclick={createSchedule}
						>
							생성
						</button>
					</div>
				</div>
			</div>
		{/if}

		<!-- 스케줄 목록 -->
		{#if schedules.length === 0}
			<div class="alert alert-info">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					class="stroke-current shrink-0 w-6 h-6"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
					></path>
				</svg>
				<span>등록된 스케줄이 없습니다. 새 스케줄을 추가해주세요.</span>
			</div>
		{:else}
			<div class="space-y-4">
				{#each schedules as schedule}
					<div class="card bg-base-100 shadow">
						<div class="card-body">
							<div
								class="flex flex-col sm:flex-row justify-between items-start gap-4"
							>
								<div class="flex-1 w-full min-w-0">
									<div
										class="flex flex-wrap items-center gap-2 mb-2"
									>
										<h3
											class="font-semibold whitespace-nowrap"
										>
											주기: {formatInterval(
												schedule.interval_seconds,
											)}
										</h3>
										<div
											class="badge {schedule.enabled
												? 'badge-success'
												: 'badge-ghost'} shrink-0"
										>
											{schedule.enabled
												? "활성화"
												: "비활성화"}
										</div>
									</div>

									<div class="text-sm space-y-1">
										{#if schedule.last_run}
											<div
												class="text-gray-600 break-words"
											>
												마지막 실행: {new Date(
													schedule.last_run,
												).toLocaleString()}
											</div>
										{/if}
										{#if schedule.next_run}
											<div
												class="text-gray-600 break-words"
											>
												다음 실행: {new Date(
													schedule.next_run,
												).toLocaleString()}
											</div>
										{/if}
										<div
											class="text-xs text-gray-500 break-words"
										>
											생성일: {new Date(
												schedule.created_at,
											).toLocaleString()}
										</div>
									</div>
								</div>

								<div
									class="flex gap-2 w-full sm:w-auto justify-end flex-wrap"
								>
									<button
										class="btn btn-sm {schedule.enabled
											? 'btn-warning'
											: 'btn-success'} flex-1 sm:flex-none"
										onclick={() => toggleSchedule(schedule)}
									>
										{schedule.enabled
											? "비활성화"
											: "활성화"}
									</button>
									<button
										class="btn btn-sm btn-error flex-1 sm:flex-none"
										onclick={() => deleteSchedule(schedule)}
									>
										삭제
									</button>
								</div>
							</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- 안내 -->
		<div class="alert alert-info mt-6">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				class="stroke-current shrink-0 w-6 h-6"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
				></path>
			</svg>
			<div class="text-sm">
				<div class="font-bold mb-1">스케줄 실행 안내</div>
				<ul class="list-disc list-inside space-y-1">
					<li>스케줄은 워커가 실행 중일 때만 동작합니다.</li>
					<li>다음 실행 시간이 되면 자동으로 크롤링이 실행됩니다.</li>
					<li>모바일 서버 연결이 필요합니다.</li>
				</ul>
			</div>
		</div>

		<div class="mt-6">
			<button
				class="btn btn-ghost"
				onclick={() => goto(`/mobile/targets/${targetId}`)}
			>
				← 대상 상세로 돌아가기
			</button>
		</div>
	{/if}
</div>
