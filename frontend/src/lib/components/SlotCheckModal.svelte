<script lang="ts">
	import { slotApi, monitoringEventApi } from '$lib/api';
	import type {
		SlotCheckResponse,
		DateSlots,
		SlotInfo,
		Business,
		BizItem,
		MonitoringEventStats
	} from '$lib/types';

	interface Props {
		show: boolean;
		business: Business | null;
		item: BizItem | null;
		onClose: () => void;
	}

	let { show, business, item, onClose }: Props = $props();

	// 공통 옵션
	let targetDate = $state('');
	let daysAhead = $state(14);

	// 조회 상태
	let loading = $state(false);
	let error = $state<string | null>(null);
	let result = $state<SlotCheckResponse | null>(null);

	// 모니터링 통계
	let monitoringStats = $state<MonitoringEventStats | null>(null);
	let loadingStats = $state(false);

	// 날짜별 접기/펼치기 상태
	let expandedDates = $state<Set<string>>(new Set());

	// 모달이 열릴 때 자동 조회
	$effect(() => {
		if (show && business && item) {
			checkSlots();
		}
	});

	// 모달이 닫힐 때 상태 초기화
	$effect(() => {
		if (!show) {
			result = null;
			error = null;
			monitoringStats = null;
			expandedDates = new Set();
		}
	});

	// 슬롯 조회
	async function checkSlots() {
		if (!business || !item) return;

		loading = true;
		error = null;
		result = null;
		monitoringStats = null;

		try {
			result = await slotApi.check({
				business_id: business.business_id,
				biz_item_id: item.biz_item_id,
				target_date: targetDate || undefined,
				days_ahead: daysAhead
			});

			// 첫 번째 날짜 자동 펼치기
			if (result?.slots_by_date?.length > 0) {
				expandedDates = new Set([result.slots_by_date[0].date]);
			}

			// 모니터링 통계 로드
			await loadMonitoringStats();
		} catch (e) {
			error = e instanceof Error ? e.message : '조회 실패';
		} finally {
			loading = false;
		}
	}

	// 모니터링 통계 로드
	async function loadMonitoringStats() {
		if (!item) return;

		loadingStats = true;
		try {
			const startDate = targetDate || getTodayDate();
			const endDate = addDays(startDate, daysAhead);

			monitoringStats = await monitoringEventApi.stats({
				biz_item_id: item.id,
				date_from: startDate,
				date_to: endDate
			});
		} catch (e) {
			console.error('Failed to load monitoring stats:', e);
		} finally {
			loadingStats = false;
		}
	}

	// 날짜 접기/펼치기 토글
	function toggleDate(date: string) {
		const newSet = new Set(expandedDates);
		if (newSet.has(date)) {
			newSet.delete(date);
		} else {
			newSet.add(date);
		}
		expandedDates = newSet;
	}

	// 전체 펼치기/접기
	function expandAll() {
		if (result?.slots_by_date) {
			expandedDates = new Set(result.slots_by_date.map((d) => d.date));
		}
	}

	function collapseAll() {
		expandedDates = new Set();
	}

	// 슬롯 상태에 따른 색상
	function getSlotBgColor(slot: SlotInfo): string {
		if (!slot.is_available) return 'bg-red-50';
		if (slot.remaining <= 2) return 'bg-yellow-50';
		return 'bg-green-50';
	}

	function getSlotTextColor(slot: SlotInfo): string {
		if (!slot.is_available) return 'text-red-600';
		if (slot.remaining <= 2) return 'text-yellow-600';
		return 'text-green-600';
	}

	function getSlotBorderColor(slot: SlotInfo): string {
		if (!slot.is_available) return 'border-red-200';
		if (slot.remaining <= 2) return 'border-yellow-200';
		return 'border-green-200';
	}

	// 진행률 계산
	function getProgress(booked: number, capacity: number): number {
		return capacity > 0 ? (booked / capacity) * 100 : 0;
	}

	// 진행률 바 색상
	function getProgressColor(booked: number, capacity: number): string {
		const ratio = capacity > 0 ? booked / capacity : 1;
		if (ratio >= 1) return 'bg-red-500';
		if (ratio >= 0.8) return 'bg-yellow-500';
		return 'bg-green-500';
	}

	// 날짜 요약 상태
	function getDateStatusColor(dateSlots: DateSlots): string {
		const { total_remaining, total_capacity } = dateSlots.summary;
		if (total_remaining === 0) return 'text-red-600';
		if (total_remaining / total_capacity < 0.2) return 'text-yellow-600';
		return 'text-green-600';
	}

	// URL 복사
	function copyUrl() {
		if (result) {
			const naverUrl = `https://booking.naver.com/booking/13/bizes/${result.business.business_id}/items/${result.biz_item.biz_item_id}`;
			navigator.clipboard.writeText(naverUrl);
		}
	}

	// 오늘 날짜
	function getTodayDate(): string {
		return new Date().toISOString().split('T')[0];
	}

	// 날짜 더하기
	function addDays(dateStr: string, days: number): string {
		const date = new Date(dateStr);
		date.setDate(date.getDate() + days);
		return date.toISOString().split('T')[0];
	}

	// 재고 발견률 계산
	function getAvailableRate(): string {
		if (!monitoringStats || monitoringStats.total_checks === 0) return '0';
		return ((monitoringStats.available_count / monitoringStats.total_checks) * 100).toFixed(1);
	}
