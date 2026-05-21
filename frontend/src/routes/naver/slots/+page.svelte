<script lang="ts">
	import { slotApi } from '$lib/api';
	import type { SlotCheckResponse, DateSlots, SlotInfo } from '$lib/types';
	import { Search, ChevronRight, ChevronsDown, ChevronsUp } from 'lucide-svelte';
	import {
		getSlotBgColor,
		getSlotTextColor,
		getSlotBorderColor,
		getProgress,
		getProgressColor,
		getDateStatusColor
	} from '$lib/utils/slot-display';

	let url = $state('');
	let targetDate = $state('');
	let daysAhead = $state(14);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let result = $state<SlotCheckResponse | null>(null);
	let expandedDates = $state<Set<string>>(new Set());

	function getTodayDate(): string {
		return new Date().toISOString().split('T')[0];
	}

	async function checkSlots() {
		if (!url.trim()) {
			error = 'URL을 입력해주세요.';
			return;
		}

		loading = true;
		error = null;
		result = null;
		expandedDates = new Set();

		try {
			result = await slotApi.check({
				url: url.trim(),
				target_date: targetDate || undefined,
				days_ahead: daysAhead
			});

			// 첫 번째 날짜 자동 펼치기
			if (result.slots_by_date.length > 0) {
				expandedDates = new Set([result.slots_by_date[0].date]);
			}
		} catch (e) {
			if (e instanceof Error) {
				error = e.message;
			} else {
				error = '슬롯 조회에 실패했습니다.';
			}
		} finally {
			loading = false;
		}
	}

	function toggleDate(date: string) {
		const next = new Set(expandedDates);
		if (next.has(date)) {
			next.delete(date);
		} else {
			next.add(date);
		}
		expandedDates = next;
	}

	function expandAll() {
		if (result) {
			expandedDates = new Set(result.slots_by_date.map((d) => d.date));
		}
	}

	function collapseAll() {
		expandedDates = new Set();
	}


</script>

