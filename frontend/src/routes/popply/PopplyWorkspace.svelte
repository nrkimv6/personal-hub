<script lang="ts">
	import { onMount } from 'svelte';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';
	import { Button } from '$lib/components/ui';
	import {
		popplyReservationApi,
		type PopplySchedule,
		type PopplyTarget
	} from '$lib/api/popplyReservation';
	import type { MonitoringEvent } from '$lib/types';
	import { Plus, RefreshCw, Search, X } from 'lucide-svelte';

	type ActiveTab = 'schedules' | 'history';

	interface Props {
		view?: string | null;
		sub?: string | null;
		unified?: boolean;
	}

	let { view = null, sub = null, unified = false }: Props = $props();

	type PopplySlot = {
		reservationDate?: string;
		reservationTime?: string;
		reservationStartTime?: string;
		currentAvailableGuests?: number;
		scheduleGroup?: string;
		reservationScheduleId?: number | string;
		id?: number | string;
		label?: string;
		availableCount?: number;
		storeId?: string;
	};

	let activeTab: ActiveTab = 'schedules';
	let targets: PopplyTarget[] = [];
	let schedules: PopplySchedule[] = [];
	let historyEvents: MonitoringEvent[] = [];
	let sourceUrl = '';
	let targetName = '';
	let selectedTargetId = '';
	let scheduleDate = '';
	let loading = false;
	let historyLoading = false;
	let error = '';
	let historyError = '';
	let historyLoadedOnce = false;
	let selectedEvent: MonitoringEvent | null = null;
	let showDetailModal = false;

	function normalizePopplyTab(value: string | null | undefined): ActiveTab {
		if (value === 'history') return 'history';
		return 'schedules';
	}

	$: {
		if (unified) activeTab = normalizePopplyTab(sub ?? view);
	}

	let popplyTabs = [
		{ id: 'schedules', label: '일정', href: undefined as string | undefined },
		{ id: 'history', label: '실행내역', href: undefined as string | undefined }
	];
	$: popplyTabs = [
		{ id: 'schedules', label: '일정', href: unified ? '/monitoring?type=popply&view=schedules' : undefined },
		{ id: 'history', label: '실행내역', href: unified ? '/monitoring?type=popply&view=history' : undefined }
	];
	const fieldClass = 'h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground';

	let historyPage = 1;
	let historyPageSize = 30;
	let historyTotal = 0;
	let historyTotalPages = 1;
	let historyFilters = {
		status: '',
		date_from: getTodayDate(),
		date_to: ''
	};

	function getTodayDate(): string {
		return new Date().toISOString().split('T')[0];
	}

	async function load() {
		loading = true;
		error = '';
		try {
			[targets, schedules] = await Promise.all([
				popplyReservationApi.listTargets(),
				popplyReservationApi.listSchedules()
			]);
			if (!selectedTargetId && targets[0]) selectedTargetId = String(targets[0].id);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			loading = false;
		}
	}

	async function loadHistory(showLoading = true) {
		if (showLoading) historyLoading = true;
		historyError = '';
		try {
			const result = await popplyReservationApi.listEvents({
				status: historyFilters.status || undefined,
				date_from: historyFilters.date_from || undefined,
				date_to: historyFilters.date_to || undefined,
				page: historyPage,
				page_size: historyPageSize
			});
			historyEvents = result.items;
			historyTotal = result.total;
			historyTotalPages = result.total_pages;
		} catch (err) {
			historyError = err instanceof Error ? err.message : String(err);
		} finally {
			if (showLoading) historyLoading = false;
		}
	}

	async function refreshAll() {
		await load();
		if (activeTab === 'history') await loadHistory(false);
	}

	function selectTab(tab: ActiveTab) {
		activeTab = tab;
		if (tab === 'history' && !historyLoadedOnce) {
			historyLoadedOnce = true;
			void loadHistory();
		}
	}

	async function createTarget() {
		if (!sourceUrl.trim()) return;
		await popplyReservationApi.createTarget({
			source_url: sourceUrl.trim(),
			name: targetName.trim() || undefined
		});
		sourceUrl = '';
		targetName = '';
		await load();
	}

	async function createSchedule() {
		if (!selectedTargetId || !scheduleDate) return;
		await popplyReservationApi.createSchedules({
			biz_item_id: Number(selectedTargetId),
			dates: [scheduleDate]
		});
		scheduleDate = '';
		await load();
	}

	async function toggleSchedule(schedule: PopplySchedule) {
		if (schedule.is_enabled) await popplyReservationApi.disableSchedule(schedule.id);
		else await popplyReservationApi.enableSchedule(schedule.id);
		await load();
	}

	async function checkNow(schedule: PopplySchedule) {
		await popplyReservationApi.checkNow(schedule.id);
		await load();
		await loadHistory(false);
	}

	function searchHistory() {
		historyLoadedOnce = true;
		historyPage = 1;
		void loadHistory();
	}

	function clearHistoryFilters() {
		historyFilters = {
			status: '',
			date_from: getTodayDate(),
			date_to: ''
		};
		historyLoadedOnce = true;
		historyPage = 1;
		void loadHistory();
	}

	$effect(() => {
		if (activeTab === 'history') selectTab('history');
	});

	function parseSlotsInfo(event: MonitoringEvent): PopplySlot[] {
		if (!Array.isArray(event.slots_info)) return [];
		return event.slots_info
			.filter((slot) => typeof slot === 'object' && slot !== null)
			.map((slot) => slot as PopplySlot);
	}

	function getSlotLabel(slot: PopplySlot): string {
		return slot.reservationTime || slot.reservationStartTime || slot.label || '-';
	}

	function getSlotAvailableCount(slot: PopplySlot): number {
		return Number(slot.currentAvailableGuests ?? slot.availableCount ?? 0);
	}

	function getStatusLabel(status: string): string {
		const labels: Record<string, string> = {
			available: '예약가능',
			no_slots: '매진',
			error: '오류',
			success: '성공'
		};
		return labels[status] || status;
	}

	function getStatusClass(status: string): string {
		if (status === 'available' || status === 'success') return 'bg-emerald-50 text-emerald-700';
		if (status === 'error') return 'bg-red-50 text-red-700';
		return 'bg-slate-100 text-slate-700';
	}

	function formatDateTime(value: string | null): string {
		if (!value) return '-';
		return new Date(value).toLocaleString('ko-KR');
	}

	function formatMs(value: number | null): string {
		if (value === null) return '-';
		if (value < 1000) return `${value.toFixed(0)}ms`;
		return `${(value / 1000).toFixed(2)}s`;
	}

	function formatJson(value: unknown): string {
		try {
			return JSON.stringify(value, null, 2);
		} catch {
			return String(value);
		}
	}

	function eventEnvelope(event: MonitoringEvent): Record<string, unknown> {
		return {
			id: event.id,
			schedule_id: event.schedule_id,
			timestamp: event.timestamp,
			event_type: event.event_type,
			status: event.status,
			available_count: event.available_count,
			response_time_ms: event.response_time_ms,
			fetch_method: event.fetch_method,
			error_message: event.error_message,
			schedule_date: event.schedule_date,
			biz_item_name: event.biz_item_name,
			business_name: event.business_name,
			slots_info: event.slots_info
		};
	}

	function openEventDetail(event: MonitoringEvent) {
		selectedEvent = event;
		showDetailModal = true;
	}

	function closeEventDetail() {
		showDetailModal = false;
		selectedEvent = null;
	}

	onMount(async () => {
		await load();
	});
