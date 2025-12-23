<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { eventApi } from '$lib/api';
	import type { Event, EventCreate, EventUpdate } from '$lib/types';

	let events: Event[] = [];
	let total = 0;
	let page = 1;
	let pageSize = 20;
	let loading = true;
	let error: string | null = null;

	// 탭 모드: 전체 / 이벤트 / 팝업
	type TabMode = 'all' | 'event' | 'popup';
	let activeTab: TabMode = 'all';

	// 필터
	let filterEventStatus: string | null = 'ongoing';  // 기본: 진행 중
	let filterBookmarked: boolean | null = null;
	let filterUrlType: string | null = null;
	let filterSourceType: string | null = null;
	let sortBy = 'event_end';
	let sortOrder = 'asc';
	let includeUnknownPeriod = false;

	// 이벤트 상태 옵션
	const eventStatusOptions = [
		{ value: 'ongoing', label: '진행 중', color: 'bg-green-100 text-green-700' },
		{ value: 'upcoming', label: '예정', color: 'bg-blue-100 text-blue-700' },
		{ value: 'ended', label: '종료', color: 'bg-gray-100 text-gray-600' },
		{ value: 'cancelled', label: '취소됨', color: 'bg-red-100 text-red-600' }
	];

	// URL 타입 옵션
	const urlTypeOptions = [
		{ value: 'google_form', label: '구글 폼' },
		{ value: 'naver_form', label: '네이버 폼' },
		{ value: 'shop', label: '쇼핑몰' },
		{ value: 'survey', label: '설문조사' },
		{ value: 'sns', label: 'SNS' },
		{ value: 'other', label: '기타' }
	];

	// 모달 상태
	let showEventModal = false;
	let editingEvent: Event | null = null;
	let eventForm: EventCreate = {
		title: '',
		event_type: 'event'
	};
	let isSaving = false;

	// 탭 변경
	function switchTab(tab: TabMode) {
		activeTab = tab;
		page = 1;
		if (tab === 'event') {
			filterEventStatus = 'ongoing';
		} else if (tab === 'popup') {
			filterEventStatus = 'ongoing_or_upcoming';
		} else {
			filterEventStatus = null;
		}
		fetchEvents();
	}

	// 이벤트 목록 조회
	async function fetchEvents() {
		loading = true;
		try {
			const params: Record<string, unknown> = {
				page,
				page_size: pageSize,
				sort_by: sortBy,
				sort_order: sortOrder
			};

			// 탭에 따른 event_type 필터
			if (activeTab === 'event') {
				params.event_type = 'event';
			} else if (activeTab === 'popup') {
				params.event_type = 'popup';
			}

			// 추가 필터
			if (filterEventStatus) params.event_status = filterEventStatus;
			if (filterBookmarked !== null) params.is_bookmarked = filterBookmarked;
			if (filterUrlType) params.url_type = filterUrlType;
			if (filterSourceType) params.source_type = filterSourceType;
			if (includeUnknownPeriod) params.include_unknown_period = true;

			const response = await eventApi.list(params);
			events = response.items;
			total = response.total;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	// 이벤트 상태 필터 변경
	function setEventStatusFilter(status: string | null) {
		filterEventStatus = filterEventStatus === status ? null : status;
		page = 1;
		fetchEvents();
	}

	// 기간 미정 포함 토글
	function toggleIncludeUnknownPeriod() {
		includeUnknownPeriod = !includeUnknownPeriod;
		page = 1;
		fetchEvents();
	}

	// 북마크만 보기 토글
	function toggleBookmarkedFilter() {
		filterBookmarked = filterBookmarked === true ? null : true;
		page = 1;
		fetchEvents();
	}

	// 페이지 이동
	function prevPage() {
		if (page > 1) {
			page--;
			fetchEvents();
		}
	}

	function nextPage() {
		if (page * pageSize < total) {
			page++;
			fetchEvents();
		}
	}

	// 새 이벤트 생성 모달 열기
	function openCreateModal() {
		editingEvent = null;
		eventForm = {
			title: '',
			event_type: activeTab === 'popup' ? 'popup' : 'event',
			event_url: '',
			event_start: '',
			event_end: '',
			organizer: '',
			summary: '',
			location_venue: '',
			location_address: ''
		};
		showEventModal = true;
	}

	// 수정 모달 열기
	function openEditModal(event: Event) {
		editingEvent = event;
		eventForm = {
			title: event.title,
			event_type: event.event_type,
			event_url: event.event_url || '',
			event_start: event.event_start || '',
			event_end: event.event_end || '',
			organizer: event.organizer || '',
			summary: event.summary || '',
			location_venue: event.location_venue || '',
			location_address: event.location_address || '',
			announcement_date: event.announcement_date || '',
			prizes: event.prizes || [],
			winner_count: event.winner_count,
			purchase_required: event.purchase_required,
			user_note: event.user_note || ''
		};
		showEventModal = true;
	}

	// 모달 닫기
	function closeModal() {
		showEventModal = false;
		editingEvent = null;
	}

	// 이벤트 저장
	async function saveEvent() {
		if (!eventForm.title.trim()) {
			alert('제목을 입력해주세요.');
			return;
		}
		isSaving = true;
		try {
			if (editingEvent) {
				const updateData: EventUpdate = { ...eventForm };
				await eventApi.update(editingEvent.id, updateData);
			} else {
				await eventApi.create(eventForm);
			}
			closeModal();
			await fetchEvents();
		} catch (e) {
			alert('저장 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		} finally {
			isSaving = false;
		}
	}

	// 이벤트 삭제
	async function deleteEvent(id: number) {
		if (!confirm('이 이벤트를 삭제하시겠습니까?')) return;
		try {
			await eventApi.delete(id);
			await fetchEvents();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	// 북마크 토글
	async function toggleBookmark(event: Event, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await eventApi.toggleBookmark(event.id);
			event.is_bookmarked = result.is_bookmarked;
			events = [...events];
		} catch (err) {
			console.error('북마크 토글 실패:', err);
		}
	}

	// 참여 완료 토글
	async function toggleParticipate(event: Event, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await eventApi.toggleParticipate(event.id);
			event.is_participated = result.is_participated;
			events = [...events];
		} catch (err) {
			console.error('참여 완료 토글 실패:', err);
		}
	}

	// 날짜 포맷팅
	function formatDate(dateStr: string | null): string {
		if (!dateStr) return '-';
		try {
			const date = new Date(dateStr);
			return date.toLocaleDateString('ko-KR', {
				month: 'short',
				day: 'numeric'
			});
		} catch {
			return '-';
		}
	}

	// 오늘 마감 여부
	function isEndingToday(event: Event): boolean {
		if (!event.event_end) return false;
		const today = new Date().toISOString().split('T')[0];
		return event.event_end === today;
	}

	// 기간 미정 여부
	function isUnknownPeriod(event: Event): boolean {
		return !event.event_end;
	}

	// D-Day 계산
	function getDaysRemaining(event: Event): string {
		if (event.days_remaining === null || event.days_remaining === undefined) return '';
		if (event.days_remaining === 0) return 'D-Day';
		if (event.days_remaining > 0) return `D-${event.days_remaining}`;
		return `D+${Math.abs(event.days_remaining)}`;
	}

	// 이벤트 상태 배지 색상
	function getEventStatusColor(status: string): string {
		switch (status) {
			case 'ongoing': return 'bg-green-100 text-green-700';
			case 'upcoming': return 'bg-blue-100 text-blue-700';
			case 'ended': return 'bg-gray-100 text-gray-600';
			case 'cancelled': return 'bg-red-100 text-red-600';
			default: return 'bg-gray-100 text-gray-600';
		}
	}

	// URL 타입 라벨
	function getUrlTypeLabel(urlType: string | null): string {
		if (!urlType) return '-';
		const option = urlTypeOptions.find(o => o.value === urlType);
		return option?.label || urlType;
	}

	// 텍스트 자르기
	function truncate(text: string | null, maxLength: number): string {
		if (!text) return '';
		if (text.length <= maxLength) return text;
		return text.slice(0, maxLength) + '...';
	}

	onMount(() => {
		fetchEvents();
	});
</script>

<div class="p-4 md:p-6">
	<!-- 헤더 -->
	<div class="mb-4 md:mb-6 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
		<div class="flex items-center justify-between sm:justify-start gap-3">
			<h2 class="text-xl md:text-2xl font-bold text-gray-900">이벤트 관리</h2>
			<button
				onclick={openCreateModal}
				class="btn btn-primary btn-sm"
			>
				+ 새 이벤트
			</button>
		</div>

		<!-- 필터 요약 -->
		<div class="flex items-center gap-2 text-sm text-gray-600">
			<span>총 {total}건</span>
			{#if filterBookmarked}
				<span class="text-yellow-600">(북마크만)</span>
			{/if}
			{#if includeUnknownPeriod}
				<span class="text-amber-600">(기간미정 포함)</span>
			{/if}
		</div>
	</div>

	<!-- 탭 -->
	<div class="mb-4 border-b border-gray-200">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('all')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'all' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				전체
			</button>
			<button
				onclick={() => switchTab('event')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'event' ? 'border-purple-600 text-purple-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				이벤트
			</button>
			<button
				onclick={() => switchTab('popup')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'popup' ? 'border-pink-600 text-pink-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				팝업
			</button>
		</nav>
	</div>

	<!-- 필터 영역 -->
	<div class="mb-4 flex flex-wrap gap-2 items-center">
		<!-- 이벤트 상태 필터 -->
		<span class="text-sm text-gray-500">상태:</span>
		{#each eventStatusOptions as opt}
			<button
				onclick={() => setEventStatusFilter(opt.value)}
				class="px-3 py-1 text-sm rounded-full transition-colors {filterEventStatus === opt.value ? opt.color + ' ring-2 ring-offset-1 ring-gray-400' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
			>
				{opt.label}
			</button>
		{/each}

		<span class="text-gray-300 mx-1">|</span>

		<!-- 기간 미정 포함 -->
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={includeUnknownPeriod}
				onchange={toggleIncludeUnknownPeriod}
				class="w-4 h-4 text-amber-600 rounded border-gray-300 focus:ring-amber-500"
			/>
			<span class="text-sm text-gray-600">기간 미정 포함</span>
		</label>

		<!-- 북마크만 -->
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={filterBookmarked === true}
				onchange={toggleBookmarkedFilter}
				class="w-4 h-4 text-yellow-600 rounded border-gray-300 focus:ring-yellow-500"
			/>
			<span class="text-sm text-gray-600">북마크만</span>
		</label>
	</div>

	{#if loading}
		<div class="flex justify-center items-center h-64">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
		</div>
	{:else if error}
		<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
			{error}
		</div>
	{:else if events.length === 0}
		<div class="text-center py-12 text-gray-500">
			<p class="text-lg">등록된 이벤트가 없습니다</p>
			<p class="text-sm mt-2">새 이벤트를 등록하면 여기에 표시됩니다</p>
			<button onclick={openCreateModal} class="mt-4 btn btn-primary btn-sm">
				+ 새 이벤트 등록
			</button>
		</div>
	{:else}
		<!-- 이벤트 테이블 -->
		<div class="bg-white rounded-lg border border-gray-200 overflow-hidden mb-6">
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">상태</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">유형</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[200px]">제목</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">기간</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">D-Day</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">주최</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">URL 타입</th>
							{#if activeTab === 'popup'}
								<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[150px]">위치</th>
							{/if}
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">출처</th>
							<th class="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">북마크</th>
							<th class="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">참여</th>
							<th class="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each events as event (event.id)}
							<tr
								class="cursor-pointer transition-colors {isEndingToday(event) ? 'bg-orange-100 hover:bg-orange-200 font-semibold' : isUnknownPeriod(event) ? 'bg-amber-50 hover:bg-amber-100' : 'hover:bg-gray-50'}"
								onclick={() => openEditModal(event)}
							>
								<!-- 상태 -->
								<td class="px-3 py-3">
									<span class="px-2 py-1 text-xs rounded-full {getEventStatusColor(event.event_status)}">
										{eventStatusOptions.find(o => o.value === event.event_status)?.label || event.event_status}
									</span>
								</td>
								<!-- 유형 -->
								<td class="px-3 py-3">
									<span class="px-2 py-1 text-xs rounded {event.event_type === 'popup' ? 'bg-pink-100 text-pink-700' : event.event_type === 'event' ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'}">
										{event.event_type === 'popup' ? '팝업' : event.event_type === 'event' ? '이벤트' : event.event_type}
									</span>
								</td>
								<!-- 제목 -->
								<td class="px-3 py-3 max-w-[200px]">
									<span class="block truncate text-sm font-medium text-gray-900" title={event.title}>
										{event.title}
									</span>
									{#if event.summary}
										<span class="block truncate text-xs text-gray-500" title={event.summary}>
											{truncate(event.summary, 30)}
										</span>
									{/if}
								</td>
								<!-- 기간 -->
								<td class="px-3 py-3 text-sm text-gray-600 whitespace-nowrap">
									{#if event.event_end}
										<div class="flex flex-col gap-0.5">
											{#if event.event_start}
												<span class="text-xs text-gray-500">{formatDate(event.event_start)}</span>
											{/if}
											{#if isEndingToday(event)}
												<span class="text-xs font-bold text-orange-600 bg-orange-50 px-1 rounded">오늘 마감!</span>
											{:else}
												<span class="text-xs text-gray-500">~ {formatDate(event.event_end)}</span>
											{/if}
										</div>
									{:else if event.event_start}
										<div class="flex flex-col gap-0.5">
											<span class="text-xs text-gray-500">{formatDate(event.event_start)} ~</span>
											<span class="text-xs text-amber-600 bg-amber-50 px-1 rounded">기간 미정</span>
										</div>
									{:else}
										<span class="text-xs text-amber-600 bg-amber-50 px-1 rounded">기간 미정</span>
									{/if}
								</td>
								<!-- D-Day -->
								<td class="px-3 py-3 text-center">
									{#if event.days_remaining !== null && event.days_remaining !== undefined}
										<span class="text-sm font-medium {event.days_remaining === 0 ? 'text-orange-600' : event.days_remaining > 0 ? 'text-blue-600' : 'text-gray-400'}">
											{getDaysRemaining(event)}
										</span>
									{:else}
										<span class="text-gray-400">-</span>
									{/if}
								</td>
								<!-- 주최 -->
								<td class="px-3 py-3 text-sm text-gray-600 max-w-[100px]">
									<span class="truncate block" title={event.organizer || ''}>
										{event.organizer || '-'}
									</span>
								</td>
								<!-- URL 타입 -->
								<td class="px-3 py-3 text-sm text-gray-600">
									{getUrlTypeLabel(event.url_type)}
								</td>
								<!-- 위치 (팝업 탭만) -->
								{#if activeTab === 'popup'}
									<td class="px-3 py-3 text-sm text-gray-600 max-w-[150px]">
										<span class="truncate block" title={event.location_venue || ''}>
											{event.location_venue || '-'}
										</span>
									</td>
								{/if}
								<!-- 출처 -->
								<td class="px-3 py-3 text-sm text-gray-600">
									<span class="px-2 py-0.5 text-xs rounded {event.source_type === 'instagram' ? 'bg-pink-100 text-pink-600' : 'bg-gray-100 text-gray-600'}">
										{event.source_type === 'instagram' ? 'IG' : event.source_type === 'manual' ? '수동' : event.source_type}
									</span>
								</td>
								<!-- 북마크 -->
								<td class="px-3 py-3 text-center" onclick={(e) => e.stopPropagation()}>
									<button
										onclick={(e) => toggleBookmark(event, e)}
										class="text-xl transition-colors {event.is_bookmarked ? 'text-yellow-500' : 'text-gray-300 hover:text-yellow-400'}"
										title={event.is_bookmarked ? '북마크 해제' : '북마크'}
									>
										{event.is_bookmarked ? '★' : '☆'}
									</button>
								</td>
								<!-- 참여 완료 -->
								<td class="px-3 py-3 text-center" onclick={(e) => e.stopPropagation()}>
									<button
										onclick={(e) => toggleParticipate(event, e)}
										class="px-2 py-1 text-xs rounded transition-colors {event.is_participated ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}"
										title={event.is_participated ? '참여 취소' : '참여 완료'}
									>
										{event.is_participated ? '참여함' : '미참여'}
									</button>
								</td>
								<!-- 액션 -->
								<td class="px-3 py-3 text-center" onclick={(e) => e.stopPropagation()}>
									<div class="flex gap-2 justify-center">
										{#if event.event_url}
											<a
												href={event.event_url}
												target="_blank"
												rel="noopener noreferrer"
												class="text-blue-600 hover:text-blue-800 text-sm"
												title="이벤트 URL 열기"
											>
												링크
											</a>
										{/if}
										<button
											onclick={() => deleteEvent(event.id)}
											class="text-red-600 hover:text-red-800 text-sm"
										>
											삭제
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>

		<!-- 페이지네이션 -->
		<div class="flex flex-col sm:flex-row justify-between items-center gap-3">
			<span class="text-sm text-gray-500">
				전체 {total}개 중 {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)}
			</span>
			<div class="flex gap-2">
				<button
					onclick={prevPage}
					disabled={page === 1}
					class="btn btn-secondary btn-sm disabled:opacity-50"
				>
					이전
				</button>
				<span class="px-3 py-1.5 text-sm">
					{page} / {Math.ceil(total / pageSize)}
				</span>
				<button
					onclick={nextPage}
					disabled={page * pageSize >= total}
					class="btn btn-secondary btn-sm disabled:opacity-50"
				>
					다음
				</button>
			</div>
		</div>
	{/if}
</div>

<!-- 이벤트 생성/수정 모달 -->
{#if showEventModal}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center sm:p-4"
		onclick={closeModal}
		onkeydown={(e) => e.key === 'Escape' && closeModal()}
		role="dialog"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div
			class="bg-white rounded-t-xl sm:rounded-xl w-full sm:max-w-2xl max-h-[90vh] overflow-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<h3 class="text-lg font-bold text-gray-900">
						{editingEvent ? '이벤트 수정' : '새 이벤트'}
					</h3>
					<button onclick={closeModal} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<div class="space-y-4">
					<!-- 제목 -->
					<div>
						<label for="event-title" class="block text-sm font-medium text-gray-700 mb-1">
							제목 <span class="text-red-500">*</span>
						</label>
						<input
							id="event-title"
							type="text"
							bind:value={eventForm.title}
							placeholder="이벤트 제목"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						/>
					</div>

					<!-- 유형 + 상태 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="event-type" class="block text-sm font-medium text-gray-700 mb-1">유형</label>
							<select
								id="event-type"
								bind:value={eventForm.event_type}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							>
								<option value="event">이벤트</option>
								<option value="popup">팝업</option>
								<option value="ambassador">홍보대사</option>
								<option value="other">기타</option>
							</select>
						</div>
						{#if editingEvent}
							<div>
								<label for="event-status" class="block text-sm font-medium text-gray-700 mb-1">상태</label>
								<select
									id="event-status"
									bind:value={eventForm.status}
									class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
								>
									<option value="active">활성</option>
									<option value="ended">종료</option>
									<option value="cancelled">취소</option>
								</select>
							</div>
						{/if}
					</div>

					<!-- 이벤트 URL -->
					<div>
						<label for="event-url" class="block text-sm font-medium text-gray-700 mb-1">이벤트 URL</label>
						<input
							id="event-url"
							type="text"
							bind:value={eventForm.event_url}
							placeholder="https://..."
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						/>
						<p class="mt-1 text-xs text-gray-500">구글폼, 네이버폼 등 참여 URL (자동으로 타입 감지)</p>
					</div>

					<!-- 기간 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="event-start" class="block text-sm font-medium text-gray-700 mb-1">시작일</label>
							<input
								id="event-start"
								type="date"
								bind:value={eventForm.event_start}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="event-end" class="block text-sm font-medium text-gray-700 mb-1">종료일</label>
							<input
								id="event-end"
								type="date"
								bind:value={eventForm.event_end}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
					</div>

					<!-- 주최 + 발표일 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="event-organizer" class="block text-sm font-medium text-gray-700 mb-1">주최</label>
							<input
								id="event-organizer"
								type="text"
								bind:value={eventForm.organizer}
								placeholder="주최자/브랜드명"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="event-announcement" class="block text-sm font-medium text-gray-700 mb-1">발표일</label>
							<input
								id="event-announcement"
								type="date"
								bind:value={eventForm.announcement_date}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
					</div>

					<!-- 팝업 전용: 위치 -->
					{#if eventForm.event_type === 'popup'}
						<div class="grid grid-cols-2 gap-4">
							<div>
								<label for="event-venue" class="block text-sm font-medium text-gray-700 mb-1">장소명</label>
								<input
									id="event-venue"
									type="text"
									bind:value={eventForm.location_venue}
									placeholder="예: 더현대 서울"
									class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
								/>
							</div>
							<div>
								<label for="event-address" class="block text-sm font-medium text-gray-700 mb-1">주소</label>
								<input
									id="event-address"
									type="text"
									bind:value={eventForm.location_address}
									placeholder="예: 서울시 영등포구..."
									class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
								/>
							</div>
						</div>
					{/if}

					<!-- 요약 -->
					<div>
						<label for="event-summary" class="block text-sm font-medium text-gray-700 mb-1">요약</label>
						<textarea
							id="event-summary"
							bind:value={eventForm.summary}
							placeholder="이벤트 설명..."
							rows="3"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						></textarea>
					</div>

					<!-- 메모 -->
					<div>
						<label for="event-note" class="block text-sm font-medium text-gray-700 mb-1">메모</label>
						<textarea
							id="event-note"
							bind:value={eventForm.user_note}
							placeholder="개인 메모..."
							rows="2"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						></textarea>
					</div>
				</div>

				<div class="mt-6 flex gap-2 justify-end">
					<button onclick={closeModal} class="btn btn-secondary btn-sm">
						취소
					</button>
					<button
						onclick={saveEvent}
						disabled={isSaving}
						class="btn btn-primary btn-sm disabled:opacity-50"
					>
						{#if isSaving}
							저장 중...
						{:else}
							{editingEvent ? '수정' : '등록'}
						{/if}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