</script>

{#if show}
	<div
		class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
		onclick={(e) => {
			if (e.target === e.currentTarget) onClose();
		}}
		onkeydown={(e) => {
			if (e.key === 'Escape') onClose();
		}}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
	>
		<div class="bg-white rounded-lg shadow-xl w-full max-w-5xl mx-4 max-h-[90vh] overflow-hidden">
			<!-- 헤더 -->
			<div class="p-4 border-b flex items-center justify-between bg-background">
				<div>
					<h3 class="text-lg font-semibold text-foreground">슬롯 조회</h3>
					{#if business && item}
						<p class="text-sm text-muted-foreground">{business.name} - {item.name}</p>
					{/if}
				</div>
				<button
					type="button"
					onclick={onClose}
					class="text-muted-foreground hover:text-muted-foreground transition-colors"
				>
					<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M6 18L18 6M6 6l12 12"
						/>
					</svg>
				</button>
			</div>

			<!-- 컨텐츠 -->
			<div class="p-4 overflow-y-auto" style="max-height: calc(90vh - 120px);">
				<!-- 옵션 및 조회 버튼 -->
				<div class="bg-background rounded-lg p-4 mb-4">
					<div class="flex flex-wrap items-center gap-4">
						<div class="flex items-center gap-2">
							<label class="text-sm text-foreground">시작일:</label>
							<input
								type="date"
								bind:value={targetDate}
								min={getTodayDate()}
								class="px-3 py-1.5 border border-border rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
							/>
						</div>

						<div class="flex items-center gap-2">
							<label class="text-sm text-foreground">조회 기간:</label>
							<select
								bind:value={daysAhead}
								class="px-3 py-1.5 border border-border rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
							>
								<option value={7}>7일</option>
								<option value={14}>14일</option>
								<option value={21}>21일</option>
								<option value={28}>28일</option>
								<option value={35}>35일</option>
							</select>
						</div>

						<button
							onclick={checkSlots}
							disabled={loading}
							class="ml-auto px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors text-sm"
						>
							{#if loading}
								<span class="flex items-center gap-2">
									<svg class="animate-spin h-4 w-4" viewBox="0 0 24 24">
										<circle
											class="opacity-25"
											cx="12"
											cy="12"
											r="10"
											stroke="currentColor"
											stroke-width="4"
											fill="none"
										></circle>
										<path
											class="opacity-75"
											fill="currentColor"
											d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
										></path>
									</svg>
									조회 중
								</span>
							{:else}
								조회
							{/if}
						</button>
					</div>
				</div>

				<!-- 에러 메시지 -->
				{#if error}
					<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
						<div class="flex items-center gap-2">
							<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
								/>
							</svg>
							<span>{error}</span>
						</div>
					</div>
				{/if}

				<!-- 조회 결과 -->
				{#if result}
					<!-- 요약 정보 -->
					<div class="bg-white rounded-lg border border-border p-4 mb-4">
						<div class="flex flex-wrap items-center justify-between gap-4">
							<div class="flex items-center gap-4">
								<div class="text-center px-4 py-2 bg-background rounded-lg">
									<p class="text-2xl font-bold text-foreground">{result.summary.total_slots}</p>
									<p class="text-xs text-muted-foreground">총 슬롯</p>
								</div>
								<div class="text-center px-4 py-2 bg-green-50 rounded-lg">
									<p class="text-2xl font-bold text-green-600">
										{result.summary.total_available_slots}
									</p>
									<p class="text-xs text-muted-foreground">예약 가능</p>
								</div>
								<div class="text-center px-4 py-2 bg-blue-50 rounded-lg">
									<p class="text-2xl font-bold text-blue-600">
										{result.summary.available_dates.length}
									</p>
									<p class="text-xs text-muted-foreground">예약 가능일</p>
								</div>
							</div>
							<div class="flex gap-2">
								<button
									onclick={copyUrl}
									class="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground border border-border rounded-lg hover:bg-muted transition-colors"
								>
									URL 복사
								</button>
								<button
									onclick={expandAll}
									class="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground border border-border rounded-lg hover:bg-muted transition-colors"
								>
									전체 펼치기
								</button>
								<button
									onclick={collapseAll}
									class="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground border border-border rounded-lg hover:bg-muted transition-colors"
								>
									전체 접기
								</button>
							</div>
						</div>
						<div class="mt-2 text-xs text-muted-foreground">
							조회 시각: {new Date(result.queried_at).toLocaleString('ko-KR')}
						</div>
					</div>

					<!-- 모니터링 이력 -->
					{#if item}
						<div class="bg-white rounded-lg border border-border p-4 mb-4">
							<h4 class="text-sm font-semibold text-foreground mb-3">모니터링 이력</h4>
							{#if loadingStats}
								<div class="text-muted-foreground text-sm">통계 로딩 중...</div>
							{:else if monitoringStats && monitoringStats.total_checks > 0}
								<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
									<div class="p-3 bg-background rounded-lg">
										<p class="text-xs text-muted-foreground">총 체크</p>
										<p class="text-lg font-bold text-foreground">
											{monitoringStats.total_checks.toLocaleString()}회
										</p>
									</div>
									<div class="p-3 bg-green-50 rounded-lg">
										<p class="text-xs text-muted-foreground">재고 발견</p>
										<p class="text-lg font-bold text-green-600">
											{monitoringStats.available_count}회
											<span class="text-sm font-normal">({getAvailableRate()}%)</span>
										</p>
									</div>
									<div class="p-3 bg-blue-50 rounded-lg">
										<p class="text-xs text-muted-foreground">평균 응답</p>
										<p class="text-lg font-bold text-blue-600">
											{monitoringStats.avg_response_time_ms
												? Math.round(monitoringStats.avg_response_time_ms)
												: '-'}ms
										</p>
									</div>
									<div class="p-3 bg-background rounded-lg">
										<p class="text-xs text-muted-foreground">마지막 체크</p>
										<p class="text-sm font-medium text-foreground">
											{monitoringStats.last_check_time
												? new Date(monitoringStats.last_check_time).toLocaleString('ko-KR')
												: '-'}
										</p>
									</div>
								</div>
							{:else}
								<div class="text-muted-foreground text-sm p-3 bg-background rounded-lg">
									이 상품에 대한 모니터링 이력이 없습니다.
								</div>
							{/if}
						</div>
					{/if}

					<!-- 날짜별 슬롯 -->
					<div class="space-y-2">
						{#each result.slots_by_date as dateSlots}
							<div class="bg-white rounded-lg border border-border overflow-hidden">
								<!-- 날짜 헤더 -->
								<button
									onclick={() => toggleDate(dateSlots.date)}
									class="w-full px-4 py-3 flex items-center justify-between hover:bg-muted transition-colors"
								>
									<div class="flex items-center gap-3">
										<svg
											class="w-4 h-4 text-muted-foreground transition-transform {expandedDates.has(
												dateSlots.date
											)
												? 'rotate-90'
												: ''}"
											fill="none"
											stroke="currentColor"
											viewBox="0 0 24 24"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												stroke-width="2"
												d="M9 5l7 7-7 7"
											/>
										</svg>
										<span class="font-medium text-foreground">
											{dateSlots.date} ({dateSlots.day_of_week})
										</span>
										{#if result.summary.available_dates.includes(dateSlots.date)}
											<span
												class="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 rounded-full"
											>
												예약가능
											</span>
										{/if}
									</div>
									<div class="flex items-center gap-4">
										<span class="{getDateStatusColor(dateSlots)} font-medium text-sm">
											남음 {dateSlots.summary.total_remaining}/{dateSlots.summary.total_capacity}
										</span>
										<div class="w-20 h-2 bg-secondary rounded-full overflow-hidden">
											<div
												class="{getProgressColor(
													dateSlots.summary.total_booked,
													dateSlots.summary.total_capacity
												)} h-full transition-all"
												style="width: {getProgress(
													dateSlots.summary.total_booked,
													dateSlots.summary.total_capacity
												)}%"
											></div>
										</div>
									</div>
								</button>

								<!-- 슬롯 목록 -->
								{#if expandedDates.has(dateSlots.date)}
									<div class="border-t border-border p-4">
										<div
											class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2"
										>
											{#each dateSlots.slots as slot}
												<div
													class="px-3 py-2 rounded-lg border {getSlotBgColor(slot)} {getSlotBorderColor(
														slot
													)}"
												>
													<div class="flex items-center justify-between mb-1">
														<span class="font-medium text-foreground text-sm">{slot.time}</span>
														<span class="{getSlotTextColor(slot)} text-sm font-semibold">
															{#if slot.is_available}
																{slot.remaining}석
															{:else}
																마감
															{/if}
														</span>
													</div>
													<div class="w-full h-1.5 bg-secondary rounded-full overflow-hidden">
														<div
															class="{getProgressColor(slot.booked, slot.capacity)} h-full transition-all"
															style="width: {getProgress(slot.booked, slot.capacity)}%"
														></div>
													</div>
													<div class="text-xs text-muted-foreground mt-1">
														{slot.booked}/{slot.capacity}
													</div>
												</div>
											{/each}
										</div>
									</div>
								{/if}
							</div>
						{/each}
					</div>

					<!-- 슬롯이 없을 때 -->
					{#if result.slots_by_date.length === 0}
						<div class="bg-background border border-border rounded-lg p-8 text-center">
							<svg
								class="w-12 h-12 text-muted-foreground mx-auto mb-4"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
								/>
							</svg>
							<p class="text-muted-foreground">조회 기간 내 슬롯이 없습니다</p>
						</div>
					{/if}
				{/if}

				<!-- 로딩 상태 -->
				{#if loading && !result}
					<div class="flex justify-center items-center h-48">
						<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
