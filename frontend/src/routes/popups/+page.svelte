<script lang="ts">
	import { onMount } from 'svelte';
	import { popupApi } from '$lib/api';
	import type { Popup, PopupCreate, PopupUpdate } from '$lib/types';

	let popups: Popup[] = [];
	let total = 0;
	let page = 1;
	let pageSize = 20;
	let loading = true;
	let error: string | null = null;

	// 필터
	let filterPopupStatus: string | null = 'ongoing';  // 기본: 진행 중
	let filterBookmarked: boolean | null = null;
	let filterVisited: boolean | null = null;
	let sortBy = 'end_date';
	let sortOrder = 'asc';
	let includeUnknownPeriod = false;

	// 팝업 상태 옵션
	const popupStatusOptions = [
		{ value: 'ongoing', label: '진행 중', color: 'bg-green-100 text-green-700' },
		{ value: 'upcoming', label: '예정', color: 'bg-blue-100 text-blue-700' },
		{ value: 'ended', label: '종료', color: 'bg-gray-100 text-gray-600' },
		{ value: 'cancelled', label: '취소됨', color: 'bg-red-100 text-red-600' }
	];

	// 모달 상태
	let showModal = false;
	let editingPopup: Popup | null = null;
	let popupForm: PopupCreate = {
		title: ''
	};
	let isSaving = false;

	// 팝업 목록 조회
	async function fetchPopups() {
		loading = true;
		try {
			const params: Record<string, unknown> = {
				page,
				page_size: pageSize,
				sort_by: sortBy,
				sort_order: sortOrder
			};

			if (filterPopupStatus) params.popup_status = filterPopupStatus;
			if (filterBookmarked !== null) params.is_bookmarked = filterBookmarked;
			if (filterVisited !== null) params.is_visited = filterVisited;
			if (includeUnknownPeriod) params.include_unknown_period = true;

			const response = await popupApi.list(params);
			popups = response.items;
			total = response.total;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	// 상태 필터 변경
	function setPopupStatusFilter(status: string | null) {
		filterPopupStatus = filterPopupStatus === status ? null : status;
		page = 1;
		fetchPopups();
	}

	// 기간 미정 포함 토글
	function toggleIncludeUnknownPeriod() {
		includeUnknownPeriod = !includeUnknownPeriod;
		page = 1;
		fetchPopups();
	}

	// 북마크만 보기 토글
	function toggleBookmarkedFilter() {
		filterBookmarked = filterBookmarked === true ? null : true;
		page = 1;
		fetchPopups();
	}

	// 방문완료만 보기 토글
	function toggleVisitedFilter() {
		filterVisited = filterVisited === true ? null : true;
		page = 1;
		fetchPopups();
	}

	// 페이지 이동
	function prevPage() {
		if (page > 1) {
			page--;
			fetchPopups();
		}
	}

	function nextPage() {
		if (page * pageSize < total) {
			page++;
			fetchPopups();
		}
	}

	// 새 팝업 생성 모달 열기
	function openCreateModal() {
		editingPopup = null;
		popupForm = {
			title: '',
			venue_name: '',
			address: '',
			start_date: '',
			end_date: '',
			organizer: '',
			brand: '',
			summary: '',
			operating_hours: '',
			official_url: ''
		};
		showModal = true;
	}

	// 수정 모달 열기
	function openEditModal(popup: Popup) {
		editingPopup = popup;
		popupForm = {
			title: popup.title,
			venue_name: popup.venue_name || '',
			address: popup.address || '',
			start_date: popup.start_date || '',
			end_date: popup.end_date || '',
			organizer: popup.organizer || '',
			brand: popup.brand || '',
			summary: popup.summary || '',
			operating_hours: popup.operating_hours || '',
			closed_days: popup.closed_days || '',
			official_url: popup.official_url || '',
			user_note: popup.user_note || ''
		};
		showModal = true;
	}

	// 모달 닫기
	function closeModal() {
		showModal = false;
		editingPopup = null;
	}

	// 팝업 저장
	async function savePopup() {
		if (!popupForm.title.trim()) {
			alert('제목을 입력해주세요.');
			return;
		}
		isSaving = true;
		try {
			if (editingPopup) {
				const updateData: PopupUpdate = { ...popupForm };
				await popupApi.update(editingPopup.id, updateData);
			} else {
				await popupApi.create(popupForm);
			}
			closeModal();
			await fetchPopups();
		} catch (e) {
			alert('저장 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		} finally {
			isSaving = false;
		}
	}

	// 팝업 삭제
	async function deletePopup(id: number) {
		if (!confirm('이 팝업을 삭제하시겠습니까?')) return;
		try {
			await popupApi.delete(id);
			await fetchPopups();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	// 북마크 토글
	async function toggleBookmark(popup: Popup, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await popupApi.toggleBookmark(popup.id);
			popup.is_bookmarked = result.is_bookmarked;
			popups = [...popups];
		} catch (err) {
			console.error('북마크 토글 실패:', err);
		}
	}

	// 방문 완료 토글
	async function toggleVisited(popup: Popup, e: MouseEvent) {
		e.stopPropagation();
		try {
			const result = await popupApi.toggleVisited(popup.id);
			popup.is_visited = result.is_visited;
			popups = [...popups];
		} catch (err) {
			console.error('방문 완료 토글 실패:', err);
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
	function isEndingToday(popup: Popup): boolean {
		if (!popup.end_date) return false;
		const today = new Date().toISOString().split('T')[0];
		return popup.end_date === today;
	}

	// 기간 미정 여부
	function isUnknownPeriod(popup: Popup): boolean {
		return !popup.end_date;
	}

	// D-Day 계산
	function getDaysRemaining(popup: Popup): string {
		if (popup.days_remaining === null || popup.days_remaining === undefined) return '';
		if (popup.days_remaining === 0) return 'D-Day';
		if (popup.days_remaining > 0) return `D-${popup.days_remaining}`;
		return `D+${Math.abs(popup.days_remaining)}`;
	}

	// 팝업 상태 배지 색상
	function getPopupStatusColor(status: string): string {
		switch (status) {
			case 'ongoing': return 'bg-green-100 text-green-700';
			case 'upcoming': return 'bg-blue-100 text-blue-700';
			case 'ended': return 'bg-gray-100 text-gray-600';
			case 'cancelled': return 'bg-red-100 text-red-600';
			default: return 'bg-gray-100 text-gray-600';
		}
	}

	// 텍스트 자르기
	function truncate(text: string | null, maxLength: number): string {
		if (!text) return '';
		if (text.length <= maxLength) return text;
		return text.slice(0, maxLength) + '...';
	}

	onMount(() => {
		fetchPopups();
	});
</script>

<div class="p-4 md:p-6">
	<!-- 헤더 -->
	<div class="mb-4 md:mb-6 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
		<div class="flex items-center justify-between sm:justify-start gap-3">
			<h2 class="text-xl md:text-2xl font-bold text-gray-900">팝업스토어</h2>
			<button
				onclick={openCreateModal}
				class="btn btn-primary btn-sm"
			>
				+ 새 팝업
			</button>
		</div>

		<!-- 필터 요약 -->
		<div class="flex items-center gap-2 text-sm text-gray-600">
			<span>총 {total}건</span>
			{#if filterBookmarked}
				<span class="text-yellow-600">(북마크만)</span>
			{/if}
			{#if filterVisited}
				<span class="text-green-600">(방문완료만)</span>
			{/if}
			{#if includeUnknownPeriod}
				<span class="text-amber-600">(기간미정 포함)</span>
			{/if}
		</div>
	</div>

	<!-- 필터 영역 -->
	<div class="mb-4 flex flex-wrap gap-2 items-center">
		<!-- 팝업 상태 필터 -->
		<span class="text-sm text-gray-500">상태:</span>
		{#each popupStatusOptions as opt}
			<button
				onclick={() => setPopupStatusFilter(opt.value)}
				class="px-3 py-1 text-sm rounded-full transition-colors {filterPopupStatus === opt.value ? opt.color + ' ring-2 ring-offset-1 ring-gray-400' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
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

		<!-- 방문완료만 -->
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={filterVisited === true}
				onchange={toggleVisitedFilter}
				class="w-4 h-4 text-green-600 rounded border-gray-300 focus:ring-green-500"
			/>
			<span class="text-sm text-gray-600">방문완료만</span>
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
	{:else if popups.length === 0}
		<div class="text-center py-12 text-gray-500">
			<p class="text-lg">등록된 팝업이 없습니다</p>
			<p class="text-sm mt-2">새 팝업을 등록하면 여기에 표시됩니다</p>
			<button onclick={openCreateModal} class="mt-4 btn btn-primary btn-sm">
				+ 새 팝업 등록
			</button>
		</div>
	{:else}
		<!-- 팝업 테이블 -->
		<div class="bg-white rounded-lg border border-gray-200 overflow-hidden mb-6">
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">상태</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[200px]">제목</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap max-w-[150px]">장소</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">기간</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">D-Day</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">브랜드</th>
							<th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">출처</th>
							<th class="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">북마크</th>
							<th class="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">방문</th>
							<th class="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase whitespace-nowrap">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each popups as popup (popup.id)}
							<tr
								class="cursor-pointer transition-colors {isEndingToday(popup) ? 'bg-orange-100 hover:bg-orange-200 font-semibold' : isUnknownPeriod(popup) ? 'bg-amber-50 hover:bg-amber-100' : 'hover:bg-gray-50'}"
								onclick={() => openEditModal(popup)}
							>
								<!-- 상태 -->
								<td class="px-3 py-3">
									<span class="px-2 py-1 text-xs rounded-full {getPopupStatusColor(popup.popup_status)}">
										{popupStatusOptions.find(o => o.value === popup.popup_status)?.label || popup.popup_status}
									</span>
								</td>
								<!-- 제목 -->
								<td class="px-3 py-3 max-w-[200px]">
									<span class="block truncate text-sm font-medium text-gray-900" title={popup.title}>
										{popup.title}
									</span>
									{#if popup.summary}
										<span class="block truncate text-xs text-gray-500" title={popup.summary}>
											{truncate(popup.summary, 30)}
										</span>
									{/if}
								</td>
								<!-- 장소 -->
								<td class="px-3 py-3 max-w-[150px]">
									<span class="block truncate text-sm text-gray-600" title={popup.venue_name || ''}>
										{popup.venue_name || '-'}
									</span>
									{#if popup.address}
										<span class="block truncate text-xs text-gray-400" title={popup.address}>
											{truncate(popup.address, 20)}
										</span>
									{/if}
								</td>
								<!-- 기간 -->
								<td class="px-3 py-3 text-sm text-gray-600 whitespace-nowrap">
									{#if popup.end_date}
										<div class="flex flex-col gap-0.5">
											{#if popup.start_date}
												<span class="text-xs text-gray-500">{formatDate(popup.start_date)}</span>
											{/if}
											{#if isEndingToday(popup)}
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
								<!-- D-Day -->
								<td class="px-3 py-3 text-center">
									{#if popup.days_remaining !== null && popup.days_remaining !== undefined}
										<span class="text-sm font-medium {popup.days_remaining === 0 ? 'text-orange-600' : popup.days_remaining > 0 ? 'text-blue-600' : 'text-gray-400'}">
											{getDaysRemaining(popup)}
										</span>
									{:else}
										<span class="text-gray-400">-</span>
									{/if}
								</td>
								<!-- 브랜드 -->
								<td class="px-3 py-3 text-sm text-gray-600 max-w-[100px]">
									<span class="truncate block" title={popup.brand || popup.organizer || ''}>
										{popup.brand || popup.organizer || '-'}
									</span>
								</td>
								<!-- 출처 -->
								<td class="px-3 py-3 text-sm text-gray-600">
									<span class="px-2 py-0.5 text-xs rounded {popup.source_type === 'instagram' ? 'bg-pink-100 text-pink-600' : 'bg-gray-100 text-gray-600'}">
										{popup.source_type === 'instagram' ? 'IG' : popup.source_type === 'manual' ? '수동' : popup.source_type}
									</span>
								</td>
								<!-- 북마크 -->
								<td class="px-3 py-3 text-center" onclick={(e) => e.stopPropagation()}>
									<button
										onclick={(e) => toggleBookmark(popup, e)}
										class="text-xl transition-colors {popup.is_bookmarked ? 'text-yellow-500' : 'text-gray-300 hover:text-yellow-400'}"
										title={popup.is_bookmarked ? '북마크 해제' : '북마크'}
									>
										{popup.is_bookmarked ? '★' : '☆'}
									</button>
								</td>
								<!-- 방문 완료 -->
								<td class="px-3 py-3 text-center" onclick={(e) => e.stopPropagation()}>
									<button
										onclick={(e) => toggleVisited(popup, e)}
										class="px-2 py-1 text-xs rounded transition-colors {popup.is_visited ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}"
										title={popup.is_visited ? '방문 취소' : '방문 완료'}
									>
										{popup.is_visited ? '방문함' : '미방문'}
									</button>
								</td>
								<!-- 액션 -->
								<td class="px-3 py-3 text-center" onclick={(e) => e.stopPropagation()}>
									<div class="flex gap-2 justify-center">
										{#if popup.official_url}
											<a
												href={popup.official_url}
												target="_blank"
												rel="noopener noreferrer"
												class="text-blue-600 hover:text-blue-800 text-sm"
												title="URL 열기"
											>
												링크
											</a>
										{/if}
										<button
											onclick={() => deletePopup(popup.id)}
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

<!-- 팝업 생성/수정 모달 -->
{#if showModal}
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
						{editingPopup ? '팝업 수정' : '새 팝업'}
					</h3>
					<button onclick={closeModal} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<div class="space-y-4">
					<!-- 제목 -->
					<div>
						<label for="popup-title" class="block text-sm font-medium text-gray-700 mb-1">
							제목 <span class="text-red-500">*</span>
						</label>
						<input
							id="popup-title"
							type="text"
							bind:value={popupForm.title}
							placeholder="팝업 제목"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						/>
					</div>

					<!-- 장소명 + 주소 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="popup-venue" class="block text-sm font-medium text-gray-700 mb-1">장소명</label>
							<input
								id="popup-venue"
								type="text"
								bind:value={popupForm.venue_name}
								placeholder="예: 더현대 서울"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="popup-address" class="block text-sm font-medium text-gray-700 mb-1">주소</label>
							<input
								id="popup-address"
								type="text"
								bind:value={popupForm.address}
								placeholder="예: 서울시 영등포구..."
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
					</div>

					<!-- 기간 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="popup-start" class="block text-sm font-medium text-gray-700 mb-1">시작일</label>
							<input
								id="popup-start"
								type="date"
								bind:value={popupForm.start_date}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="popup-end" class="block text-sm font-medium text-gray-700 mb-1">종료일</label>
							<input
								id="popup-end"
								type="date"
								bind:value={popupForm.end_date}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
					</div>

					<!-- 운영시간 + 휴무일 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="popup-hours" class="block text-sm font-medium text-gray-700 mb-1">운영시간</label>
							<input
								id="popup-hours"
								type="text"
								bind:value={popupForm.operating_hours}
								placeholder="예: 10:30 - 20:00"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="popup-closed" class="block text-sm font-medium text-gray-700 mb-1">휴무일</label>
							<input
								id="popup-closed"
								type="text"
								bind:value={popupForm.closed_days}
								placeholder="예: 매주 월요일"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
					</div>

					<!-- 브랜드 + 주최 -->
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label for="popup-brand" class="block text-sm font-medium text-gray-700 mb-1">브랜드</label>
							<input
								id="popup-brand"
								type="text"
								bind:value={popupForm.brand}
								placeholder="브랜드명"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
						<div>
							<label for="popup-organizer" class="block text-sm font-medium text-gray-700 mb-1">주최</label>
							<input
								id="popup-organizer"
								type="text"
								bind:value={popupForm.organizer}
								placeholder="주최자"
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							/>
						</div>
					</div>

					<!-- URL -->
					<div>
						<label for="popup-url" class="block text-sm font-medium text-gray-700 mb-1">관련 URL</label>
						<input
							id="popup-url"
							type="text"
							bind:value={popupForm.official_url}
							placeholder="https://..."
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						/>
					</div>

					<!-- 요약 -->
					<div>
						<label for="popup-summary" class="block text-sm font-medium text-gray-700 mb-1">요약</label>
						<textarea
							id="popup-summary"
							bind:value={popupForm.summary}
							placeholder="팝업 설명..."
							rows="3"
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						></textarea>
					</div>

					<!-- 메모 -->
					<div>
						<label for="popup-note" class="block text-sm font-medium text-gray-700 mb-1">메모</label>
						<textarea
							id="popup-note"
							bind:value={popupForm.user_note}
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
						onclick={savePopup}
						disabled={isSaving}
						class="btn btn-primary btn-sm disabled:opacity-50"
					>
						{#if isSaving}
							저장 중...
						{:else}
							{editingPopup ? '수정' : '등록'}
						{/if}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