<div class="space-y-4">
	<!-- 조회 폼 -->
	<div class="card">
		<h3 class="text-base font-semibold text-foreground mb-4">슬롯 조회</h3>
		<form
			onsubmit={(e) => {
				e.preventDefault();
				checkSlots();
			}}
			class="space-y-3"
		>
			<div>
				<label for="slot-url" class="block text-sm font-medium text-foreground mb-1">
					네이버 예약 URL
				</label>
				<input
					id="slot-url"
					type="text"
					class="input"
					bind:value={url}
					placeholder="https://booking.naver.com/booking/13/bizes/.../items/..."
				/>
			</div>

			<div class="flex flex-wrap gap-4">
				<div>
					<label for="slot-start-date" class="block text-sm font-medium text-foreground mb-1">
						시작일 (선택)
					</label>
					<input
						id="slot-start-date"
						type="date"
						class="input"
						bind:value={targetDate}
						min={getTodayDate()}
					/>
				</div>

				<div>
					<label for="slot-days-ahead" class="block text-sm font-medium text-foreground mb-1">
						조회 기간
					</label>
					<select id="slot-days-ahead" class="input" bind:value={daysAhead}>
						<option value={7}>7일</option>
						<option value={14}>14일</option>
						<option value={21}>21일</option>
						<option value={28}>28일</option>
						<option value={35}>35일</option>
					</select>
				</div>

				<div class="flex items-end">
					<button
						type="submit"
						disabled={loading}
						class="btn btn-primary flex items-center gap-2"
					>
						{#if loading}
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
						{:else}
							<Search class="w-4 h-4" />
							조회
						{/if}
					</button>
				</div>
			</div>
		</form>
	</div>

	<!-- 에러 -->
	{#if error}
		<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg text-sm">
			{error}
		</div>
	{/if}

	<!-- 결과 -->
	{#if result}
		<!-- 요약 -->
		<div class="card">
			<div class="flex flex-wrap items-start justify-between gap-4">
				<div>
					<p class="text-base font-semibold text-foreground">{result.business.name}</p>
					<p class="text-sm text-muted-foreground">{result.biz_item.name}</p>
				</div>
				<div class="flex gap-3">
					<div class="text-center px-3 py-2 bg-background rounded-lg">
						<p class="text-xl font-bold text-foreground">{result.summary.total_slots}</p>
						<p class="text-xs text-muted-foreground">총 슬롯</p>
					</div>
					<div class="text-center px-3 py-2 bg-success-light rounded-lg">
						<p class="text-xl font-bold text-success">{result.summary.total_available_slots}</p>
						<p class="text-xs text-muted-foreground">예약 가능</p>
					</div>
					<div class="text-center px-3 py-2 bg-primary-light rounded-lg">
						<p class="text-xl font-bold text-primary">{result.summary.available_dates.length}</p>
						<p class="text-xs text-muted-foreground">가능일</p>
					</div>
				</div>
			</div>
			<div class="flex items-center justify-between mt-3 pt-3 border-t border-border">
				<p class="text-xs text-muted-foreground">
					조회: {new Date(result.queried_at).toLocaleString('ko-KR')}
				</p>
				<div class="flex gap-2">
					<button
						onclick={expandAll}
						class="flex items-center gap-1 px-2 py-1 text-xs text-muted-foreground hover:text-foreground border border-border rounded hover:bg-muted transition-colors"
					>
						<ChevronsDown class="w-3 h-3" />
						전체 펼치기
					</button>
					<button
						onclick={collapseAll}
						class="flex items-center gap-1 px-2 py-1 text-xs text-muted-foreground hover:text-foreground border border-border rounded hover:bg-muted transition-colors"
					>
						<ChevronsUp class="w-3 h-3" />
						전체 접기
					</button>
				</div>
			</div>
		</div>

		<!-- 날짜별 슬롯 -->
		{#if result.slots_by_date.length === 0}
			<div class="card text-center py-10">
				<p class="text-muted-foreground">조회 기간 내 슬롯이 없습니다.</p>
			</div>
		{:else}
			<div class="md:hidden space-y-3">
				{#each result.slots_by_date as dateSlots (dateSlots.date)}
					<article class="bg-white rounded-lg border border-border overflow-hidden">
						<!-- 날짜 헤더 -->
						<button
							onclick={() => toggleDate(dateSlots.date)}
							class="w-full px-3 py-3 flex items-start justify-between gap-3 hover:bg-muted transition-colors"
						>
							<div class="flex items-start gap-2 text-left">
								<ChevronRight
									class="w-4 h-4 mt-0.5 text-muted-foreground transition-transform {expandedDates.has(dateSlots.date) ? 'rotate-90' : ''}"
								/>
								<div>
									<span class="font-medium text-foreground text-sm">
										{dateSlots.date} ({dateSlots.day_of_week})
									</span>
									{#if result.summary.available_dates.includes(dateSlots.date)}
										<span class="ml-1 px-2 py-0.5 text-xs font-medium bg-success-light text-success rounded-full">
											예약가능
										</span>
									{/if}
									<p class="{getDateStatusColor(dateSlots)} font-medium text-sm mt-1">
										남음 {dateSlots.summary.total_remaining}/{dateSlots.summary.total_capacity}
									</p>
								</div>
							</div>
							<div class="w-16 h-2 bg-secondary rounded-full overflow-hidden mt-2 shrink-0">
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
						</button>

						<!-- 슬롯 목록 -->
						{#if expandedDates.has(dateSlots.date)}
							<div class="border-t border-border p-4">
								<div class="grid grid-cols-1 gap-2">
									{#each dateSlots.slots as slot (slot.time)}
										<div
											class="px-3 py-2 rounded-lg border {getSlotBgColor(slot)} {getSlotBorderColor(slot)}"
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
					</article>
				{/each}
			</div>

			<div class="hidden md:block overflow-x-auto rounded-lg border border-border bg-white">
				<table class="w-full text-sm">
					<thead class="bg-background">
						<tr>
							<th class="px-4 py-2 text-left font-medium text-muted-foreground">날짜</th>
							<th class="px-4 py-2 text-left font-medium text-muted-foreground">상태</th>
							<th class="px-4 py-2 text-left font-medium text-muted-foreground">잔여/정원</th>
							<th class="px-4 py-2 text-left font-medium text-muted-foreground">진행률</th>
							<th class="px-4 py-2 text-left font-medium text-muted-foreground">슬롯</th>
							<th class="px-4 py-2 text-left font-medium text-muted-foreground">작업</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each result.slots_by_date as dateSlots (dateSlots.date)}
							<tr class="hover:bg-muted">
								<td class="px-4 py-3">
									<div class="font-medium text-foreground">
										{dateSlots.date} ({dateSlots.day_of_week})
									</div>
								</td>
								<td class="px-4 py-3">
									{#if result.summary.available_dates.includes(dateSlots.date)}
										<span class="px-2 py-0.5 text-xs font-medium bg-success-light text-success rounded-full">
											예약가능
										</span>
									{:else}
										<span class="px-2 py-0.5 text-xs font-medium bg-secondary text-muted-foreground rounded-full">
											마감
										</span>
									{/if}
								</td>
								<td class="px-4 py-3">
									<span class="{getDateStatusColor(dateSlots)} font-medium">
										{dateSlots.summary.total_remaining}/{dateSlots.summary.total_capacity}
									</span>
								</td>
								<td class="px-4 py-3">
									<div class="w-24 h-2 bg-secondary rounded-full overflow-hidden">
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
								</td>
								<td class="px-4 py-3 text-muted-foreground">
									{dateSlots.slots.length}개
								</td>
								<td class="px-4 py-3">
									<button
										onclick={() => toggleDate(dateSlots.date)}
										class="btn btn-secondary btn-xs"
									>
										{expandedDates.has(dateSlots.date) ? '접기' : '보기'}
									</button>
								</td>
							</tr>
							{#if expandedDates.has(dateSlots.date)}
								<tr class="bg-background">
									<td colspan="6" class="px-4 py-3">
										<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
											{#each dateSlots.slots as slot (slot.time)}
												<div
													class="px-3 py-2 rounded-lg border {getSlotBgColor(slot)} {getSlotBorderColor(slot)}"
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
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/if}
</div>
