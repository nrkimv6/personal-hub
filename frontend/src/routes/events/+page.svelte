<script lang="ts">
	/**
	 * 이벤트/팝업 관리 페이지
	 *
	 * 리팩토링된 버전: 컴포넌트 분리로 가독성 및 유지보수성 향상
	 */
	import { onMount } from 'svelte';
	import { page as pageStore } from '$app/stores';
	import { eventApi, popupApi, instagramApi, instagramTagApi } from '$lib/api';
	import type { Event, EventCreate, EventUpdate, InstagramPost, Popup, InstagramTag } from '$lib/types';
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

	// 탭 모드
	type TabMode = 'event' | 'popup';
	let activeTab: TabMode = $state('event');

	// 필터
	let filterEventStatus: string | null = $state('ongoing');
	let filterBookmarked: boolean | null = $state(null);  // 북마크 기능 임시 비활성화 (변수는 유지)
	let filterUrlType: string | null = $state(null);
	let filterSourceType: string | null = $state(null);
	let filterSearch = $state('');  // 검색어
	let sortBy = $state('event_end');
	let sortOrder = $state('asc');
	let includeUnknownPeriod = $state(false);
	let showFilters = $state(false);

	// 활성 필터 카운트
	const activeFilterCount = $derived(
		[
			filterEventStatus,
			// filterBookmarked !== null,  // 북마크 기능 임시 비활성화
			filterUrlType,
			filterSourceType,
			filterSearch,
			includeUnknownPeriod
		].filter(Boolean).length
	);

	// 익명 사용자 여부
	const isAnonymous = $derived(!$isLoggedIn);

	// 모달 상태
	let showEventModal = $state(false);
	let editingEvent: Event | null = $state(null);

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

	function switchTab(tab: TabMode) {
		activeTab = tab;
		currentPage = 1;
		if (isAnonymous) {
			filterEventStatus = tab === 'event' ? 'ending_today' : null;
		} else if (tab === 'event') {
			filterEventStatus = 'ongoing';
		} else if (tab === 'popup') {
			filterEventStatus = 'ongoing_or_upcoming';
		}
		fetchEvents();
	}

	function handleStatusFilterChange(status: string | null) {
		filterEventStatus = status;
		currentPage = 1;
		fetchEvents();
	}

	function handleBookmarkedFilterToggle() {
		filterBookmarked = filterBookmarked === true ? null : true;
		currentPage = 1;
		fetchEvents();
	}

	function handleUnknownPeriodToggle() {
		includeUnknownPeriod = !includeUnknownPeriod;
		currentPage = 1;
		fetchEvents();
	}

	// 검색 실행
	function handleSearch() {
		currentPage = 1;
		fetchEvents();
	}

	// 검색어 초기화
	function clearSearch() {
		filterSearch = '';
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

	async function fetchEvents() {
		loading = true;
		try {
			if (activeTab === 'popup') {
				const params: Record<string, unknown> = {
					page: currentPage,
					page_size: pageSize,
					sort_by: sortBy === 'event_end' ? 'end_date' : sortBy === 'event_start' ? 'start_date' : sortBy,
					sort_order: sortOrder
				};
				if (filterEventStatus) params.popup_status = filterEventStatus;
				// if (filterBookmarked !== null) params.is_bookmarked = filterBookmarked;  // 북마크 기능 임시 비활성화
				if (filterSourceType) params.source_type = filterSourceType;
				if (filterSearch) params.search = filterSearch;
				if (includeUnknownPeriod) params.include_unknown_period = true;

				const response = await popupApi.list(params);
				popups = response.items;
				events = [];
				total = response.total;
				error = null;
			} else {
				const params: Record<string, unknown> = {
					page: currentPage,
					page_size: pageSize,
					sort_by: sortBy,
					sort_order: sortOrder,
					event_type: 'event'
				};
				if (filterEventStatus) params.event_status = filterEventStatus;
				// if (filterBookmarked !== null) params.is_bookmarked = filterBookmarked;  // 북마크 기능 임시 비활성화
				if (filterUrlType) params.url_type = filterUrlType;
				if (filterSourceType) params.source_type = filterSourceType;
				if (filterSearch) params.search = filterSearch;
				if (includeUnknownPeriod) params.include_unknown_period = true;

				const response = await eventApi.list(params);
				events = response.items;
				popups = [];
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
		showEventModal = true;
	}

	function openEditModal(event: Event) {
		editingEvent = event;
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
				instagramPost = await instagramApi.getPost(postId);
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

	function handleViewerEdit() {
		if (viewingEvent) {
			closeFeedViewer();
			openEditModal(viewingEvent);
		}
	}

	// =========================================================
	// Instagram 관련 핸들러
	// =========================================================

	async function handleRecrawl(postId: number): Promise<void> {
		try {
			await instagramApi.recrawlPost(postId);
			alert('재크롤링 요청이 등록되었습니다.');
		} catch (e) {
			console.error('재크롤링 요청 실패:', e);
			alert('재크롤링 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function handleTagsUpdate(postId: number, tagIds: number[]): Promise<void> {
		try {
			const updated = await instagramApi.updatePost(postId, { tag_ids: tagIds });
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
			await instagramApi.deletePost(postId);
			closeFeedViewer();
			await fetchEvents();
		} catch (e) {
			console.error('삭제 실패:', e);
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function handleRequestLlmAnalysis(postId: number): Promise<void> {
		try {
			await instagramApi.requestLlmAnalysis(postId);
			alert('AI 분석 요청이 등록되었습니다.');
		} catch (e) {
			console.error('AI 분석 요청 실패:', e);
			alert('AI 분석 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
			availableTags = await instagramTagApi.getTags();
		} catch (e) {
			console.error('태그 목록 로드 실패:', e);
		}

		// PWA Share Target 처리
		const action = $pageStore.url.searchParams.get('action');
		const sharedUrl = $pageStore.url.searchParams.get('url');
		if (action === 'add' && sharedUrl) {
			showEventModal = true;
		}

		// 익명 사용자 필터 설정
		if (!$isLoggedIn) {
			filterEventStatus = activeTab === 'event' ? 'ending_today' : null;
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
				<button onclick={openCreateModal} class="btn btn-primary btn-sm"> + 새 이벤트 </button>
			{/if}
		</div>

		<!-- 필터 요약 + 모바일 필터 토글 -->
		<div class="flex items-center gap-2">
			{#if isAnonymous}
				<!-- 익명 사용자: 필터 비활성화, 고정 배지만 표시 -->
				{#if activeTab === 'event'}
					<span class="px-2 py-1 text-xs font-medium bg-orange-100 text-orange-700 rounded-full">
						오늘 마감
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
			<!-- 북마크 기능 임시 비활성화
			{#if filterBookmarked}
				<span class="hidden sm:inline text-sm text-yellow-600">(북마크만)</span>
			{/if} -->
			{#if includeUnknownPeriod}
				<span class="hidden sm:inline text-sm text-amber-600">(기간미정 포함)</span>
			{/if}
		</div>
	</div>

	<!-- 탭 -->
	<div class="mb-4 border-b border-gray-200">
		<nav class="flex gap-4">
			<button
				onclick={() => switchTab('event')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'event'
					? 'border-purple-600 text-purple-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				온라인 이벤트
			</button>
			<button
				onclick={() => switchTab('popup')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'popup'
					? 'border-pink-600 text-pink-600'
					: 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				팝업
			</button>
		</nav>
	</div>

	<!-- 필터 패널 (로그인 사용자만) -->
	{#if !isAnonymous}
		<EventFilterPanel
			{filterEventStatus}
			{filterBookmarked}
			{includeUnknownPeriod}
			{showFilters}
			onStatusFilterChange={handleStatusFilterChange}
			onBookmarkedFilterToggle={handleBookmarkedFilterToggle}
			onUnknownPeriodToggle={handleUnknownPeriodToggle}
			onShowFiltersChange={(v) => (showFilters = v)}
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
	{:else if (activeTab === 'popup' ? popups.length : events.length) === 0}
		<div class="text-center py-12 text-gray-500">
			<p class="text-lg">
				{activeTab === 'popup' ? '등록된 팝업이 없습니다' : '등록된 이벤트가 없습니다'}
			</p>
			<p class="text-sm mt-2">
				{activeTab === 'popup'
					? '새 팝업을 등록하면 여기에 표시됩니다'
					: '새 이벤트를 등록하면 여기에 표시됩니다'}
			</p>
			{#if $isAdmin}
				<button onclick={openCreateModal} class="mt-4 btn btn-primary btn-sm">
					+ {activeTab === 'popup' ? '새 팝업 등록' : '새 이벤트 등록'}
				</button>
			{/if}
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
			isParticipated={isEventParticipated}
			onEventClick={handleEventClick}
			onBookmarkToggle={handleEventBookmarkToggle}
			onParticipateToggle={handleEventParticipateToggle}
		/>
		<EventListTable
			{events}
			{sortBy}
			{sortOrder}
			isParticipated={isEventParticipated}
			onSort={handleSort}
			onEventClick={handleEventClick}
			onBookmarkToggle={handleEventBookmarkToggle}
			onParticipateToggle={handleEventParticipateToggle}
		/>
	{/if}

	<!-- 페이지네이션 -->
	{#if !loading && !error && (activeTab === 'popup' ? popups.length : events.length) > 0}
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
	{activeTab}
	onClose={() => (showEventModal = false)}
	onSave={handleSaveEvent}
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
	isParticipated={viewingEvent ? isEventParticipated(viewingEvent) : false}
	onClose={closeFeedViewer}
	onEdit={$isAdmin ? handleViewerEdit : undefined}
	onDelete={$isAdmin ? handleDeleteEvent : undefined}
	onBookmarkToggle={handleViewerBookmarkToggle}
	onParticipateToggle={handleViewerParticipateToggle}
	onVisitToggle={handleViewerVisitToggle}
	onRecrawl={$isAdmin ? handleRecrawl : undefined}
	onTagsUpdate={$isAdmin ? handleTagsUpdate : undefined}
	onDeletePost={$isAdmin ? handleDeletePost : undefined}
	onRequestLlmAnalysis={$isAdmin ? handleRequestLlmAnalysis : undefined}
/>
