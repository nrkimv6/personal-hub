<script lang="ts">
	/**
	 * 이벤트/팝업 관리 페이지
	 *
	 * 리팩토링된 버전: 컴포넌트 분리로 가독성 및 유지보수성 향상
	 */
	import { onMount } from 'svelte';
	import { page as pageStore } from '$app/stores';
	import { goto } from '$app/navigation';
	import { eventApi, popupApi, uncategorizedApi, collectApi } from '$lib/api';
	import type { Event, EventCreate, EventUpdate, InstagramPost, Popup, UncategorizedPost, InstagramTag } from '$lib/types';
	import { isAdmin, isLoggedIn } from '$lib/stores/auth';
	import { localParticipation } from '$lib/stores/localParticipation';

	// 컴포넌트 import
	import EventListCard from '$lib/components/events/EventListCard.svelte';
	import EventListTable from '$lib/components/events/EventListTable.svelte';
	import PopupListCard from '$lib/components/events/PopupListCard.svelte';
	import PopupListTable from '$lib/components/events/PopupListTable.svelte';
	import EventFilterPanel from '$lib/components/events/EventFilterPanel.svelte';
	import EventFormModal from '$lib/components/events/EventFormModal.svelte';
	import EventFeedViewerModal from '$lib/components/events/EventFeedViewerModal.svelte';
	import EventUrlImportModal from '$lib/components/events/EventUrlImportModal.svelte';

	// 로컬 참여 상태 스토어 반응형 구독
	const participatedMap = $derived($localParticipation);

	// 상태 변수
	let events: Event[] = $state([]);
	let popups: Popup[] = $state([]);
	let total = $state(0);
	let currentPage = $state(1);
	let pageSize = 20;
	let loading = $state(true);
	let error: string | null = $state(null);

	// 탭 모드: online(온라인 이벤트), offline(오프라인 이벤트), popup, uncategorized
	type TabMode = 'online' | 'offline' | 'popup' | 'uncategorized';
	let activeTab: TabMode = $state('online');

	// 미분류 목록
	let uncategorizedPosts: UncategorizedPost[] = $state([]);

	// 필터
	let filterEventStatus: string | null = $state('ongoing');
	let filterUrlType: string | null = $state(null);
	let filterSourceType: string | null = $state(null);
	let filterSearch = $state('');  // 검색어
	let filterDeadlineDate: string | null = $state(null);  // 마감일 날짜 필터
	let deadlineCounts: Record<string, number> = $state({});  // 날짜별 마감 이벤트 개수
	let sortBy = $state('event_end');
	let sortOrder = $state('asc');
	let unknownPeriodFilter = $state('include');  // exclude/include/only
	let showFilters = $state(false);

	// 활성 필터 카운트
	const activeFilterCount = $derived(
		[
			filterEventStatus,
			filterUrlType,
			filterSourceType,
			filterSearch,
			filterDeadlineDate,
			unknownPeriodFilter !== 'include'  // include가 아니면 활성 필터로 카운트
		].filter(Boolean).length
	);

	// 익명 사용자 여부
	const isAnonymous = $derived(!$isLoggedIn);

	// 모달 상태
	let showEventModal = $state(false);
	let editingEvent: Event | null = $state(null);
	let showUrlImportModal = $state(false);
	let importedEventData: EventCreate | null = $state(null);

	// 피드 뷰어 상태
	let showFeedViewer = $state(false);
	let viewerType: 'event' | 'popup' = $state('event');
	let viewingEvent: Event | null = $state(null);
	let viewingPopup: Popup | null = $state(null);
	let instagramPost: InstagramPost | null = $state(null);
	let loadingPost = $state(false);

	// FeedCard용 태그 목록
	let availableTags: InstagramTag[] = $state([]);

	// =========================================================
	// 탭/필터 관련 함수
	// =========================================================

	function switchTab(tab: TabMode, updateUrl: boolean = true) {
		activeTab = tab;
		currentPage = 1;

		// URL 업데이트 (히스토리에 추가)
		if (updateUrl) {
			goto(`?tab=${tab}`, { replaceState: false, keepFocus: true, noScroll: true });
		}

		if (isAnonymous) {
			// 운영모드: 온라인은 내일까지, 오프라인은 진행중
			if (tab === 'online') {
				filterEventStatus = 'ending_tomorrow';
			} else if (tab === 'offline') {
				filterEventStatus = 'ongoing';
			} else {
				filterEventStatus = null;
			}
		} else if (tab === 'online' || tab === 'offline') {
			filterEventStatus = 'ongoing';
		} else if (tab === 'popup') {
			filterEventStatus = 'ongoing_or_upcoming';
		} else if (tab === 'uncategorized') {
			filterEventStatus = null;
		}
		fetchEvents();
	}

	function handleStatusFilterChange(status: string | null) {
		filterEventStatus = status;
		// Phase 2: 마감일 필터와 독립 동작 (초기화하지 않음)
		currentPage = 1;
		fetchEvents();
	}

	function handleUnknownPeriodFilterChange(filter: string) {
		unknownPeriodFilter = filter;
		currentPage = 1;
		fetchEvents();
	}

	function handleSortChange(newSortBy: string, newSortOrder: string) {
		sortBy = newSortBy;
		sortOrder = newSortOrder;
		currentPage = 1;
		fetchEvents();
	}

	function handleQuickFilter(preset: { filters: { eventStatus: string; sortBy: string; sortOrder: string; unknownPeriodFilter: string } }) {
		filterEventStatus = preset.filters.eventStatus || null;
		sortBy = preset.filters.sortBy;
		sortOrder = preset.filters.sortOrder;
		unknownPeriodFilter = preset.filters.unknownPeriodFilter;
		filterDeadlineDate = null;  // 빠른 필터 시 마감일 초기화
		currentPage = 1;
		fetchEvents();
	}

	function handleUrlTypeChange(urlType: string | null) {
		filterUrlType = urlType;
		currentPage = 1;
		fetchEvents();
	}

	function handleSourceTypeChange(sourceType: string | null) {
		filterSourceType = sourceType;
		currentPage = 1;
		fetchEvents();
	}

	function handleDeadlineDateChange(date: string | null) {
		filterDeadlineDate = date;
		// Phase 2: 상태 필터와 독립 동작 (초기화하지 않음)
		currentPage = 1;
		fetchEvents();
	}

	// 검색 실행
	function handleSearch() {
		currentPage = 1;
		fetchEvents();
	}

	function handleSort(column: string) {
		if (sortBy === column) {
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			sortBy = column;
			sortOrder = ['created_at', 'event_end', 'event_start', 'announcement_date'].includes(column)
				? 'desc'
				: 'asc';
		}
		currentPage = 1;
		fetchEvents();
	}

	// =========================================================
	// API 호출
	// =========================================================

	async function fetchDeadlineCounts() {
		try {
			deadlineCounts = await eventApi.getDeadlineCounts(6, 'event');
		} catch (e) {
			console.error('날짜별 카운트 로드 실패:', e);
		}
	}

	async function fetchEvents() {
		loading = true;
		try {
			if (activeTab === 'popup') {
				const params: Record<string, unknown> = {
					page: currentPage,
					page_size: pageSize,
					sort_by: sortBy === 'event_end' ? 'end_date' : sortBy === 'event_start' ? 'start_date' : sortBy,
					sort_order: sortOrder,
					unknown_period_filter: unknownPeriodFilter
				};
				if (filterEventStatus) params.popup_status = filterEventStatus;
				if (filterSourceType) params.source_type = filterSourceType;
				if (filterSearch) params.search = filterSearch;

				const response = await popupApi.list(params);
				popups = response.items;
				events = [];
				uncategorizedPosts = [];
				total = response.total;
				error = null;
			} else if (activeTab === 'uncategorized') {
				const params: Record<string, unknown> = {
					page: currentPage,
					page_size: pageSize,
					sort_by: sortBy === 'event_end' ? 'created_at' : sortBy,
					sort_order: sortOrder,
					include_reclassified: false
				};

				const response = await uncategorizedApi.list(params);
				uncategorizedPosts = response.items;
				events = [];
				popups = [];
				total = response.total;
				error = null;
			} else {
				// online 또는 offline 탭: 이벤트 목록 조회
				const params: Record<string, unknown> = {
					page: currentPage,
					page_size: pageSize,
					sort_by: sortBy,
					sort_order: sortOrder,
					event_type: 'event',
					is_offline: activeTab === 'offline',  // 탭에 따라 온라인/오프라인 필터
					unknown_period_filter: unknownPeriodFilter
				};
				// Phase 2: 상태/마감일 필터 독립 동작 (둘 다 적용)
				if (filterEventStatus) params.event_status = filterEventStatus;
				if (filterDeadlineDate) params.deadline_date = filterDeadlineDate;
				if (filterUrlType) params.url_type = filterUrlType;
				if (filterSourceType) params.source_type = filterSourceType;
				if (filterSearch) params.search = filterSearch;

				const response = await eventApi.list(params);
				events = response.items;
				popups = [];
				uncategorizedPosts = [];
				total = response.total;
				error = null;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	// =========================================================
	// 이벤트 핸들러
	// =========================================================

	async function handleEventClick(event: Event) {
		if (event.source_type === 'instagram' && event.source_instagram_post_id) {
			await openFeedViewer('event', event);
		} else {
			openEditModal(event);
		}
	}

	async function handlePopupClick(popup: Popup) {
		if (popup.source_type === 'instagram' && popup.source_instagram_post_id) {
			await openFeedViewer('popup', undefined, popup);
		} else if (popup.source_instagram_url) {
			window.open(popup.source_instagram_url, '_blank');
		}
	}

	function openCreateModal() {
		editingEvent = null;
		importedEventData = null;
		showEventModal = true;
	}

	function openEditModal(event: Event) {
		editingEvent = event;
		importedEventData = null;
		showEventModal = true;
	}

	function openUrlImportModal() {
		showUrlImportModal = true;
	}

	function handleUrlImportComplete(eventData: EventCreate) {
		// URL에서 추출된 데이터로 이벤트 생성 모달 열기
		importedEventData = eventData;
		editingEvent = null;
		showEventModal = true;
	}

	async function handleSaveEvent(formData: EventCreate | EventUpdate, isEdit: boolean) {
		if (isEdit && editingEvent) {
			await eventApi.update(editingEvent.id, formData as EventUpdate);
		} else {
			await eventApi.create(formData as EventCreate);
		}
		await fetchEvents();
	}

	async function handleDeleteEvent() {
		if (!viewingEvent) return;
		if (!confirm('이 이벤트를 삭제하시겠습니까?')) return;
		try {
			await eventApi.delete(viewingEvent.id);
			closeFeedViewer();
			await fetchEvents();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	// =========================================================
	// 북마크/참여/방문 토글
	// =========================================================

	async function handleEventBookmarkToggle(event: Event, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await eventApi.toggleBookmark(event.id);
			event.is_bookmarked = result.is_bookmarked;
			events = [...events];
			// 뷰어에서도 업데이트
			if (viewingEvent?.id === event.id) {
				viewingEvent = { ...viewingEvent, is_bookmarked: result.is_bookmarked };
			}
		} catch (err) {
			console.error('북마크 토글 실패:', err);
		}
	}

	function handleEventParticipateToggle(event: Event, e: MouseEvent) {
		e.stopPropagation();
		const currentState = isEventParticipated(event);
		localParticipation.toggle(event.id, currentState);
		// events 배열 재할당하여 UI 즉시 반영
		events = [...events];
	}

	async function handlePopupBookmarkToggle(popup: Popup, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await popupApi.toggleBookmark(popup.id);
			popup.is_bookmarked = result.is_bookmarked;
			popups = [...popups];
			if (viewingPopup?.id === popup.id) {
				viewingPopup = { ...viewingPopup, is_bookmarked: result.is_bookmarked };
			}
		} catch (err) {
			console.error('북마크 토글 실패:', err);
		}
	}

	async function handlePopupVisitedToggle(popup: Popup, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await popupApi.toggleVisited(popup.id);
			popup.is_visited = result.is_visited;
			popups = [...popups];
			if (viewingPopup?.id === popup.id) {
				viewingPopup = { ...viewingPopup, is_visited: result.is_visited };
			}
		} catch (err) {
			console.error('방문 토글 실패:', err);
		}
	}

	async function handleEventOfflineToggle(event: Event, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await eventApi.toggleOffline(event.id);
			// 목록 업데이트
			const eventIndex = events.findIndex(ev => ev.id === event.id);
			if (eventIndex !== -1) {
				events[eventIndex].is_offline = result.is_offline;
				events = [...events];
			}
			// 뷰어에서도 업데이트
			if (viewingEvent?.id === event.id) {
				viewingEvent = { ...viewingEvent, is_offline: result.is_offline };
			}
			// 탭에 따라 목록 새로고침 (토글 후 다른 탭으로 이동해야 하므로)
			await fetchEvents();
		} catch (err) {
			console.error('오프라인 토글 실패:', err);
		}
	}

	// =========================================================
	// 피드 뷰어
	// =========================================================

	async function openFeedViewer(type: 'event' | 'popup', event?: Event, popup?: Popup) {
		viewerType = type;
		viewingEvent = event || null;
		viewingPopup = popup || null;
		showFeedViewer = true;
		loadingPost = true;
		instagramPost = null;

		try {
			const postId = type === 'event' ? event?.source_instagram_post_id : popup?.source_instagram_post_id;
			if (postId) {
				instagramPost = await collectApi.getPost(postId);
			}
		} catch (e) {
			console.error('Instagram 게시물 로드 실패:', e);
		} finally {
			loadingPost = false;
		}
	}

	function closeFeedViewer() {
		showFeedViewer = false;
		viewingEvent = null;
		viewingPopup = null;
		instagramPost = null;
	}

	function handleViewerBookmarkToggle(e: MouseEvent) {
		e.stopPropagation();
		if (viewerType === 'event' && viewingEvent) {
			handleEventBookmarkToggle(viewingEvent, e);
		} else if (viewerType === 'popup' && viewingPopup) {
			handlePopupBookmarkToggle(viewingPopup, e);
		}
	}

	function handleViewerParticipateToggle(e: MouseEvent) {
		e.stopPropagation();
		if (viewingEvent) {
			handleEventParticipateToggle(viewingEvent, e);
		}
	}

	function handleViewerVisitToggle(e: MouseEvent) {
		e.stopPropagation();
		if (viewingPopup) {
			handlePopupVisitedToggle(viewingPopup, e);
		}
	}

	function handleViewerOfflineToggle(e: MouseEvent) {
		e.stopPropagation();
		if (viewingEvent) {
			handleEventOfflineToggle(viewingEvent, e);
		}
	}

	function handleViewerEdit() {
		if (viewingEvent) {
			const event = viewingEvent;  // closeFeedViewer에서 null로 설정되기 전에 저장
			closeFeedViewer();
			openEditModal(event);
		}
	}

	// =========================================================
	// Instagram 관련 핸들러
	// =========================================================

	async function handleRecrawl(postId: number): Promise<void> {
		try {
			await collectApi.recrawlPost(postId);
			alert('재크롤링 요청이 등록되었습니다.');
		} catch (e) {
			console.error('재크롤링 요청 실패:', e);
			alert('재크롤링 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function handleTagsUpdate(postId: number, tagIds: number[]): Promise<void> {
		try {
			const updated = await collectApi.updatePost(postId, { tag_ids: tagIds });
			if (instagramPost?.id === postId) {
				instagramPost = updated;
			}
		} catch (e) {
			console.error('태그 저장 실패:', e);
			alert('태그 저장 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
			throw e;
		}
	}

	async function handleDeletePost(postId: number): Promise<void> {
		if (!confirm('이 게시물을 삭제하시겠습니까?')) return;
		try {
			await collectApi.deletePost(postId);
			closeFeedViewer();
			await fetchEvents();
		} catch (e) {
			console.error('삭제 실패:', e);
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function handleRequestLlmAnalysis(postId: number): Promise<void> {
		try {
			await collectApi.requestLlmAnalysisSingle(postId);
			alert('AI 분석 요청이 등록되었습니다.');
		} catch (e) {
			console.error('AI 분석 요청 실패:', e);
			alert('AI 분석 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	// =========================================================
	// 미분류 재분류
	// =========================================================

	async function handleReclassify(post: UncategorizedPost, target: 'event' | 'popup') {
		try {
			await uncategorizedApi.reclassify(post.id, { target, title: post.title || undefined });
			alert(`${target === 'event' ? '이벤트' : '팝업'}로 재분류되었습니다.`);
			await fetchEvents();
		} catch (e) {
			console.error('재분류 실패:', e);
			alert('재분류 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	// =========================================================
	// 페이지네이션
	// =========================================================

	function prevPage() {
		if (currentPage > 1) {
			currentPage--;
			fetchEvents();
		}
	}

	function nextPage() {
		if (currentPage * pageSize < total) {
			currentPage++;
			fetchEvents();
		}
	}

	// =========================================================
	// 참여 상태 헬퍼
	// =========================================================

	function isEventParticipated(event: Event): boolean {
		// 반응형 participatedMap 사용
		if (event.id in participatedMap) {
			return participatedMap[event.id];
		}
		return event.is_participated;
	}

	// =========================================================
	// 초기화
	// =========================================================

	onMount(async () => {
		localParticipation.load();

		try {
			availableTags = await collectApi.tags.getTags();
		} catch (e) {
			console.error('태그 목록 로드 실패:', e);
		}

		// 날짜별 마감 카운트 로드
		fetchDeadlineCounts();

		// URL의 tab 파라미터로 초기 탭 설정
		const urlTab = $pageStore.url.searchParams.get('tab');
		const validTabs: TabMode[] = ['online', 'offline', 'popup', 'uncategorized'];
		if (urlTab && validTabs.includes(urlTab as TabMode)) {
			// URL 파라미터로 탭 전환 (URL 업데이트 불필요)
			switchTab(urlTab as TabMode, false);
			return; // switchTab에서 fetchEvents 호출하므로 여기서 종료
		}

		// PWA Share Target 처리
		const action = $pageStore.url.searchParams.get('action');
		const sharedUrl = $pageStore.url.searchParams.get('url');
		if (action === 'add' && sharedUrl) {
			showEventModal = true;
		}

		// 익명 사용자(운영모드) 필터 설정
		if (!$isLoggedIn) {
			if (activeTab === 'online') {
				filterEventStatus = 'ending_tomorrow';
			} else if (activeTab === 'offline') {
				filterEventStatus = 'ongoing';
			} else {
				filterEventStatus = null;
			}
		}

		fetchEvents();
	});
</script>

<svelte:head>
	<title>이벤트 · 팝업 관리</title>
</svelte:head>

<div class="p-4 md:p-6">
	<!-- 헤더 -->
	<div class="mb-4 md:mb-6 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
		<div class="flex items-center justify-between sm:justify-start gap-3">
			<h2 class="text-xl md:text-2xl font-bold text-gray-900">이벤트 관리</h2>
			{#if $isAdmin}
				<div class="flex gap-2">
					<button onclick={openCreateModal} class="btn btn-primary btn-sm"> + 새 이벤트 </button>
					<button onclick={openUrlImportModal} class="btn btn-outline btn-sm" title="URL에서 이벤트 가져오기">
						🔗 URL 가져오기
					</button>
				</div>
			{/if}
		</div>

		<!-- 필터 요약 + 모바일 필터 토글 -->
		<div class="flex items-center gap-2">
			{#if isAnonymous}
				<!-- 익명 사용자: 필터 비활성화, 고정 배지만 표시 -->
				{#if activeTab === 'online'}
					<span class="px-2 py-1 text-xs font-medium bg-orange-100 text-orange-700 rounded-full">
						내일까지
					</span>
				{:else if activeTab === 'offline'}
					<span class="px-2 py-1 text-xs font-medium bg-green-100 text-green-700 rounded-full">
						진행중
					</span>
				{:else}
					<span class="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-600 rounded-full">
						전체
					</span>
				{/if}
			{:else}
				<!-- 모바일 필터 토글 버튼 (로그인 사용자만) -->
				<button
					onclick={() => (showFilters = !showFilters)}
					class="md:hidden btn btn-secondary btn-sm flex items-center gap-1"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"
						/>
					</svg>
					필터
					{#if activeFilterCount > 0}
						<span class="px-1.5 py-0.5 text-xs bg-blue-600 text-white rounded-full"
							>{activeFilterCount}</span
						>
					{/if}
				</button>
			{/if}

			<span class="text-sm text-gray-600">총 {total}건</span>
			{#if unknownPeriodFilter === 'only'}
				<span class="hidden sm:inline text-sm text-amber-600">(기간미정만)</span>
			{:else if unknownPeriodFilter === 'exclude'}
				<span class="hidden sm:inline text-sm text-gray-500">(기간미정 제외)</span>
			{/if}
		</div>
	</div>

	<!-- 탭 -->
	<div class="mb-4 border-b border-gray-200">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('online')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'online'
					? 'border-purple-600 text-purple-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				온라인 이벤트
			</button>
			<button
				onclick={() => switchTab('offline')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'offline'
					? 'border-green-600 text-green-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				오프라인 이벤트
			</button>
			<button
				onclick={() => switchTab('popup')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'popup'
					? 'border-pink-600 text-pink-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				팝업
			</button>
			<button
				onclick={() => switchTab('uncategorized')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'uncategorized'
					? 'border-gray-600 text-gray-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				미분류
			</button>
		</nav>
	</div>

	<!-- 필터 패널 (로그인 사용자만) -->
	{#if !isAnonymous}
		<EventFilterPanel
			{filterEventStatus}
			{unknownPeriodFilter}
			{showFilters}
			{filterDeadlineDate}
			{deadlineCounts}
			{filterSearch}
			{sortBy}
			{sortOrder}
			{filterUrlType}
			{filterSourceType}
			onStatusFilterChange={handleStatusFilterChange}
			onUnknownPeriodFilterChange={handleUnknownPeriodFilterChange}
			onShowFiltersChange={(v) => (showFilters = v)}
			onDeadlineDateChange={handleDeadlineDateChange}
			onSearchChange={(v) => (filterSearch = v)}
			onSearch={handleSearch}
			onSortChange={handleSortChange}
			onQuickFilter={handleQuickFilter}
			onUrlTypeChange={handleUrlTypeChange}
			onSourceTypeChange={handleSourceTypeChange}
		/>
	{/if}

	<!-- 목록 -->
	{#if loading}
			<div class="flex justify-center items-center h-64">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
			</div>
		{:else if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
				{error}
			</div>
		{:else if (activeTab === 'popup' ? popups.length : activeTab === 'uncategorized' ? uncategorizedPosts.length : events.length) === 0}
			<div class="text-center py-12 text-gray-500">
				<p class="text-lg">
					{activeTab === 'popup' ? '등록된 팝업이 없습니다' : activeTab === 'uncategorized' ? '미분류 항목이 없습니다' : activeTab === 'offline' ? '등록된 오프라인 이벤트가 없습니다' : '등록된 온라인 이벤트가 없습니다'}
				</p>
				{#if $isAdmin && activeTab !== 'uncategorized'}
					<button onclick={openCreateModal} class="mt-4 btn btn-primary btn-sm">
						+ {activeTab === 'popup' ? '새 팝업 등록' : '새 이벤트 등록'}
					</button>
				{/if}
			</div>
		{:else if activeTab === 'uncategorized'}
		<!-- 미분류 목록 -->
		<div class="space-y-3">
			{#each uncategorizedPosts as post}
				<div
					class="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer"
					onclick={() => post.source_instagram_url && window.open(post.source_instagram_url, '_blank')}
				>
					<div class="flex items-start gap-4">
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2 mb-1">
								<span class="px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-600">
									{post.original_tag || '미분류'}
								</span>
								{#if post.source_instagram_account}
									<span class="text-xs text-gray-500">@{post.source_instagram_account}</span>
								{/if}
							</div>
							<h3 class="font-medium text-gray-900 truncate">
								{post.title || '제목 없음'}
							</h3>
							{#if post.summary}
								<p class="text-sm text-gray-600 mt-1 line-clamp-2">{post.summary}</p>
							{/if}
							{#if post.organizer}
								<p class="text-xs text-gray-500 mt-1">{post.organizer}</p>
							{/if}
						</div>
						{#if $isAdmin}
							<div class="flex gap-2" onclick={(e) => e.stopPropagation()}>
								<button
									onclick={() => handleReclassify(post, 'event')}
									class="px-2 py-1 text-xs bg-purple-100 text-purple-700 rounded hover:bg-purple-200"
								>
									이벤트로
								</button>
								<button
									onclick={() => handleReclassify(post, 'popup')}
									class="px-2 py-1 text-xs bg-pink-100 text-pink-700 rounded hover:bg-pink-200"
								>
									팝업으로
								</button>
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{:else if activeTab === 'popup'}
		<!-- 팝업 목록 -->
		<PopupListCard
			{popups}
			onPopupClick={handlePopupClick}
			onBookmarkToggle={handlePopupBookmarkToggle}
		/>
		<PopupListTable
			{popups}
			onPopupClick={handlePopupClick}
			onBookmarkToggle={handlePopupBookmarkToggle}
			onVisitedToggle={handlePopupVisitedToggle}
		/>
	{:else}
		<!-- 이벤트 목록 -->
		<EventListCard
			{events}
			isAdmin={$isAdmin}
			isParticipated={isEventParticipated}
			onEventClick={handleEventClick}
			onBookmarkToggle={handleEventBookmarkToggle}
			onParticipateToggle={handleEventParticipateToggle}
		/>
		<EventListTable
			{events}
			{sortBy}
			{sortOrder}
			isAdmin={$isAdmin}
			isParticipated={isEventParticipated}
			onSort={handleSort}
			onEventClick={handleEventClick}
			onBookmarkToggle={handleEventBookmarkToggle}
			onParticipateToggle={handleEventParticipateToggle}
		/>
		{/if}

		<!-- 페이지네이션 -->
		{#if !loading && !error && (activeTab === 'popup' ? popups.length : activeTab === 'uncategorized' ? uncategorizedPosts.length : events.length) > 0}
		<div class="flex flex-col sm:flex-row justify-between items-center gap-3 mt-6">
			<span class="text-sm text-gray-500">
				전체 {total}개 중 {(currentPage - 1) * pageSize + 1} - {Math.min(
					currentPage * pageSize,
					total
				)}
			</span>
			<div class="flex gap-2">
				<button
					onclick={prevPage}
					disabled={currentPage === 1}
					class="btn btn-secondary btn-sm disabled:opacity-50"
				>
					이전
				</button>
				<span class="px-3 py-1.5 text-sm">
					{currentPage} / {Math.ceil(total / pageSize)}
				</span>
				<button
					onclick={nextPage}
					disabled={currentPage * pageSize >= total}
					class="btn btn-secondary btn-sm disabled:opacity-50"
				>
					다음
				</button>
			</div>
		</div>
		{/if}
</div>

<!-- 이벤트 생성/수정 모달 (관리자 전용) -->
{#if $isAdmin}
<EventFormModal
	show={showEventModal}
	{editingEvent}
	importedData={importedEventData}
	activeTab={activeTab === 'popup' ? 'popup' : 'event'}
	onClose={() => {
		showEventModal = false;
		importedEventData = null;
	}}
	onSave={handleSaveEvent}
/>

<!-- URL 가져오기 모달 -->
<EventUrlImportModal
	show={showUrlImportModal}
	onClose={() => (showUrlImportModal = false)}
	onImportComplete={handleUrlImportComplete}
/>
{/if}

<!-- 피드 뷰어 모달 -->
<EventFeedViewerModal
	show={showFeedViewer}
	type={viewerType}
	event={viewingEvent}
	popup={viewingPopup}
	{instagramPost}
	{loadingPost}
	{availableTags}
	isAdmin={$isAdmin}
	isParticipated={viewingEvent ? isEventParticipated(viewingEvent) : false}
	onClose={closeFeedViewer}
	onEdit={$isAdmin ? handleViewerEdit : undefined}
	onDelete={$isAdmin ? handleDeleteEvent : undefined}
	onBookmarkToggle={handleViewerBookmarkToggle}
	onParticipateToggle={handleViewerParticipateToggle}
	onVisitToggle={handleViewerVisitToggle}
	onOfflineToggle={$isAdmin ? handleViewerOfflineToggle : undefined}
	onRecrawl={$isAdmin ? handleRecrawl : undefined}
	onTagsUpdate={$isAdmin ? handleTagsUpdate : undefined}
	onDeletePost={$isAdmin ? handleDeletePost : undefined}
	onRequestLlmAnalysis={$isAdmin ? handleRequestLlmAnalysis : undefined}
/>

