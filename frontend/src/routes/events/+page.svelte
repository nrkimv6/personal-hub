<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { page as pageStore } from '$app/stores';
	import { eventApi, popupApi, instagramApi, instagramTagApi } from '$lib/api';
	import type { Event, EventCreate, EventUpdate, InstagramPost, Popup, InstagramTag } from '$lib/types';
	import FeedCard from '$lib/components/instagram/FeedCard.svelte';
	import { isAdmin, isLoggedIn } from '$lib/stores/auth';

	let events: Event[] = [];
	let popups: Popup[] = [];
	let total = 0;
	let currentPage = 1;
	let pageSize = 20;
	let loading = true;
	let error: string | null = null;

	// 탭 모드: 온라인 이벤트 / 팝업
	type TabMode = 'event' | 'popup';
	let activeTab: TabMode = 'event';

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
		{ value: 'ending_today', label: '오늘 마감', color: 'bg-orange-100 text-orange-700' },
		{ value: 'ongoing', label: '진행 중', color: 'bg-green-100 text-green-700' },
		{ value: 'upcoming', label: '예정', color: 'bg-blue-100 text-blue-700' },
		{ value: 'ended', label: '종료', color: 'bg-gray-100 text-gray-600' },
		{ value: 'cancelled', label: '취소됨', color: 'bg-red-100 text-red-600' }
	];

	// 익명 사용자 여부 - 오늘 마감 필터 강제
	$: isAnonymous = !$isLoggedIn;

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

	// Instagram 피드 뷰어 상태
	let showFeedViewer = false;
	let viewingEvent: Event | null = null;
	let instagramPost: InstagramPost | null = null;
	let loadingPost = false;

	// 팝업 피드 뷰어 상태
	let showPopupFeedViewer = false;
	let viewingPopup: Popup | null = null;

	// FeedCard용 태그 목록
	let availableTags: InstagramTag[] = [];

	// 모바일 피드 뷰어 탭 상태
	type MobileViewerTab = 'info' | 'feed';
	let mobileViewerTab: MobileViewerTab = 'info';

	// 모바일 필터 표시 상태
	let showFilters = false;

	// 활성 필터 카운트 계산
	$: activeFilterCount = [
		filterEventStatus,
		filterBookmarked !== null,
		filterUrlType,
		filterSourceType,
		includeUnknownPeriod
	].filter(Boolean).length;


	// 로컬 참여 상태 관리 (로컬스토리지)
	const PARTICIPATED_STORAGE_KEY = 'events_participated';
	let localParticipated: Record<number, boolean> = {};

	function loadLocalParticipated() {
		if (!browser) return;
		try {
			const stored = localStorage.getItem(PARTICIPATED_STORAGE_KEY);
			if (stored) {
				localParticipated = JSON.parse(stored);
			}
		} catch (e) {
			console.error('로컬 참여 상태 로드 실패:', e);
			localParticipated = {};
		}
	}

	function saveLocalParticipated() {
		if (!browser) return;
		try {
			localStorage.setItem(PARTICIPATED_STORAGE_KEY, JSON.stringify(localParticipated));
		} catch (e) {
			console.error('로컬 참여 상태 저장 실패:', e);
		}
	}

	function isParticipated(event: Event): boolean {
		// 로컬스토리지에 저장된 값이 있으면 사용, 없으면 서버 값 사용
		if (event.id in localParticipated) {
			return localParticipated[event.id];
		}
		return event.is_participated;
	}

	// 탭 변경
	function switchTab(tab: TabMode) {
		activeTab = tab;
		currentPage = 1;
		// 익명 사용자: 이벤트 탭은 '오늘 마감' 고정, 팝업 탭은 필터 없음
		if (isAnonymous) {
			filterEventStatus = tab === 'event' ? 'ending_today' : null;
		} else if (tab === 'event') {
			filterEventStatus = 'ongoing';
		} else if (tab === 'popup') {
			filterEventStatus = 'ongoing_or_upcoming';
		}
		fetchEvents();
	}

	// 이벤트/팝업 목록 조회
	async function fetchEvents() {
		loading = true;
		try {
			// 팝업 탭인 경우 popupApi 호출
			if (activeTab === 'popup') {
				const params: Record<string, unknown> = {
					page: currentPage,
					page_size: pageSize,
					sort_by: sortBy === 'event_end' ? 'end_date' : sortBy === 'event_start' ? 'start_date' : sortBy,
					sort_order: sortOrder
				};

				// 팝업 필터
				if (filterEventStatus) params.popup_status = filterEventStatus;
				if (filterBookmarked !== null) params.is_bookmarked = filterBookmarked;
				if (filterSourceType) params.source_type = filterSourceType;
				if (includeUnknownPeriod) params.include_unknown_period = true;

				const response = await popupApi.list(params);
				popups = response.items;
				events = [];
				total = response.total;
				error = null;
			} else {
				// 이벤트 탭인 경우 eventApi 호출
				const params: Record<string, unknown> = {
					page: currentPage,
					page_size: pageSize,
					sort_by: sortBy,
					sort_order: sortOrder,
					event_type: 'event'
				};

				// 추가 필터
				if (filterEventStatus) params.event_status = filterEventStatus;
				if (filterBookmarked !== null) params.is_bookmarked = filterBookmarked;
				if (filterUrlType) params.url_type = filterUrlType;
				if (filterSourceType) params.source_type = filterSourceType;
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

	// 이벤트 상태 필터 변경
	function setEventStatusFilter(status: string | null) {
		filterEventStatus = filterEventStatus === status ? null : status;
		currentPage = 1;
		fetchEvents();
	}

	// 기간 미정 포함 토글
	function toggleIncludeUnknownPeriod() {
		includeUnknownPeriod = !includeUnknownPeriod;
		currentPage = 1;
		fetchEvents();
	}

	// 북마크만 보기 토글
	function toggleBookmarkedFilter() {
		filterBookmarked = filterBookmarked === true ? null : true;
		currentPage = 1;
		fetchEvents();
	}

	// 헤더 클릭 시 정렬 토글
	function toggleSort(column: string) {
		if (sortBy === column) {
			// 같은 컬럼 클릭 시 정렬 순서 토글
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			// 다른 컬럼 클릭 시 해당 컬럼으로 변경, 기본 오름차순 (날짜는 내림차순)
			sortBy = column;
			sortOrder = ['created_at', 'event_end', 'event_start', 'announcement_date'].includes(column) ? 'desc' : 'asc';
		}
		currentPage = 1;
		fetchEvents();
	}

	// 정렬 화살표 표시
	function getSortIcon(column: string): string {
		if (sortBy !== column) return '↕';
		return sortOrder === 'asc' ? '↑' : '↓';
	}

	// 페이지 이동
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

	// 경품 배열 <-> 문자열 변환
	let prizesText = '';
	function prizesToText(prizes: string[] | undefined): string {
		return (prizes || []).join('\n');
	}
	function textToPrizes(text: string): string[] {
		return text.split('\n').map(s => s.trim()).filter(s => s.length > 0);
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
			location_address: '',
			announcement_date: '',
			prizes: [],
			winner_count: undefined,
			purchase_required: undefined
		};
		prizesText = '';
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
		prizesText = prizesToText(event.prizes);
		showEventModal = true;
	}

	// 모달 닫기
	function closeModal() {
		showEventModal = false;
		editingEvent = null;
	}

	// 이벤트 행 클릭 핸들러
	async function handleEventClick(event: Event) {
		// Instagram 출처인 경우 FeedCard 뷰어로 열기
		if (event.source_type === 'instagram' && event.source_instagram_post_id) {
			await openFeedViewer(event);
		} else {
			// 그 외는 기존 수정 모달
			openEditModal(event);
		}
	}

	// Instagram 피드 뷰어 열기
	async function openFeedViewer(event: Event) {
		viewingEvent = event;
		showFeedViewer = true;
		loadingPost = true;
		instagramPost = null;
		mobileViewerTab = 'info';  // 탭 초기화

		try {
			if (event.source_instagram_post_id) {
				instagramPost = await instagramApi.getPost(event.source_instagram_post_id);
			}
		} catch (e) {
			console.error('Instagram 게시물 로드 실패:', e);
		} finally {
			loadingPost = false;
		}
	}

	// 피드 뷰어 닫기
	function closeFeedViewer() {
		showFeedViewer = false;
		viewingEvent = null;
		instagramPost = null;
	}

	// 피드 뷰어에서 이벤트 수정 모달 열기
	function openEditFromViewer() {
		if (viewingEvent) {
			closeFeedViewer();
			openEditModal(viewingEvent);
		}
	}

	// 재크롤링 핸들러 (FeedCard용)
	async function handleRecrawl(postId: number): Promise<void> {
		try {
			await instagramApi.recrawlPost(postId);
			alert('재크롤링 요청이 등록되었습니다. 워커가 처리하면 게시물 정보가 업데이트됩니다.');
		} catch (e) {
			console.error('재크롤링 요청 실패:', e);
			alert('재크롤링 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	// 태그 업데이트 핸들러 (FeedCard용)
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

	// 게시물 삭제 핸들러 (FeedCard용)
	async function handleDeletePost(postId: number): Promise<void> {
		if (!confirm('이 게시물을 삭제하시겠습니까?')) return;
		try {
			await instagramApi.deletePost(postId);
			// 뷰어 닫기
			if (showFeedViewer) closeFeedViewer();
			if (showPopupFeedViewer) closePopupFeedViewer();
			// 목록 새로고침
			await fetchEvents();
		} catch (e) {
			console.error('삭제 실패:', e);
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	// 이벤트 저장
	async function saveEvent() {
		if (!eventForm.title.trim()) {
			alert('제목을 입력해주세요.');
			return;
		}
		isSaving = true;
		try {
			// prizesText를 배열로 변환
			const formData = {
				...eventForm,
				prizes: textToPrizes(prizesText)
			};
			if (editingEvent) {
				const updateData: EventUpdate = { ...formData };
				await eventApi.update(editingEvent.id, updateData);
			} else {
				await eventApi.create(formData);
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

	// 참여 완료 토글 (로컬스토리지 기반)
	function toggleParticipate(event: Event, e: MouseEvent) {
		e.stopPropagation();
		const currentState = isParticipated(event);
		localParticipated[event.id] = !currentState;
		saveLocalParticipated();
		// 뷰 업데이트를 위해 재할당
		localParticipated = { ...localParticipated };
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

	// 팝업 오늘 마감 여부
	function isPopupEndingToday(popup: Popup): boolean {
		if (!popup.end_date) return false;
		const today = new Date().toISOString().split('T')[0];
		return popup.end_date === today;
	}

	// 팝업 기간 미정 여부
	function isPopupUnknownPeriod(popup: Popup): boolean {
		return !popup.end_date;
	}

	// 팝업 행 클릭 핸들러
	async function handlePopupClick(popup: Popup) {
		// Instagram 출처인 경우 FeedCard 뷰어로 열기
		if (popup.source_type === 'instagram' && popup.source_instagram_post_id) {
			await openPopupFeedViewer(popup);
		} else {
			// 그 외는 Instagram 링크로 이동
			if (popup.source_instagram_url) {
				window.open(popup.source_instagram_url, '_blank');
			}
		}
	}

	// 팝업 Instagram 피드 뷰어 열기
	async function openPopupFeedViewer(popup: Popup) {
		viewingPopup = popup;
		showPopupFeedViewer = true;
		loadingPost = true;
		instagramPost = null;
		mobileViewerTab = 'info';  // 탭 초기화

		try {
			if (popup.source_instagram_post_id) {
				instagramPost = await instagramApi.getPost(popup.source_instagram_post_id);
			}
		} catch (e) {
			console.error('Instagram 게시물 로드 실패:', e);
		} finally {
			loadingPost = false;
		}
	}

	// 팝업 피드 뷰어 닫기
	function closePopupFeedViewer() {
		showPopupFeedViewer = false;
		viewingPopup = null;
		instagramPost = null;
	}

	// 팝업 북마크 토글
	async function togglePopupBookmark(popup: Popup, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await popupApi.toggleBookmark(popup.id);
			popup.is_bookmarked = result.is_bookmarked;
			popups = [...popups];
		} catch (err) {
			console.error('북마크 토글 실패:', err);
		}
	}

	// 팝업 방문 완료 토글
	async function togglePopupVisited(popup: Popup, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await popupApi.toggleVisited(popup.id);
			popup.is_visited = result.is_visited;
			popups = [...popups];
		} catch (err) {
			console.error('방문 토글 실패:', err);
		}
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

	onMount(async () => {
		// 로컬 참여 상태 로드
		loadLocalParticipated();

		// FeedCard용 태그 목록 로드
		try {
			availableTags = await instagramTagApi.getTags();
		} catch (e) {
			console.error('태그 목록 로드 실패:', e);
		}

		// PWA Share Target에서 전달된 URL 처리
		const action = $pageStore.url.searchParams.get('action');
		const sharedUrl = $pageStore.url.searchParams.get('url');

		if (action === 'add' && sharedUrl) {
			// 이벤트 생성 모달 열기 + URL 자동 입력
			eventForm = {
				title: '',
				event_type: 'event',
				event_url: sharedUrl
			};
			showEventModal = true;
		}

		// 익명 사용자: 이벤트 탭은 '오늘 마감' 고정, 팝업 탭은 필터 없음
		if (!$isLoggedIn) {
			filterEventStatus = activeTab === 'event' ? 'ending_today' : null;
		}

		fetchEvents();
	});
</script>

<div class="p-4 md:p-6">
	<!-- 헤더 -->
	<div class="mb-4 md:mb-6 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
		<div class="flex items-center justify-between sm:justify-start gap-3">
			<h2 class="text-xl md:text-2xl font-bold text-gray-900">이벤트 관리</h2>
			{#if $isAdmin}
				<button
					onclick={openCreateModal}
					class="btn btn-primary btn-sm"
				>
					+ 새 이벤트
				</button>
			{/if}
		</div>

		<!-- 필터 요약 + 모바일 필터 토글 -->
		<div class="flex items-center gap-2">
			{#if isAnonymous && activeTab === 'event'}
				<!-- 익명 사용자 이벤트 탭: 오늘 마감 고정 배지 -->
				<span class="px-2 py-1 text-xs font-medium bg-orange-100 text-orange-700 rounded-full">
					오늘 마감
				</span>
			{:else if !isAnonymous}
				<!-- 모바일 필터 토글 버튼 -->
				<button
					onclick={() => showFilters = !showFilters}
					class="md:hidden btn btn-secondary btn-sm flex items-center gap-1"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
					</svg>
					필터
					{#if activeFilterCount > 0}
						<span class="px-1.5 py-0.5 text-xs bg-blue-600 text-white rounded-full">{activeFilterCount}</span>
					{/if}
				</button>
			{/if}

			<span class="text-sm text-gray-600">총 {total}건</span>
			{#if filterBookmarked}
				<span class="hidden sm:inline text-sm text-yellow-600">(북마크만)</span>
			{/if}
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
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'event' ? 'border-purple-600 text-purple-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				온라인 이벤트
			</button>
			<button
				onclick={() => switchTab('popup')}
				class="pb-2 px-1 text-sm font-medium border-b-2 transition-colors {activeTab === 'popup' ? 'border-pink-600 text-pink-600' : 'border-transparent text-gray-500 hover:text-gray-700'}"
			>
				팝업
			</button>
		</nav>
	</div>

	<!-- 모바일 필터 패널 (접이식) - 로그인 사용자만 -->
	{#if !isAnonymous}
	<div
		class="md:hidden mb-4 bg-white rounded-lg border border-gray-200 overflow-hidden transition-all duration-300"
		class:hidden={!showFilters}
	>
		<div class="p-4 space-y-4">
			<!-- 이벤트 상태 필터 -->
			<div class="flex flex-col gap-2">
				<label class="text-sm font-medium text-gray-700">상태</label>
				<div class="flex flex-wrap gap-2">
					{#each eventStatusOptions as opt}
						<button
							onclick={() => setEventStatusFilter(opt.value)}
							class="px-3 py-1.5 text-sm rounded-full transition-colors {filterEventStatus === opt.value ? opt.color + ' ring-2 ring-offset-1 ring-gray-400' : 'bg-gray-100 text-gray-600'}"
						>
							{opt.label}
						</button>
					{/each}
				</div>
			</div>

			<!-- 옵션 체크박스 -->
			<div class="flex flex-col gap-3">
				<label class="flex items-center gap-2 cursor-pointer">
					<input
						type="checkbox"
						checked={includeUnknownPeriod}
						onchange={toggleIncludeUnknownPeriod}
						class="w-4 h-4 text-amber-600 rounded border-gray-300 focus:ring-amber-500"
					/>
					<span class="text-sm text-gray-600">기간 미정 포함</span>
				</label>
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

			<!-- 닫기 버튼 -->
			<div class="pt-2 border-t border-gray-100">
				<button
					onclick={() => showFilters = false}
					class="w-full btn btn-secondary btn-sm"
				>
					닫기
				</button>
			</div>
		</div>
	</div>
	{/if}

	<!-- 데스크톱 필터 영역 - 로그인 사용자만 -->
	{#if !isAnonymous}
	<div class="hidden md:flex mb-4 flex-wrap gap-2 items-center">
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
	{/if}

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
			<p class="text-lg">{activeTab === 'popup' ? '등록된 팝업이 없습니다' : '등록된 이벤트가 없습니다'}</p>
			<p class="text-sm mt-2">{activeTab === 'popup' ? '새 팝업을 등록하면 여기에 표시됩니다' : '새 이벤트를 등록하면 여기에 표시됩니다'}</p>
			{#if $isAdmin}
				<button onclick={openCreateModal} class="mt-4 btn btn-primary btn-sm">
					+ {activeTab === 'popup' ? '새 팝업 등록' : '새 이벤트 등록'}
				</button>
			{/if}
		</div>
	{:else}
		<!-- 팝업 -->
		{#if activeTab === 'popup'}
		<!-- 모바일 카드 리스트 -->
		<div class="md:hidden space-y-3 mb-6">
			{#each popups as popup (popup.id)}
				<div
					class="bg-white rounded-lg border border-gray-200 p-3 cursor-pointer hover:shadow-md transition-shadow {isPopupEndingToday(popup) ? 'border-orange-300 bg-orange-50' : isPopupUnknownPeriod(popup) ? 'border-amber-200 bg-amber-50' : ''}"
					onclick={() => handlePopupClick(popup)}
					onkeydown={(e) => e.key === 'Enter' && handlePopupClick(popup)}
					role="button"
					tabindex="0"
				>
					<div class="flex justify-between items-start gap-2 mb-2">
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2 mb-1">
								<span class="px-2 py-0.5 text-xs rounded-full {getEventStatusColor(popup.popup_status)}">
									{eventStatusOptions.find(o => o.value === popup.popup_status)?.label || popup.popup_status}
								</span>
								{#if popup.source_type === 'instagram'}
									<span class="px-1.5 py-0.5 text-xs rounded bg-pink-100 text-pink-600">IG</span>
								{/if}
							</div>
							<h3 class="font-medium text-gray-900 truncate" title={popup.title}>{popup.title}</h3>
							{#if popup.brand || popup.organizer}
								<p class="text-sm text-blue-600 truncate">{popup.brand || popup.organizer}</p>
							{/if}
						</div>
						<!-- 북마크/방문 버튼 -->
						<div class="flex items-center gap-1" onclick={(e) => e.stopPropagation()}>
							<button
								onclick={(e) => togglePopupBookmark(popup, e)}
								class="text-xl transition-colors {popup.is_bookmarked ? 'text-yellow-500' : 'text-gray-300'}"
							>
								{popup.is_bookmarked ? '★' : '☆'}
							</button>
						</div>
					</div>
					<div class="flex flex-wrap items-center gap-2 text-xs text-gray-500">
						<!-- 기간 -->
						{#if popup.end_date}
							{#if isPopupEndingToday(popup)}
								<span class="font-bold text-orange-600 bg-orange-100 px-1.5 py-0.5 rounded">오늘 마감!</span>
							{:else}
								<span>~ {formatDate(popup.end_date)}</span>
							{/if}
						{:else}
							<span class="text-amber-600 bg-amber-100 px-1.5 py-0.5 rounded">기간 미정</span>
						{/if}
						<!-- 위치 -->
						{#if popup.venue_name}
							<span class="text-gray-600 truncate max-w-[120px]">{popup.venue_name}</span>
						{/if}
						<!-- 방문 상태 -->
						<span class="ml-auto px-1.5 py-0.5 rounded {popup.is_visited ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}">
							{popup.is_visited ? '방문' : '미방문'}
						</span>
					</div>
				</div>
			{/each}
		</div>
		<!-- 데스크톱 테이블 -->
		<div class="hidden md:block bg-white rounded-lg border border-gray-200 overflow-hidden mb-6">
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">상태</th>
							<th class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">브랜드</th>
							<th class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[180px]">제목</th>
							<th class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">기간</th>
							<th class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[150px]">위치</th>
							<th class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">출처</th>
							<th class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">원본</th>
							<th class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">관리</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each popups as popup (popup.id)}
							<tr
								class="cursor-pointer transition-colors {isPopupEndingToday(popup) ? 'bg-orange-100 hover:bg-orange-200 font-semibold' : isPopupUnknownPeriod(popup) ? 'bg-amber-50 hover:bg-amber-100' : 'hover:bg-gray-50'}"
								onclick={() => handlePopupClick(popup)}
							>
								<!-- 상태 -->
								<td class="px-2 py-2">
									<span class="px-2 py-0.5 text-xs rounded-full {getEventStatusColor(popup.popup_status)}">
										{eventStatusOptions.find(o => o.value === popup.popup_status)?.label || popup.popup_status}
									</span>
								</td>
								<!-- 브랜드/주최 -->
								<td class="px-2 py-2 max-w-[100px]">
									{#if popup.brand || popup.organizer}
										<span class="text-sm font-medium text-blue-600 truncate block" title={popup.brand || popup.organizer}>
											{popup.brand || popup.organizer}
										</span>
									{:else}
										<span class="text-xs text-gray-400">-</span>
									{/if}
								</td>
								<!-- 제목 -->
								<td class="px-2 py-2 max-w-[180px]">
									<span class="block truncate text-sm font-medium text-gray-900" title={popup.title}>
										{popup.title}
									</span>
									{#if popup.summary}
										<span class="block truncate text-xs text-gray-500 line-clamp-2" title={popup.summary}>
											{truncate(popup.summary, 40)}
										</span>
									{/if}
								</td>
								<!-- 기간 -->
								<td class="px-2 py-2 text-sm text-gray-600 whitespace-nowrap">
									{#if popup.end_date}
										<div class="flex flex-col gap-0.5">
											{#if popup.start_date}
												<span class="text-xs text-gray-500">{formatDate(popup.start_date)}</span>
											{/if}
											{#if isPopupEndingToday(popup)}
												<span class="text-xs font-bold text-orange-600 bg-orange-50 px-1 rounded">오늘 마감!</span>
											{:else}
												<span class="text-xs text-gray-500">~ {formatDate(popup.end_date)}</span>
											{/if}
										</div>
									{:else if popup.start_date}
										<div class="flex flex-col gap-0.5">
											<span class="text-xs text-gray-500">{formatDate(popup.start_date)} ~</span>
											<span class="text-xs text-amber-600 bg-amber-50 px-1 rounded">기간 미정</span>
										</div>
									{:else}
										<span class="text-xs text-amber-600 bg-amber-50 px-1 rounded">기간 미정</span>
									{/if}
								</td>
								<!-- 위치 -->
								<td class="px-2 py-2 max-w-[150px]">
									{#if popup.venue_name}
										<div class="flex flex-col">
											<span class="text-xs font-medium text-gray-700 truncate" title={popup.venue_name}>
												{popup.venue_name}
											</span>
											{#if popup.address}
												<span class="text-xs text-gray-500 truncate" title={popup.address}>
													{truncate(popup.address, 20)}
												</span>
											{/if}
										</div>
									{:else}
										<span class="text-xs text-gray-400">-</span>
									{/if}
								</td>
								<!-- 출처 -->
								<td class="px-2 py-2 text-center">
									<span class="px-1.5 py-0.5 text-xs rounded {popup.source_type === 'instagram' ? 'bg-pink-100 text-pink-600' : 'bg-gray-100 text-gray-600'}">
										{popup.source_type === 'instagram' ? 'IG' : popup.source_type === 'manual' ? '수동' : popup.source_type}
									</span>
								</td>
								<!-- 원본 링크 -->
								<td class="px-2 py-2 text-center" onclick={(e) => e.stopPropagation()}>
									<div class="flex gap-1 justify-center">
										{#if popup.official_url}
											<a
												href={popup.official_url}
												target="_blank"
												rel="noopener noreferrer"
												class="text-xs text-blue-600 hover:text-blue-800 hover:underline"
												title="공식 사이트"
											>
												공식
											</a>
										{/if}
										{#if popup.source_type === 'instagram' && popup.source_instagram_url}
											<a
												href={popup.source_instagram_url}
												target="_blank"
												rel="noopener noreferrer"
												class="text-xs text-pink-600 hover:text-pink-800 hover:underline font-medium"
												title="Instagram 원본"
											>
												IG
											</a>
										{/if}
										{#if !popup.official_url && !(popup.source_type === 'instagram' && popup.source_instagram_url)}
											<span class="text-xs text-gray-400">-</span>
										{/if}
									</div>
								</td>
								<!-- 관리 (북마크/방문) -->
								<td class="px-2 py-2" onclick={(e) => e.stopPropagation()}>
									<div class="flex items-center gap-1 justify-center">
										<button
											onclick={(e) => togglePopupBookmark(popup, e)}
											class="text-lg transition-colors {popup.is_bookmarked ? 'text-yellow-500' : 'text-gray-300 hover:text-yellow-400'}"
											title={popup.is_bookmarked ? '북마크 해제' : '북마크'}
										>
											{popup.is_bookmarked ? '★' : '☆'}
										</button>
										<button
											onclick={(e) => togglePopupVisited(popup, e)}
											class="px-1.5 py-0.5 text-xs rounded transition-colors {popup.is_visited ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}"
											title={popup.is_visited ? '방문 취소' : '방문 완료'}
										>
											{popup.is_visited ? '방문' : '미방문'}
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		{:else}
		<!-- 이벤트 -->
		<!-- 모바일 카드 리스트 -->
		<div class="md:hidden space-y-3 mb-6">
			{#each events as event (event.id)}
				<div
					class="bg-white rounded-lg border border-gray-200 p-3 cursor-pointer hover:shadow-md transition-shadow {isEndingToday(event) ? 'border-orange-300 bg-orange-50' : isUnknownPeriod(event) ? 'border-amber-200 bg-amber-50' : ''}"
					onclick={() => handleEventClick(event)}
					onkeydown={(e) => e.key === 'Enter' && handleEventClick(event)}
					role="button"
					tabindex="0"
				>
					<div class="flex justify-between items-start gap-2 mb-2">
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2 mb-1">
								<span class="px-2 py-0.5 text-xs rounded-full {getEventStatusColor(event.event_status)}">
									{eventStatusOptions.find(o => o.value === event.event_status)?.label || event.event_status}
								</span>
								{#if event.source_type === 'instagram'}
									<span class="px-1.5 py-0.5 text-xs rounded bg-pink-100 text-pink-600">IG</span>
								{/if}
								{#if event.purchase_required === 'no'}
									<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 text-green-600">무료</span>
								{:else if event.purchase_required === 'yes_all'}
									<span class="px-1.5 py-0.5 text-xs rounded bg-red-100 text-red-600">구매</span>
								{/if}
							</div>
							<h3 class="font-medium text-gray-900 truncate" title={event.title}>{event.title}</h3>
							{#if event.organizer}
								<p class="text-sm text-blue-600 truncate">{event.organizer}</p>
							{/if}
						</div>
						<!-- 북마크/참여 버튼 -->
						<div class="flex items-center gap-1" onclick={(e) => e.stopPropagation()}>
							<button
								onclick={(e) => toggleBookmark(event, e)}
								class="text-xl transition-colors {event.is_bookmarked ? 'text-yellow-500' : 'text-gray-300'}"
							>
								{event.is_bookmarked ? '★' : '☆'}
							</button>
						</div>
					</div>
					<div class="flex items-center gap-2 text-xs text-gray-500">
						<div class="flex flex-wrap items-center gap-2 flex-1">
							<!-- 기간 -->
							{#if event.event_end}
								{#if isEndingToday(event)}
									<span class="font-bold text-orange-600 bg-orange-100 px-1.5 py-0.5 rounded">오늘 마감!</span>
								{:else}
									<span>~ {formatDate(event.event_end)}</span>
								{/if}
							{:else}
								<span class="text-amber-600 bg-amber-100 px-1.5 py-0.5 rounded">기간 미정</span>
							{/if}
							<!-- 경품 -->
							{#if event.prizes && event.prizes.length > 0}
								<span class="text-yellow-700 bg-yellow-50 px-1.5 py-0.5 rounded truncate max-w-[100px]">{event.prizes[0]}</span>
							{/if}
							<!-- 당첨자 수 -->
							{#if event.winner_count}
								<span class="text-purple-600">{event.winner_count}명</span>
							{/if}
						</div>
						<!-- 참여 체크박스 (큰 사이즈) -->
						<button
							onclick={(e) => toggleParticipate(event, e)}
							class="flex items-center justify-center w-10 h-10 rounded-lg border-2 transition-all {isParticipated(event) ? 'bg-green-500 border-green-500 text-white' : 'bg-white border-gray-300 text-gray-400 hover:border-green-400'}"
							title={isParticipated(event) ? '참여 취소' : '참여 완료'}
						>
							{#if isParticipated(event)}
								<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
								</svg>
							{:else}
								<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
								</svg>
							{/if}
						</button>
					</div>
				</div>
			{/each}
		</div>
		<!-- 데스크톱 테이블 -->
		<div class="hidden md:block bg-white rounded-lg border border-gray-200 overflow-hidden mb-6">
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">상태</th>
							{#if activeTab === 'all'}
								<th class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">유형</th>
							{/if}
							<th
								class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap cursor-pointer hover:bg-gray-100 select-none"
								onclick={() => toggleSort('organizer')}
							>
								주최 <span class="text-gray-400">{getSortIcon('organizer')}</span>
							</th>
							<th
								class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[180px] cursor-pointer hover:bg-gray-100 select-none"
								onclick={() => toggleSort('title')}
							>
								제목 <span class="text-gray-400">{getSortIcon('title')}</span>
							</th>
							<th
								class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap cursor-pointer hover:bg-gray-100 select-none"
								onclick={() => toggleSort('event_end')}
							>
								기간 <span class="text-gray-400">{getSortIcon('event_end')}</span>
							</th>
							<th
								class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap cursor-pointer hover:bg-gray-100 select-none"
								onclick={() => toggleSort('announcement_date')}
							>
								발표일 <span class="text-gray-400">{getSortIcon('announcement_date')}</span>
							</th>
							<th class="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[120px]">경품</th>
							<th class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">당첨자</th>
							<th class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">조건</th>
							<th
								class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap cursor-pointer hover:bg-gray-100 select-none"
								onclick={() => toggleSort('created_at')}
							>
								수집일 <span class="text-gray-400">{getSortIcon('created_at')}</span>
							</th>
							<th class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">출처</th>
							<th class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">원본</th>
							<th class="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">관리</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each events as event (event.id)}
							<tr
								class="cursor-pointer transition-colors {isEndingToday(event) ? 'bg-orange-100 hover:bg-orange-200 font-semibold' : isUnknownPeriod(event) ? 'bg-amber-50 hover:bg-amber-100' : 'hover:bg-gray-50'}"
								onclick={() => handleEventClick(event)}
							>
								<!-- 상태 -->
								<td class="px-2 py-2">
									<span class="px-2 py-0.5 text-xs rounded-full {getEventStatusColor(event.event_status)}">
										{eventStatusOptions.find(o => o.value === event.event_status)?.label || event.event_status}
									</span>
								</td>
								<!-- 유형 (전체 탭만) -->
								{#if activeTab === 'all'}
									<td class="px-2 py-2">
										<span class="px-2 py-0.5 text-xs rounded {event.event_type === 'popup' ? 'bg-pink-100 text-pink-700' : event.event_type === 'event' ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'}">
											{event.event_type === 'popup' ? '팝업' : event.event_type === 'event' ? '이벤트' : event.event_type}
										</span>
									</td>
								{/if}
								<!-- 주최 -->
								<td class="px-2 py-2 max-w-[100px]">
									{#if event.organizer}
										<span class="text-sm font-medium text-blue-600 truncate block" title={event.organizer}>
											{event.organizer}
										</span>
									{:else}
										<span class="text-xs text-gray-400">-</span>
									{/if}
								</td>
								<!-- 제목 -->
								<td class="px-2 py-2 max-w-[180px]">
									<span class="block truncate text-sm font-medium text-gray-900" title={event.title}>
										{event.title}
									</span>
									{#if event.summary}
										<span class="block truncate text-xs text-gray-500 line-clamp-2" title={event.summary}>
											{truncate(event.summary, 40)}
										</span>
									{/if}
								</td>
								<!-- 기간 -->
								<td class="px-2 py-2 text-sm text-gray-600 whitespace-nowrap">
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
								<!-- 발표일 -->
								<td class="px-2 py-2 text-xs text-gray-600 whitespace-nowrap">
									{#if event.announcement_date}
										<span class="text-gray-700">{formatDate(event.announcement_date)}</span>
									{:else}
										<span class="text-gray-400">-</span>
									{/if}
								</td>
								<!-- 경품 -->
								<td class="px-2 py-2 max-w-[120px]">
									{#if event.prizes && event.prizes.length > 0}
										<div class="flex flex-wrap gap-0.5">
											{#each event.prizes.slice(0, 2) as prize}
												<span class="text-xs bg-yellow-50 text-yellow-700 px-1 rounded truncate max-w-[100px]" title={prize}>
													{truncate(prize, 12)}
												</span>
											{/each}
											{#if event.prizes.length > 2}
												<span class="text-xs text-gray-500">+{event.prizes.length - 2}개</span>
											{/if}
										</div>
									{:else}
										<span class="text-xs text-gray-400">-</span>
									{/if}
								</td>
								<!-- 당첨자 -->
								<td class="px-2 py-2 text-center">
									{#if event.winner_count}
										<span class="text-sm font-medium text-purple-600">{event.winner_count}명</span>
									{:else}
										<span class="text-xs text-gray-400">-</span>
									{/if}
								</td>
								<!-- 조건 -->
								<td class="px-2 py-2 text-center">
									{#if event.purchase_required === 'yes_all'}
										<span class="text-xs bg-red-100 text-red-600 px-1.5 py-0.5 rounded">구매필수</span>
									{:else if event.purchase_required === 'yes_partial'}
										<span class="text-xs bg-orange-100 text-orange-600 px-1.5 py-0.5 rounded">부분구매</span>
									{:else if event.purchase_required === 'no'}
										<span class="text-xs bg-green-100 text-green-600 px-1.5 py-0.5 rounded">무료</span>
									{:else}
										<span class="text-xs text-gray-400">-</span>
									{/if}
								</td>
								<!-- 수집일 -->
								<td class="px-2 py-2 text-center text-xs text-gray-500 whitespace-nowrap">
									{formatDate(event.created_at)}
								</td>
								<!-- 출처 -->
								<td class="px-2 py-2 text-center">
									<span class="px-1.5 py-0.5 text-xs rounded {event.source_type === 'instagram' ? 'bg-pink-100 text-pink-600' : 'bg-gray-100 text-gray-600'}">
										{event.source_type === 'instagram' ? 'IG' : event.source_type === 'manual' ? '수동' : event.source_type}
									</span>
								</td>
								<!-- 원본 링크 -->
								<td class="px-2 py-2 text-center" onclick={(e) => e.stopPropagation()}>
									<div class="flex gap-1 justify-center">
										{#if event.event_url}
											<a
												href={event.event_url}
												target="_blank"
												rel="noopener noreferrer"
												class="text-xs text-blue-600 hover:text-blue-800 hover:underline"
												title="이벤트 참여"
											>
												참여
											</a>
										{/if}
										{#if event.source_type === 'instagram' && event.source_instagram_url}
											<a
												href={event.source_instagram_url}
												target="_blank"
												rel="noopener noreferrer"
												class="text-xs text-pink-600 hover:text-pink-800 hover:underline font-medium"
												title="Instagram 원본"
											>
												IG
											</a>
										{/if}
										{#if !event.event_url && !(event.source_type === 'instagram' && event.source_instagram_url)}
											<span class="text-xs text-gray-400">-</span>
										{/if}
									</div>
								</td>
								<!-- 관리 (북마크/참여/삭제) -->
								<td class="px-2 py-2" onclick={(e) => e.stopPropagation()}>
									<div class="flex items-center gap-1 justify-center">
										<button
											onclick={(e) => toggleBookmark(event, e)}
											class="text-lg transition-colors {event.is_bookmarked ? 'text-yellow-500' : 'text-gray-300 hover:text-yellow-400'}"
											title={event.is_bookmarked ? '북마크 해제' : '북마크'}
										>
											{event.is_bookmarked ? '★' : '☆'}
										</button>
										<button
											onclick={(e) => toggleParticipate(event, e)}
											class="px-1.5 py-0.5 text-xs rounded transition-colors {isParticipated(event) ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}"
											title={isParticipated(event) ? '참여 취소' : '참여 완료'}
										>
											{isParticipated(event) ? '참여' : '미참여'}
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		{/if}

		<!-- 페이지네이션 -->
		<div class="flex flex-col sm:flex-row justify-between items-center gap-3">
			<span class="text-sm text-gray-500">
				전체 {total}개 중 {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, total)}
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

					<!-- 경품 -->
					<div>
						<label for="event-prizes" class="block text-sm font-medium text-gray-700 mb-1">경품</label>
						<textarea
							id="event-prizes"
							bind:value={prizesText}
							placeholder="경품을 한 줄에 하나씩 입력&#10;예: 아이패드 프로&#10;에어팟 프로"
							rows="3"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
						></textarea>
						<p class="mt-1 text-xs text-gray-500">한 줄에 하나의 경품 입력</p>
					</div>

					<!-- 당첨자 수 + 조건 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="event-winner-count" class="block text-sm font-medium text-gray-700 mb-1">당첨자 수</label>
							<input
								id="event-winner-count"
								type="number"
								min="0"
								bind:value={eventForm.winner_count}
								placeholder="예: 10"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="event-purchase" class="block text-sm font-medium text-gray-700 mb-1">구매 조건</label>
							<select
								id="event-purchase"
								bind:value={eventForm.purchase_required}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							>
								<option value={undefined}>선택 안함</option>
								<option value="no">무료 (구매 불필요)</option>
								<option value="yes_partial">부분 구매 필요</option>
								<option value="yes_all">구매 필수</option>
							</select>
						</div>
					</div>

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

<!-- Instagram 피드 뷰어 모달 -->
{#if showFeedViewer && viewingEvent}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/60 z-50 overflow-y-auto p-4"
		onclick={closeFeedViewer}
		onkeydown={(e) => e.key === 'Escape' && closeFeedViewer()}
		role="dialog"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div
			class="max-w-5xl w-full mx-auto my-4"
			onclick={(e) => e.stopPropagation()}
		>
			<!-- 데스크톱 레이아웃: lg 이상 -->
			<div class="hidden lg:flex gap-4">
				<!-- 왼쪽: AI 분석 (이벤트 정보) -->
				<div class="bg-white rounded-xl p-4 w-80 shrink-0 max-h-[85vh] overflow-y-auto">
					<div class="flex items-center justify-between mb-3">
						<h4 class="font-semibold text-sm text-gray-900 flex items-center gap-2">
							<svg class="w-4 h-4 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
							</svg>
							AI 분석
						</h4>
						<div class="flex items-center gap-2">
							<button
								onclick={openEditFromViewer}
								class="text-xs text-purple-600 hover:text-purple-800 underline"
							>
								수정
							</button>
							<button
								onclick={closeFeedViewer}
								class="p-1 hover:bg-gray-100 rounded-full"
								aria-label="닫기"
							>
								<svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
								</svg>
							</button>
						</div>
					</div>

					<div class="space-y-2 text-xs bg-gradient-to-r from-purple-50 to-blue-50 rounded-lg p-3">
						<!-- 분류 -->
						<div class="flex items-center gap-2">
							<span class="text-gray-500 w-12">분류:</span>
							<span class="px-2 py-0.5 font-medium rounded-full bg-purple-100 text-purple-700">
								{viewingEvent.event_type === 'popup' ? '팝업' : '이벤트'}
							</span>
							<span class="px-2 py-0.5 rounded-full {getEventStatusColor(viewingEvent.event_status)}">
								{eventStatusOptions.find(o => o.value === viewingEvent.event_status)?.label}
							</span>
						</div>
						<!-- 주최 -->
						{#if viewingEvent.organizer}
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">주최:</span>
								<span class="text-gray-900">{viewingEvent.organizer}</span>
							</div>
						{/if}
						<!-- 기간 -->
						{#if viewingEvent.event_start || viewingEvent.event_end}
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">기간:</span>
								<span class="text-gray-900">
									{viewingEvent.event_start || '?'} ~ {viewingEvent.event_end || '?'}
									{#if viewingEvent.days_remaining !== null}
										<span class="ml-1 {viewingEvent.days_remaining === 0 ? 'text-orange-600 font-bold' : viewingEvent.days_remaining > 0 ? 'text-blue-600' : 'text-gray-400'}">
											({getDaysRemaining(viewingEvent)})
										</span>
									{/if}
								</span>
							</div>
						{/if}
						<!-- 발표일 -->
						{#if viewingEvent.announcement_date}
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">발표일:</span>
								<span class="text-gray-900">{viewingEvent.announcement_date}</span>
							</div>
						{/if}
						<!-- 구매조건 -->
						{#if viewingEvent.purchase_required}
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">구매:</span>
								<span class="px-1.5 py-0.5 rounded {viewingEvent.purchase_required === 'no' ? 'bg-green-100 text-green-700' : viewingEvent.purchase_required === 'yes_all' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'}">
									{viewingEvent.purchase_required === 'no' ? '불필요' : viewingEvent.purchase_required === 'yes_all' ? '전체 필요' : '부분 필요'}
								</span>
							</div>
						{/if}
						<!-- 당첨자 -->
						{#if viewingEvent.winner_count}
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">당첨자:</span>
								<span class="text-gray-900">{viewingEvent.winner_count}명</span>
							</div>
						{/if}
						<!-- 경품 -->
						{#if viewingEvent.prizes && viewingEvent.prizes.length > 0}
							<div class="flex items-start gap-2">
								<span class="text-gray-500 w-12 shrink-0">경품:</span>
								<div class="flex flex-wrap gap-1">
									{#each viewingEvent.prizes as prize}
										<span class="px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded">{prize}</span>
									{/each}
								</div>
							</div>
						{/if}
						<!-- 요약 -->
						{#if viewingEvent.summary}
							<div class="flex items-start gap-2">
								<span class="text-gray-500 w-12 shrink-0">요약:</span>
								<p class="text-gray-700">{viewingEvent.summary}</p>
							</div>
						{/if}
					</div>

					<!-- 링크 -->
					{#if viewingEvent.event_url}
						<div class="mt-3 pt-3 border-t border-gray-100">
							<a
								href={viewingEvent.event_url}
								target="_blank"
								rel="noopener noreferrer"
								class="flex items-center gap-2 text-sm text-blue-600 hover:underline"
							>
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
								</svg>
								이벤트 참여
							</a>
						</div>
					{/if}

					<!-- 북마크/참여 -->
					<div class="mt-3 pt-3 border-t border-gray-100 flex gap-2">
						<button
							onclick={(e) => { e.stopPropagation(); toggleBookmark(viewingEvent!, e); }}
							class="flex-1 py-2 text-xs rounded transition-colors {viewingEvent.is_bookmarked ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
						>
							{viewingEvent.is_bookmarked ? '★ 북마크됨' : '☆ 북마크'}
						</button>
						<button
							onclick={(e) => { e.stopPropagation(); toggleParticipate(viewingEvent!, e); }}
							class="flex-1 py-2 text-xs rounded transition-colors {isParticipated(viewingEvent) ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
						>
							{isParticipated(viewingEvent) ? '✓ 참여완료' : '참여하기'}
						</button>
					</div>

					<!-- 삭제 -->
					<button
						onclick={() => { deleteEvent(viewingEvent!.id); closeFeedViewer(); }}
						class="w-full mt-2 py-2 text-xs text-red-600 hover:bg-red-50 rounded transition-colors"
					>
						이벤트 삭제
					</button>
				</div>

				<!-- 오른쪽: FeedCard -->
				<div class="flex-shrink-0 flex justify-center">
					{#if loadingPost}
						<div class="bg-white rounded-xl p-8 flex items-center justify-center w-[468px] h-[300px]">
							<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-600"></div>
						</div>
					{:else if instagramPost}
						<FeedCard
							post={instagramPost}
							detailMode={true}
							onClose={closeFeedViewer}
							onDelete={handleDeletePost}
							onRecrawl={handleRecrawl}
							{availableTags}
							onTagsUpdate={handleTagsUpdate}
						/>
					{:else}
						<div class="bg-white rounded-xl p-8 text-center w-[468px]">
							<p class="text-gray-500 mb-4">Instagram 게시물을 불러올 수 없습니다.</p>
							{#if viewingEvent.source_instagram_url}
								<a
									href={viewingEvent.source_instagram_url}
									target="_blank"
									rel="noopener noreferrer"
									class="btn btn-primary btn-sm"
								>
									Instagram에서 보기
								</a>
							{/if}
						</div>
					{/if}
				</div>
			</div>

			<!-- 모바일 레이아웃: lg 미만 -->
			<div class="lg:hidden">
				<!-- 탭 헤더 -->
				<div class="flex bg-white rounded-t-xl border-b border-gray-200">
					<button
						onclick={() => mobileViewerTab = 'info'}
						class="flex-1 py-3 text-sm font-medium transition-colors {mobileViewerTab === 'info' ? 'border-b-2 border-purple-600 text-purple-600' : 'text-gray-500'}"
					>
						AI 분석
					</button>
					<button
						onclick={() => mobileViewerTab = 'feed'}
						class="flex-1 py-3 text-sm font-medium transition-colors {mobileViewerTab === 'feed' ? 'border-b-2 border-purple-600 text-purple-600' : 'text-gray-500'}"
					>
						원본 피드
					</button>
					<button
						onclick={closeFeedViewer}
						class="px-4 py-3 text-gray-500 hover:text-gray-700"
						aria-label="닫기"
					>
						<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				</div>

				<!-- 탭 내용 -->
				{#if mobileViewerTab === 'info'}
					<!-- AI 분석 탭 -->
					<div class="bg-white rounded-b-xl p-4">
						<div class="flex items-center justify-between mb-3">
							<h4 class="font-semibold text-sm text-gray-900 flex items-center gap-2">
								<svg class="w-4 h-4 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
								</svg>
								AI 분석
							</h4>
							<button
								onclick={openEditFromViewer}
								class="text-xs text-purple-600 hover:text-purple-800 underline"
							>
								수정
							</button>
						</div>

						<div class="space-y-2 text-xs bg-gradient-to-r from-purple-50 to-blue-50 rounded-lg p-3">
							<!-- 분류 -->
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">분류:</span>
								<span class="px-2 py-0.5 font-medium rounded-full bg-purple-100 text-purple-700">
									{viewingEvent.event_type === 'popup' ? '팝업' : '이벤트'}
								</span>
								<span class="px-2 py-0.5 rounded-full {getEventStatusColor(viewingEvent.event_status)}">
									{eventStatusOptions.find(o => o.value === viewingEvent.event_status)?.label}
								</span>
							</div>
							<!-- 주최 -->
							{#if viewingEvent.organizer}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">주최:</span>
									<span class="text-gray-900">{viewingEvent.organizer}</span>
								</div>
							{/if}
							<!-- 기간 -->
							{#if viewingEvent.event_start || viewingEvent.event_end}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">기간:</span>
									<span class="text-gray-900">
										{viewingEvent.event_start || '?'} ~ {viewingEvent.event_end || '?'}
										{#if viewingEvent.days_remaining !== null}
											<span class="ml-1 {viewingEvent.days_remaining === 0 ? 'text-orange-600 font-bold' : viewingEvent.days_remaining > 0 ? 'text-blue-600' : 'text-gray-400'}">
												({getDaysRemaining(viewingEvent)})
											</span>
										{/if}
									</span>
								</div>
							{/if}
							<!-- 발표일 -->
							{#if viewingEvent.announcement_date}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">발표일:</span>
									<span class="text-gray-900">{viewingEvent.announcement_date}</span>
								</div>
							{/if}
							<!-- 구매조건 -->
							{#if viewingEvent.purchase_required}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">구매:</span>
									<span class="px-1.5 py-0.5 rounded {viewingEvent.purchase_required === 'no' ? 'bg-green-100 text-green-700' : viewingEvent.purchase_required === 'yes_all' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'}">
										{viewingEvent.purchase_required === 'no' ? '불필요' : viewingEvent.purchase_required === 'yes_all' ? '전체 필요' : '부분 필요'}
									</span>
								</div>
							{/if}
							<!-- 당첨자 -->
							{#if viewingEvent.winner_count}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">당첨자:</span>
									<span class="text-gray-900">{viewingEvent.winner_count}명</span>
								</div>
							{/if}
							<!-- 경품 -->
							{#if viewingEvent.prizes && viewingEvent.prizes.length > 0}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-12 shrink-0">경품:</span>
									<div class="flex flex-wrap gap-1">
										{#each viewingEvent.prizes as prize}
											<span class="px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded">{prize}</span>
										{/each}
									</div>
								</div>
							{/if}
							<!-- 요약 -->
							{#if viewingEvent.summary}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-12 shrink-0">요약:</span>
									<p class="text-gray-700">{viewingEvent.summary}</p>
								</div>
							{/if}
						</div>

						<!-- 링크 -->
						{#if viewingEvent.event_url}
							<div class="mt-3 pt-3 border-t border-gray-100">
								<a
									href={viewingEvent.event_url}
									target="_blank"
									rel="noopener noreferrer"
									class="flex items-center gap-2 text-sm text-blue-600 hover:underline"
								>
									<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
									</svg>
									이벤트 참여
								</a>
							</div>
						{/if}

						<!-- 북마크/참여 -->
						<div class="mt-3 pt-3 border-t border-gray-100 flex gap-2">
							<button
								onclick={(e) => { e.stopPropagation(); toggleBookmark(viewingEvent!, e); }}
								class="flex-1 py-2 text-sm rounded transition-colors {viewingEvent.is_bookmarked ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
							>
								{viewingEvent.is_bookmarked ? '★ 북마크됨' : '☆ 북마크'}
							</button>
							<button
								onclick={(e) => { e.stopPropagation(); toggleParticipate(viewingEvent!, e); }}
								class="flex-1 py-2 text-sm rounded transition-colors {isParticipated(viewingEvent) ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
							>
								{isParticipated(viewingEvent) ? '✓ 참여완료' : '참여하기'}
							</button>
						</div>

						<!-- 삭제 -->
						<button
							onclick={() => { deleteEvent(viewingEvent!.id); closeFeedViewer(); }}
							class="w-full mt-2 py-2 text-sm text-red-600 hover:bg-red-50 rounded transition-colors"
						>
							이벤트 삭제
						</button>
					</div>
				{:else}
					<!-- 원본 피드 탭 -->
					<div class="flex justify-center py-4">
						{#if loadingPost}
							<div class="bg-white rounded-xl p-8 flex items-center justify-center w-full max-w-[468px] h-[300px]">
								<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-600"></div>
							</div>
						{:else if instagramPost}
							<FeedCard
								post={instagramPost}
								detailMode={true}
								onClose={closeFeedViewer}
								onDelete={handleDeletePost}
								onRecrawl={handleRecrawl}
								onRequestLlmAnalysis={handleRequestLlmAnalysis}
								{availableTags}
								onTagsUpdate={handleTagsUpdate}
								onLlmUpdate={handleLlmUpdate}
							/>
						{:else}
							<div class="bg-white rounded-xl p-8 text-center w-full max-w-[468px]">
								<p class="text-gray-500 mb-4">Instagram 게시물을 불러올 수 없습니다.</p>
								{#if viewingEvent.source_instagram_url}
									<a
										href={viewingEvent.source_instagram_url}
										target="_blank"
										rel="noopener noreferrer"
										class="btn btn-primary btn-sm"
									>
										Instagram에서 보기
									</a>
								{/if}
							</div>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- 팝업 Instagram 피드 뷰어 모달 -->
{#if showPopupFeedViewer && viewingPopup}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/60 z-50 overflow-y-auto p-4"
		onclick={closePopupFeedViewer}
		onkeydown={(e) => e.key === 'Escape' && closePopupFeedViewer()}
		role="dialog"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div
			class="max-w-5xl w-full mx-auto my-4"
			onclick={(e) => e.stopPropagation()}
		>
			<!-- 데스크톱 레이아웃: lg 이상 -->
			<div class="hidden lg:flex gap-4">
				<!-- 왼쪽: AI 분석 (팝업 정보) -->
				<div class="bg-white rounded-xl p-4 w-80 shrink-0 max-h-[85vh] overflow-y-auto">
					<div class="flex items-center justify-between mb-3">
						<h4 class="font-semibold text-sm text-gray-900 flex items-center gap-2">
							<svg class="w-4 h-4 text-pink-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
							</svg>
							AI 분석
						</h4>
						<button
							onclick={closePopupFeedViewer}
							class="p-1 hover:bg-gray-100 rounded-full"
							aria-label="닫기"
						>
							<svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
							</svg>
						</button>
					</div>

					<div class="space-y-2 text-xs bg-gradient-to-r from-pink-50 to-purple-50 rounded-lg p-3">
						<!-- 분류 -->
						<div class="flex items-center gap-2">
							<span class="text-gray-500 w-12">분류:</span>
							<span class="px-2 py-0.5 font-medium rounded-full bg-pink-100 text-pink-700">팝업</span>
							<span class="px-2 py-0.5 rounded-full {getEventStatusColor(viewingPopup.popup_status)}">
								{eventStatusOptions.find(o => o.value === viewingPopup.popup_status)?.label}
							</span>
						</div>
						<!-- 브랜드/주최 -->
						{#if viewingPopup.brand || viewingPopup.organizer}
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">브랜드:</span>
								<span class="text-gray-900">{viewingPopup.brand || viewingPopup.organizer}</span>
							</div>
						{/if}
						<!-- 기간 -->
						{#if viewingPopup.start_date || viewingPopup.end_date}
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">기간:</span>
								<span class="text-gray-900">{viewingPopup.start_date || '?'} ~ {viewingPopup.end_date || '?'}</span>
							</div>
						{/if}
						<!-- 위치 -->
						{#if viewingPopup.venue_name || viewingPopup.address}
							<div class="flex items-start gap-2">
								<span class="text-gray-500 w-12 shrink-0">위치:</span>
								<div>
									{#if viewingPopup.venue_name}
										<span class="text-gray-900 font-medium">{viewingPopup.venue_name}</span>
									{/if}
									{#if viewingPopup.address}
										<span class="text-gray-600 block">{viewingPopup.address}</span>
									{/if}
								</div>
							</div>
						{/if}
						<!-- 요약 -->
						{#if viewingPopup.summary}
							<div class="flex items-start gap-2">
								<span class="text-gray-500 w-12 shrink-0">요약:</span>
								<p class="text-gray-700">{viewingPopup.summary}</p>
							</div>
						{/if}
					</div>

					<!-- 링크 -->
					{#if viewingPopup.official_url}
						<div class="mt-3 pt-3 border-t border-gray-100">
							<a
								href={viewingPopup.official_url}
								target="_blank"
								rel="noopener noreferrer"
								class="flex items-center gap-2 text-sm text-blue-600 hover:underline"
							>
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
								</svg>
								공식 사이트
							</a>
						</div>
					{/if}

					<!-- 북마크/방문 -->
					<div class="mt-3 pt-3 border-t border-gray-100 flex gap-2">
						<button
							onclick={(e) => { e.stopPropagation(); togglePopupBookmark(viewingPopup!, e); }}
							class="flex-1 py-2 text-xs rounded transition-colors {viewingPopup.is_bookmarked ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
						>
							{viewingPopup.is_bookmarked ? '★ 북마크됨' : '☆ 북마크'}
						</button>
						<button
							onclick={(e) => { e.stopPropagation(); togglePopupVisited(viewingPopup!, e); }}
							class="flex-1 py-2 text-xs rounded transition-colors {viewingPopup.is_visited ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
						>
							{viewingPopup.is_visited ? '✓ 방문완료' : '방문하기'}
						</button>
					</div>
				</div>

				<!-- 오른쪽: FeedCard -->
				<div class="flex-shrink-0 flex justify-center">
					{#if loadingPost}
						<div class="bg-white rounded-xl p-8 flex items-center justify-center w-[468px] h-[300px]">
							<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-pink-600"></div>
						</div>
					{:else if instagramPost}
						<FeedCard
							post={instagramPost}
							detailMode={true}
							onClose={closePopupFeedViewer}
							onDelete={handleDeletePost}
							onRecrawl={handleRecrawl}
							{availableTags}
							onTagsUpdate={handleTagsUpdate}
						/>
					{:else}
						<div class="bg-white rounded-xl p-8 text-center w-[468px]">
							<p class="text-gray-500 mb-4">Instagram 게시물을 불러올 수 없습니다.</p>
							{#if viewingPopup.source_instagram_url}
								<a
									href={viewingPopup.source_instagram_url}
									target="_blank"
									rel="noopener noreferrer"
									class="btn btn-primary btn-sm"
								>
									Instagram에서 보기
								</a>
							{/if}
						</div>
					{/if}
				</div>
			</div>

			<!-- 모바일 레이아웃: lg 미만 -->
			<div class="lg:hidden">
				<!-- 탭 헤더 -->
				<div class="flex bg-white rounded-t-xl border-b border-gray-200">
					<button
						onclick={() => mobileViewerTab = 'info'}
						class="flex-1 py-3 text-sm font-medium transition-colors {mobileViewerTab === 'info' ? 'border-b-2 border-pink-600 text-pink-600' : 'text-gray-500'}"
					>
						AI 분석
					</button>
					<button
						onclick={() => mobileViewerTab = 'feed'}
						class="flex-1 py-3 text-sm font-medium transition-colors {mobileViewerTab === 'feed' ? 'border-b-2 border-pink-600 text-pink-600' : 'text-gray-500'}"
					>
						원본 피드
					</button>
					<button
						onclick={closePopupFeedViewer}
						class="px-4 py-3 text-gray-500 hover:text-gray-700"
						aria-label="닫기"
					>
						<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				</div>

				<!-- 탭 내용 -->
				{#if mobileViewerTab === 'info'}
					<!-- AI 분석 탭 -->
					<div class="bg-white rounded-b-xl p-4">
						<div class="flex items-center justify-between mb-3">
							<h4 class="font-semibold text-sm text-gray-900 flex items-center gap-2">
								<svg class="w-4 h-4 text-pink-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
								</svg>
								AI 분석
							</h4>
						</div>

						<div class="space-y-2 text-xs bg-gradient-to-r from-pink-50 to-purple-50 rounded-lg p-3">
							<!-- 분류 -->
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">분류:</span>
								<span class="px-2 py-0.5 font-medium rounded-full bg-pink-100 text-pink-700">팝업</span>
								<span class="px-2 py-0.5 rounded-full {getEventStatusColor(viewingPopup.popup_status)}">
									{eventStatusOptions.find(o => o.value === viewingPopup.popup_status)?.label}
								</span>
							</div>
							<!-- 브랜드/주최 -->
							{#if viewingPopup.brand || viewingPopup.organizer}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">브랜드:</span>
									<span class="text-gray-900">{viewingPopup.brand || viewingPopup.organizer}</span>
								</div>
							{/if}
							<!-- 기간 -->
							{#if viewingPopup.start_date || viewingPopup.end_date}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">기간:</span>
									<span class="text-gray-900">{viewingPopup.start_date || '?'} ~ {viewingPopup.end_date || '?'}</span>
								</div>
							{/if}
							<!-- 위치 -->
							{#if viewingPopup.venue_name || viewingPopup.address}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-12 shrink-0">위치:</span>
									<div>
										{#if viewingPopup.venue_name}
											<span class="text-gray-900 font-medium">{viewingPopup.venue_name}</span>
										{/if}
										{#if viewingPopup.address}
											<span class="text-gray-600 block">{viewingPopup.address}</span>
										{/if}
									</div>
								</div>
							{/if}
							<!-- 요약 -->
							{#if viewingPopup.summary}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-12 shrink-0">요약:</span>
									<p class="text-gray-700">{viewingPopup.summary}</p>
								</div>
							{/if}
						</div>

						<!-- 링크 -->
						{#if viewingPopup.official_url}
							<div class="mt-3 pt-3 border-t border-gray-100">
								<a
									href={viewingPopup.official_url}
									target="_blank"
									rel="noopener noreferrer"
									class="flex items-center gap-2 text-sm text-blue-600 hover:underline"
								>
									<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
									</svg>
									공식 사이트
								</a>
							</div>
						{/if}

						<!-- 북마크/방문 -->
						<div class="mt-3 pt-3 border-t border-gray-100 flex gap-2">
							<button
								onclick={(e) => { e.stopPropagation(); togglePopupBookmark(viewingPopup!, e); }}
								class="flex-1 py-2 text-sm rounded transition-colors {viewingPopup.is_bookmarked ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
							>
								{viewingPopup.is_bookmarked ? '★ 북마크됨' : '☆ 북마크'}
							</button>
							<button
								onclick={(e) => { e.stopPropagation(); togglePopupVisited(viewingPopup!, e); }}
								class="flex-1 py-2 text-sm rounded transition-colors {viewingPopup.is_visited ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
							>
								{viewingPopup.is_visited ? '✓ 방문완료' : '방문하기'}
							</button>
						</div>
					</div>
				{:else}
					<!-- 원본 피드 탭 -->
					<div class="flex justify-center py-4">
						{#if loadingPost}
							<div class="bg-white rounded-xl p-8 flex items-center justify-center w-full max-w-[468px] h-[300px]">
								<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-pink-600"></div>
							</div>
						{:else if instagramPost}
							<FeedCard
								post={instagramPost}
								detailMode={true}
								onClose={closePopupFeedViewer}
								onDelete={handleDeletePost}
								onRecrawl={handleRecrawl}
								onRequestLlmAnalysis={handleRequestLlmAnalysis}
								{availableTags}
								onTagsUpdate={handleTagsUpdate}
								onLlmUpdate={handleLlmUpdate}
							/>
						{:else}
							<div class="bg-white rounded-xl p-8 text-center w-full max-w-[468px]">
								<p class="text-gray-500 mb-4">Instagram 게시물을 불러올 수 없습니다.</p>
								{#if viewingPopup.source_instagram_url}
									<a
										href={viewingPopup.source_instagram_url}
										target="_blank"
										rel="noopener noreferrer"
										class="btn btn-primary btn-sm"
									>
										Instagram에서 보기
									</a>
								{/if}
							</div>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