</script>

<svelte:head>
	<title>POPPLY 예약</title>
</svelte:head>

{#snippet headerActions()}
	<Button variant="outline" size="sm" onclick={refreshAll} disabled={loading || historyLoading}>
		<RefreshCw size={16} class={(loading || historyLoading) ? 'animate-spin' : ''} />
		새로고침
	</Button>
{/snippet}

{#snippet popplyToolbar()}
	{#if activeTab === 'schedules'}
		<div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px_auto]">
			<input class={fieldClass} bind:value={sourceUrl} placeholder="POPPLY 예약 URL" />
			<input class={fieldClass} bind:value={targetName} placeholder="이름" />
			<Button variant="primary" size="sm" onclick={createTarget}>
				<Plus size={16} />
				등록
			</Button>
		</div>
		<div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_auto]">
			<select class={fieldClass} bind:value={selectedTargetId}>
				{#each targets as target}
					<option value={target.id}>{target.name} · {target.store_id}</option>
				{/each}
			</select>
			<input class={fieldClass} type="date" bind:value={scheduleDate} />
			<Button variant="primary" size="sm" onclick={createSchedule}>
				<Plus size={16} />
				일정 추가
			</Button>
		</div>
	{:else}
		<div class="grid gap-3 md:grid-cols-[160px_180px_180px_auto_auto]">
			<select class={fieldClass} bind:value={historyFilters.status}>
				<option value="">전체</option>
				<option value="available">예약가능</option>
				<option value="no_slots">매진</option>
				<option value="error">오류</option>
			</select>
			<input class={fieldClass} type="date" bind:value={historyFilters.date_from} />
			<input class={fieldClass} type="date" bind:value={historyFilters.date_to} />
			<Button variant="primary" size="sm" onclick={searchHistory}>
				<Search size={16} />
				검색
			</Button>
			<Button variant="outline" size="sm" onclick={clearHistoryFilters}>
				<X size={16} />
				초기화
			</Button>
		</div>
	{/if}
{/snippet}

<TabbedPageLayout
	title="POPPLY 예약"
	actions={headerActions}
	toolbar={popplyToolbar}
	primaryTabs={popplyTabs}
	bind:activePrimaryTab={activeTab}
	primaryQueryParam={unified ? undefined : ''}
	primaryUrlBased={unified}
	primaryReplaceState={false}
	density="compact"
	containerClass="space-y-3 p-4 md:p-6"
>

	{#if error}
		<p class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>
	{/if}

	{#if activeTab === 'schedules'}
		<section class="overflow-hidden rounded-lg border border-border">
			<table class="w-full text-left text-sm">
				<thead class="bg-muted text-muted-foreground">
					<tr>
						<th class="p-3">대상</th>
						<th class="p-3">날짜</th>
						<th class="p-3">상태</th>
						<th class="p-3">마지막 체크</th>
						<th class="p-3"></th>
					</tr>
				</thead>
				<tbody>
					{#each schedules as schedule}
						<tr class="border-t border-border">
							<td class="p-3">{schedule.item_name}</td>
							<td class="p-3">{schedule.date}</td>
							<td class="p-3">{schedule.is_enabled ? (schedule.last_event_status ?? 'idle') : 'disabled'}</td>
							<td class="p-3">{schedule.last_check_time ?? '-'}</td>
							<td class="space-x-2 p-3 text-right">
								<button class="rounded-md border border-input px-2 py-1 text-sm" on:click={() => toggleSchedule(schedule)}>
									{schedule.is_enabled ? '비활성' : '활성'}
								</button>
								<button class="rounded-md border border-input px-2 py-1 text-sm" on:click={() => checkNow(schedule)}>체크</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</section>
	{:else}
		{#if historyError}
			<p class="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{historyError}</p>
		{:else if historyLoading}
			<div class="rounded-lg border border-border p-8 text-center text-sm text-muted-foreground">불러오는 중</div>
		{:else if historyEvents.length === 0}
			<div class="rounded-lg border border-border p-8 text-center text-sm text-muted-foreground">실행내역이 없습니다.</div>
		{:else}
			<section class="overflow-hidden rounded-lg border border-border">
				<div class="border-b border-border bg-muted px-3 py-2 text-sm text-muted-foreground">
					총 {historyTotal}건 중 {(historyPage - 1) * historyPageSize + 1} - {Math.min(historyPage * historyPageSize, historyTotal)}
				</div>
				<div class="overflow-x-auto">
					<table class="w-full min-w-[960px] text-left text-sm">
						<thead class="bg-muted text-muted-foreground">
							<tr>
								<th class="p-3">시간</th>
								<th class="p-3">대상</th>
								<th class="p-3">날짜</th>
								<th class="p-3">상태</th>
								<th class="p-3">슬롯</th>
								<th class="p-3">응답</th>
								<th class="p-3">오류</th>
								<th class="p-3"></th>
							</tr>
						</thead>
						<tbody>
							{#each historyEvents as event (event.id)}
								{@const slots = parseSlotsInfo(event)}
								<tr class="border-t border-border align-top">
									<td class="whitespace-nowrap p-3 text-muted-foreground">{formatDateTime(event.timestamp)}</td>
									<td class="p-3">
										<div class="font-medium text-foreground">{event.biz_item_name || '-'}</div>
										<div class="text-xs text-muted-foreground">{event.business_name || '-'}</div>
										<div class="text-xs text-muted-foreground">#{event.schedule_id}</div>
									</td>
									<td class="whitespace-nowrap p-3">{event.schedule_date || '-'}</td>
									<td class="p-3">
										<span class="rounded px-2 py-1 text-xs {getStatusClass(event.status)}">
											{getStatusLabel(event.status)}
										</span>
										<div class="mt-1 text-xs text-muted-foreground">{event.available_count}개</div>
									</td>
									<td class="max-w-[300px] p-3 text-xs text-muted-foreground">
										{#if slots.length === 0}
											-
										{:else}
											<div class="space-y-1">
												{#each slots.slice(0, 3) as slot}
													<div>
														{slot.reservationDate || event.schedule_date || '-'} · {getSlotLabel(slot)} · 잔여 {getSlotAvailableCount(slot)}
													</div>
												{/each}
												{#if slots.length > 3}
													<div class="text-muted-foreground">외 {slots.length - 3}개</div>
												{/if}
											</div>
										{/if}
									</td>
									<td class="whitespace-nowrap p-3 text-muted-foreground">
										<div>{formatMs(event.response_time_ms)}</div>
										<div class="text-xs text-muted-foreground">{event.fetch_method || '-'}</div>
									</td>
									<td class="max-w-[160px] truncate p-3 text-red-600" title={event.error_message || ''}>
										{event.error_message || '-'}
									</td>
									<td class="p-3 text-right">
										<button class="rounded-md border border-input px-2 py-1 text-sm" on:click={() => openEventDetail(event)}>
											상세
										</button>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if historyTotalPages > 1}
					<div class="flex items-center justify-between border-t border-border px-3 py-2">
						<div class="text-sm text-muted-foreground">{historyPage} / {historyTotalPages}</div>
						<div class="flex gap-2">
							<button
								class="rounded-md border border-input px-3 py-1 text-sm disabled:opacity-50"
								disabled={historyPage === 1}
								on:click={() => {
									historyPage -= 1;
									void loadHistory();
								}}
							>
								이전
							</button>
							<button
								class="rounded-md border border-input px-3 py-1 text-sm disabled:opacity-50"
								disabled={historyPage === historyTotalPages}
								on:click={() => {
									historyPage += 1;
									void loadHistory();
								}}
							>
								다음
							</button>
						</div>
					</div>
				{/if}
			</section>
		{/if}
	{/if}
</TabbedPageLayout>

{#if showDetailModal && selectedEvent}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
		role="dialog"
		aria-modal="true"
		tabindex="-1"
		on:click={(event) => {
			if (event.target === event.currentTarget) closeEventDetail();
		}}
		on:keydown={(event) => {
			if (event.key === 'Escape') closeEventDetail();
		}}
	>
		<div class="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded bg-white shadow-xl">
			<div class="flex items-center justify-between border-b px-4 py-3">
				<div>
					<h2 class="text-base font-semibold text-slate-900">POPPLY 실행 상세</h2>
					<p class="text-sm text-slate-500">
						#{selectedEvent.id} · schedule #{selectedEvent.schedule_id} · {formatDateTime(selectedEvent.timestamp)}
					</p>
				</div>
				<button class="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100" on:click={closeEventDetail}>
					닫기
				</button>
			</div>
			<div class="grid gap-3 border-b p-4 text-sm md:grid-cols-4">
				<div>
					<div class="text-xs text-slate-500">상태</div>
					<div class="font-medium">{getStatusLabel(selectedEvent.status)}</div>
				</div>
				<div>
					<div class="text-xs text-slate-500">잔여</div>
					<div class="font-medium">{selectedEvent.available_count}개</div>
				</div>
				<div>
					<div class="text-xs text-slate-500">응답시간</div>
					<div class="font-medium">{formatMs(selectedEvent.response_time_ms)}</div>
				</div>
				<div>
					<div class="text-xs text-slate-500">조회 방식</div>
					<div class="font-medium">{selectedEvent.fetch_method || '-'}</div>
				</div>
			</div>
			<div class="space-y-4 overflow-auto p-4">
				{#if selectedEvent.error_message}
					<section>
						<h3 class="mb-2 text-sm font-semibold text-red-700">오류</h3>
						<pre class="whitespace-pre-wrap rounded bg-red-50 p-3 text-xs text-red-700">{selectedEvent.error_message}</pre>
					</section>
				{/if}
				<section>
					<h3 class="mb-2 text-sm font-semibold text-slate-900">slots_info</h3>
					<pre class="max-h-72 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-100">{formatJson(selectedEvent.slots_info)}</pre>
				</section>
				<section>
					<h3 class="mb-2 text-sm font-semibold text-slate-900">event envelope</h3>
					<pre class="max-h-72 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-100">{formatJson(eventEnvelope(selectedEvent))}</pre>
				</section>
			</div>
		</div>
	</div>
{/if}
