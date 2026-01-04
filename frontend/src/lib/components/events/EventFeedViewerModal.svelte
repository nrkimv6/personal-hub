<script lang="ts">
	/**
	 * 이벤트/팝업 피드 뷰어 모달 컴포넌트
	 *
	 * Instagram 출처 이벤트/팝업의 상세 보기
	 * - 데스크톱: AI 분석 패널 + FeedCard 나란히
	 * - 모바일: 탭 전환 (AI 분석 / 원본 피드)
	 */
	import type { Event, Popup, InstagramPost, InstagramTag } from '$lib/types';
	import FeedCard from '$lib/components/instagram/FeedCard.svelte';
	import SourcesList from '$lib/components/events/SourcesList.svelte';
	import { getEventStatusColor, getEventStatusLabel, getDaysRemaining } from '$lib/utils/eventUtils';
	
	type ViewerType = 'event' | 'popup';
	type MobileViewerTab = 'info' | 'feed';

	interface Props {
		show: boolean;
		type: ViewerType;
		event?: Event | null;
		popup?: Popup | null;
		instagramPost: InstagramPost | null;
		loadingPost: boolean;
		availableTags: InstagramTag[];
		isAdmin?: boolean;
		onClose: () => void;
		onEdit?: () => void;  // 관리자 전용
		onDelete?: () => void;  // 관리자 전용
		onBookmarkToggle: (e: MouseEvent) => void;
		onParticipateToggle?: (e: MouseEvent) => void; // 이벤트용
		onVisitToggle?: (e: MouseEvent) => void; // 팝업용
		onOfflineToggle?: (e: MouseEvent) => void; // 이벤트 온라인/오프라인 토글
		onRecrawl?: (postId: number) => Promise<void>;  // 관리자 전용
		onTagsUpdate?: (postId: number, tagIds: number[]) => Promise<void>;  // 관리자 전용
		onDeletePost?: (postId: number) => Promise<void>;  // 관리자 전용
		onRequestLlmAnalysis?: (postId: number) => Promise<void>;  // 관리자 전용
		isParticipated?: boolean;
	}

	let {
		show,
		type,
		event = null,
		popup = null,
		instagramPost,
		loadingPost,
		availableTags,
		isAdmin = false,
		onClose,
		onEdit,
		onDelete,
		onBookmarkToggle,
		onParticipateToggle,
		onVisitToggle,
		onOfflineToggle,
		onRecrawl,
		onTagsUpdate,
		onDeletePost,
		onRequestLlmAnalysis,
		isParticipated = false
	}: Props = $props();

	let copied = $state(false);

	async function copyEventUrl() {
		const url = type === 'event' ? event?.event_url : popup?.official_url;
		if (!url) return;

		try {
			await navigator.clipboard.writeText(url);
			copied = true;
			setTimeout(() => {
				copied = false;
			}, 2000);
		} catch (err) {
			console.error('Failed to copy URL:', err);
		}
	}

	let mobileViewerTab: MobileViewerTab = $state('info');

	// show가 변경될 때 탭 초기화
	$effect(() => {
		if (show) {
			mobileViewerTab = 'info';
		}
	});

	// 현재 아이템 (이벤트 또는 팝업)
	const item = $derived(type === 'event' ? event : popup);
	const themeColor = $derived(type === 'event' ? 'purple' : 'pink');

	// 이벤트/팝업 필드 접근 헬퍼
	function getOrganizer(): string | null {
		if (type === 'event' && event) return event.organizer;
		if (type === 'popup' && popup) return popup.brand || popup.organizer;
		return null;
	}

	function getStatus(): string {
		if (type === 'event' && event) return event.event_status;
		if (type === 'popup' && popup) return popup.popup_status;
		return 'unknown';
	}

	function getPeriod(): { start: string | null; end: string | null } {
		if (type === 'event' && event)
			return { start: event.event_start, end: event.event_end };
		if (type === 'popup' && popup)
			return { start: popup.start_date, end: popup.end_date };
		return { start: null, end: null };
	}

	function getInstagramUrl(): string | null {
		if (type === 'event' && event) return event.source_instagram_url;
		if (type === 'popup' && popup) return popup.source_instagram_url;
		return null;
	}

	function getBookmarked(): boolean {
		if (type === 'event' && event) return event.is_bookmarked;
		if (type === 'popup' && popup) return popup.is_bookmarked;
		return false;
	}

	function getVisited(): boolean {
		if (type === 'popup' && popup) return popup.is_visited;
		return false;
	}

	function getInputSource(): 'ai' | 'human' | 'ai_edited' {
		if (type === 'event' && event) return event.input_source || 'human';
		if (type === 'popup' && popup) return popup.input_source || 'human';
		return 'human';
	}

	function getInputSourceLabel(): string {
		const source = getInputSource();
		if (source === 'ai') return 'AI';
		if (source === 'ai_edited') return 'AI+수정';
		return '수동';
	}

	function getInputSourceColor(): string {
		const source = getInputSource();
		if (source === 'ai') return 'bg-purple-100 text-purple-700';
		if (source === 'ai_edited') return 'bg-blue-100 text-blue-700';
		return 'bg-gray-100 text-gray-600';
	}

	// 이벤트 URL 목록 (event_url + additional_urls)
	function getEventUrls(): string[] {
		if (type === 'event' && event) {
			const urls: string[] = [];
			if (event.event_url) urls.push(event.event_url);
			if (event.additional_urls?.length) urls.push(...event.additional_urls);
			return urls;
		}
		if (type === 'popup' && popup?.official_url) {
			return [popup.official_url];
		}
		return [];
	}
</script>

{#if show && item}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/60 z-50 overflow-y-auto p-4"
		onclick={onClose}
		onkeydown={(e) => e.key === 'Escape' && onClose()}
		role="dialog"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div class="max-w-5xl w-full mx-auto my-4" onclick={(e) => e.stopPropagation()}>
			<!-- 데스크톱 레이아웃: lg 이상 -->
			<div class="hidden lg:flex gap-4">
				<!-- 왼쪽: AI 분석 패널 -->
				<div class="bg-white rounded-xl p-4 w-80 shrink-0 max-h-[85vh] overflow-y-auto">
					<div class="flex items-center justify-between mb-3">
						<h4 class="font-semibold text-sm text-gray-900 flex items-center gap-2">
							<svg
								class="w-4 h-4 text-{themeColor}-600"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
								/>
							</svg>
							AI 분석
						</h4>
						<div class="flex items-center gap-2">
							{#if getInstagramUrl()}
								<a
									href={getInstagramUrl()}
									target="_blank"
									rel="noopener noreferrer"
									class="text-xs text-pink-600 hover:text-pink-800 underline"
								>
									원본 링크
								</a>
							{/if}
							{#if type === 'event' && onEdit}
								<button
									onclick={onEdit}
									class="text-xs text-{themeColor}-600 hover:text-{themeColor}-800 underline"
								>
									수정
								</button>
							{/if}
							<button onclick={onClose} class="p-1 hover:bg-gray-100 rounded-full" aria-label="닫기">
								<svg
									class="w-4 h-4 text-gray-500"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M6 18L18 6M6 6l12 12"
									/>
								</svg>
							</button>
						</div>
					</div>

					<div
						class="space-y-2 text-xs bg-gradient-to-r from-{themeColor}-50 to-blue-50 rounded-lg p-3"
					>
						<!-- 분류 -->
						<div class="flex items-center gap-2">
							<span class="text-gray-500 w-12">분류:</span>
							<span class="px-2 py-0.5 font-medium rounded-full bg-{themeColor}-100 text-{themeColor}-700">
								{type === 'popup' ? '팝업' : '이벤트'}
							</span>
							<span class="px-2 py-0.5 rounded-full {getEventStatusColor(getStatus())}">
								{getEventStatusLabel(getStatus())}
							</span>
							<span class="px-2 py-0.5 rounded-full {getInputSourceColor()}">
								{getInputSourceLabel()}
							</span>
						</div>
						<!-- 주최/브랜드 -->
						{#if getOrganizer()}
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">{type === 'popup' ? '브랜드:' : '주최:'}</span>
								<span class="text-gray-900">{getOrganizer()}</span>
							</div>
						{/if}
						<!-- 기간 -->
						{#if getPeriod().start || getPeriod().end}
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">기간:</span>
								<span class="text-gray-900">
									{getPeriod().start || '?'} ~ {getPeriod().end || '?'}
									{#if type === 'event' && event?.days_remaining !== null && event?.days_remaining !== undefined}
										<span
											class="ml-1 {event.days_remaining === 0
												? 'text-orange-600 font-bold'
												: event.days_remaining > 0
													? 'text-blue-600'
													: 'text-gray-400'}"
										>
											({getDaysRemaining(event)})
										</span>
									{/if}
								</span>
							</div>
						{/if}

						<!-- 이벤트 전용 필드 -->
						{#if type === 'event' && event}
							<!-- 발표일 -->
							{#if event.announcement_date}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">발표일:</span>
									<span class="text-gray-900">{event.announcement_date}</span>
								</div>
							{/if}
							<!-- 구매조건 -->
							{#if event.purchase_required}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">구매:</span>
									<span
										class="px-1.5 py-0.5 rounded {event.purchase_required === 'no'
											? 'bg-green-100 text-green-700'
											: event.purchase_required === 'yes_all'
												? 'bg-red-100 text-red-700'
												: 'bg-yellow-100 text-yellow-700'}"
									>
										{event.purchase_required === 'no'
											? '불필요'
											: event.purchase_required === 'yes_all'
												? '전체 필요'
												: '부분 필요'}
									</span>
								</div>
							{/if}
							<!-- 당첨자 -->
							{#if event.winner_count}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">당첨자:</span>
									<span class="text-gray-900">{event.winner_count}명</span>
								</div>
							{/if}
							<!-- 경품 -->
							{#if event.prizes && event.prizes.length > 0}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-12 shrink-0">경품:</span>
									<div class="flex flex-wrap gap-1">
										{#each event.prizes as prize}
											<span class="px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded">{prize}</span>
										{/each}
									</div>
								</div>
							{/if}
						{/if}

						<!-- 팝업 전용 필드: 위치 -->
						{#if type === 'popup' && popup && (popup.venue_name || popup.address)}
							<div class="flex items-start gap-2">
								<span class="text-gray-500 w-12 shrink-0">위치:</span>
								<div>
									{#if popup.venue_name}
										<span class="text-gray-900 font-medium">{popup.venue_name}</span>
									{/if}
									{#if popup.address}
										<span class="text-gray-600 block">{popup.address}</span>
									{/if}
								</div>
							</div>
						{/if}

						<!-- 요약 -->
						{#if (type === 'event' && event?.summary) || (type === 'popup' && popup?.summary)}
							<div class="flex items-start gap-2">
								<span class="text-gray-500 w-12 shrink-0">요약:</span>
								<p class="text-gray-700">
									{type === 'event' ? event?.summary : popup?.summary}
								</p>
							</div>
						{/if}
					</div>

					<!-- 링크 -->
					{@const eventUrls = getEventUrls()}
					{#if eventUrls.length > 0}
						<div class="mt-3 pt-3 border-t border-gray-100">
							<div class="space-y-1.5">
								{#each eventUrls as url, index}
									<div class="flex items-center gap-2">
										<a
											href={url}
											target="_blank"
											rel="noopener noreferrer"
											class="flex items-center gap-1.5 text-sm text-blue-600 hover:underline truncate flex-1"
											title={url}
										>
											<svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
												/>
											</svg>
											<span class="truncate">{index === 0 ? (type === 'event' ? '이벤트 참여' : '공식 사이트') : `링크 ${index + 1}`}</span>
										</a>
										{#if index === 0}
											<span class="text-[10px] text-blue-600 px-1.5 py-0.5 bg-blue-50 rounded shrink-0">메인</span>
										{/if}
									</div>
								{/each}
							</div>
							{#if isAdmin}
								<button
									onclick={copyEventUrl}
									class="mt-2 flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors {copied
										? 'bg-green-100 text-green-700'
										: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
									title={copied ? '복사됨!' : '메인 링크 복사'}
								>
									{#if copied}
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
										</svg>
										복사됨
									{:else}
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
										</svg>
										메인 복사
									{/if}
								</button>
							{/if}
						</div>
					{/if}

					<!-- 북마크/참여 또는 방문 -->
					<div class="mt-3 pt-3 border-t border-gray-100 flex gap-2">
						<button
							onclick={onBookmarkToggle}
							class="flex-1 py-2 text-xs rounded transition-colors {getBookmarked()
								? 'bg-yellow-100 text-yellow-700'
								: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
						>
							{getBookmarked() ? '★ 북마크됨' : '☆ 북마크'}
						</button>
						{#if type === 'event' && onParticipateToggle}
							<button
								onclick={onParticipateToggle}
								class="flex-1 py-2 text-xs rounded transition-colors {isParticipated
									? 'bg-green-100 text-green-700'
									: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
							>
								{isParticipated ? '✓ 참여완료' : '참여체크'}
							</button>
						{:else if type === 'popup' && onVisitToggle}
							<button
								onclick={onVisitToggle}
								class="flex-1 py-2 text-xs rounded transition-colors {getVisited()
									? 'bg-green-100 text-green-700'
									: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
							>
								{getVisited() ? '✓ 방문완료' : '방문하기'}
							</button>
						{/if}
					</div>

					<!-- 오프라인 토글 (이벤트, 관리자 전용) -->
					{#if type === 'event' && isAdmin && onOfflineToggle && event}
						<button
							onclick={onOfflineToggle}
							class="w-full mt-2 py-2 text-xs rounded transition-colors {event.is_offline
								? 'bg-green-100 text-green-700 hover:bg-green-200'
								: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
						>
							{event.is_offline ? '📍 오프라인 이벤트' : '🌐 온라인 이벤트'} (클릭하여 변경)
						</button>
					{/if}

					<!-- 출처 목록 -->
					{#if item?.id}
						<div class="mt-3 pt-3 border-t border-gray-100">
							<SourcesList
								entityType={type === 'event' ? 'events' : 'popups'}
								entityId={item.id}
								{isAdmin}
							/>
						</div>
					{/if}

					<!-- 삭제 (이벤트만) -->
					{#if type === 'event' && onDelete}
						<button
							onclick={onDelete}
							class="w-full mt-2 py-2 text-xs text-red-600 hover:bg-red-50 rounded transition-colors"
						>
							이벤트 삭제
						</button>
					{/if}
				</div>

				<!-- 오른쪽: FeedCard -->
				<div class="flex-shrink-0 flex justify-center">
					{#if loadingPost}
						<div
							class="bg-white rounded-xl p-8 flex items-center justify-center w-[468px] h-[300px]"
						>
							<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-{themeColor}-600"
							></div>
						</div>
					{:else if instagramPost}
						<FeedCard
							post={instagramPost}
							detailMode={true}
							{onClose}
							onDelete={onDeletePost}
							{onRecrawl}
							{onRequestLlmAnalysis}
							{availableTags}
							onTagsUpdate={onTagsUpdate}
						/>
					{:else}
						<div class="bg-white rounded-xl p-8 text-center w-[468px]">
							<p class="text-gray-500 mb-4">Instagram 게시물을 불러올 수 없습니다.</p>
							{#if getInstagramUrl()}
								<a
									href={getInstagramUrl()}
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
						onclick={() => (mobileViewerTab = 'info')}
						class="flex-1 py-3 text-sm font-medium transition-colors {mobileViewerTab === 'info'
							? `border-b-2 border-${themeColor}-600 text-${themeColor}-600`
							: 'text-gray-500'}"
					>
						AI 분석
					</button>
					<button
						onclick={() => (mobileViewerTab = 'feed')}
						class="flex-1 py-3 text-sm font-medium transition-colors {mobileViewerTab === 'feed'
							? `border-b-2 border-${themeColor}-600 text-${themeColor}-600`
							: 'text-gray-500'}"
					>
						원본 피드
					</button>
					<button
						onclick={onClose}
						class="px-4 py-3 text-gray-500 hover:text-gray-700"
						aria-label="닫기"
					>
						<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M6 18L18 6M6 6l12 12"
							/>
						</svg>
					</button>
				</div>

				<!-- 탭 내용 -->
				{#if mobileViewerTab === 'info'}
					<!-- AI 분석 탭 -->
					<div class="bg-white rounded-b-xl p-4 max-h-[70vh] overflow-y-auto">
						<div class="flex items-center justify-between mb-3">
							<h4 class="font-semibold text-sm text-gray-900 flex items-center gap-2">
								<svg
									class="w-4 h-4 text-{themeColor}-600"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
									/>
								</svg>
								AI 분석
							</h4>
							<div class="flex items-center gap-2">
							{#if getInstagramUrl()}
								<a
									href={getInstagramUrl()}
									target="_blank"
									rel="noopener noreferrer"
									class="text-xs text-pink-600 hover:text-pink-800 underline"
								>
									원본 링크
								</a>
							{/if}
							{#if type === 'event' && onEdit}
								<button
									onclick={onEdit}
									class="text-xs text-{themeColor}-600 hover:text-{themeColor}-800 underline"
								>
									수정
								</button>
							{/if}
						</div>
						</div>

						<div
							class="space-y-2 text-xs bg-gradient-to-r from-{themeColor}-50 to-blue-50 rounded-lg p-3"
						>
							<!-- 분류 -->
							<div class="flex items-center gap-2">
								<span class="text-gray-500 w-12">분류:</span>
								<span class="px-2 py-0.5 font-medium rounded-full bg-{themeColor}-100 text-{themeColor}-700">
									{type === 'popup' ? '팝업' : '이벤트'}
								</span>
								<span class="px-2 py-0.5 rounded-full {getEventStatusColor(getStatus())}">
									{getEventStatusLabel(getStatus())}
								</span>
								<span class="px-2 py-0.5 rounded-full {getInputSourceColor()}">
									{getInputSourceLabel()}
								</span>
							</div>
							<!-- 주최/브랜드 -->
							{#if getOrganizer()}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">{type === 'popup' ? '브랜드:' : '주최:'}</span>
									<span class="text-gray-900">{getOrganizer()}</span>
								</div>
							{/if}
							<!-- 기간 -->
							{#if getPeriod().start || getPeriod().end}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-12">기간:</span>
									<span class="text-gray-900">
										{getPeriod().start || '?'} ~ {getPeriod().end || '?'}
										{#if type === 'event' && event?.days_remaining !== null && event?.days_remaining !== undefined}
											<span
												class="ml-1 {event.days_remaining === 0
													? 'text-orange-600 font-bold'
													: event.days_remaining > 0
														? 'text-blue-600'
														: 'text-gray-400'}"
											>
												({getDaysRemaining(event)})
											</span>
										{/if}
									</span>
								</div>
							{/if}

							<!-- 이벤트 전용 필드 -->
							{#if type === 'event' && event}
								{#if event.announcement_date}
									<div class="flex items-center gap-2">
										<span class="text-gray-500 w-12">발표일:</span>
										<span class="text-gray-900">{event.announcement_date}</span>
									</div>
								{/if}
								{#if event.purchase_required}
									<div class="flex items-center gap-2">
										<span class="text-gray-500 w-12">구매:</span>
										<span
											class="px-1.5 py-0.5 rounded {event.purchase_required === 'no'
												? 'bg-green-100 text-green-700'
												: event.purchase_required === 'yes_all'
													? 'bg-red-100 text-red-700'
													: 'bg-yellow-100 text-yellow-700'}"
										>
											{event.purchase_required === 'no'
												? '불필요'
												: event.purchase_required === 'yes_all'
													? '전체 필요'
													: '부분 필요'}
										</span>
									</div>
								{/if}
								{#if event.winner_count}
									<div class="flex items-center gap-2">
										<span class="text-gray-500 w-12">당첨자:</span>
										<span class="text-gray-900">{event.winner_count}명</span>
									</div>
								{/if}
								{#if event.prizes && event.prizes.length > 0}
									<div class="flex items-start gap-2">
										<span class="text-gray-500 w-12 shrink-0">경품:</span>
										<div class="flex flex-wrap gap-1">
											{#each event.prizes as prize}
												<span class="px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded"
													>{prize}</span
												>
											{/each}
										</div>
									</div>
								{/if}
							{/if}

							<!-- 팝업 전용 필드: 위치 -->
							{#if type === 'popup' && popup && (popup.venue_name || popup.address)}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-12 shrink-0">위치:</span>
									<div>
										{#if popup.venue_name}
											<span class="text-gray-900 font-medium">{popup.venue_name}</span>
										{/if}
										{#if popup.address}
											<span class="text-gray-600 block">{popup.address}</span>
										{/if}
									</div>
								</div>
							{/if}

							<!-- 요약 -->
							{#if (type === 'event' && event?.summary) || (type === 'popup' && popup?.summary)}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-12 shrink-0">요약:</span>
									<p class="text-gray-700">
										{type === 'event' ? event?.summary : popup?.summary}
									</p>
								</div>
							{/if}
						</div>

						<!-- 링크 -->
						{@const mobileEventUrls = getEventUrls()}
						{#if mobileEventUrls.length > 0}
							<div class="mt-3 pt-3 border-t border-gray-100">
								<div class="space-y-1.5">
									{#each mobileEventUrls as url, index}
										<div class="flex items-center gap-2">
											<a
												href={url}
												target="_blank"
												rel="noopener noreferrer"
												class="flex items-center gap-1.5 text-sm text-blue-600 hover:underline truncate flex-1"
												title={url}
											>
												<svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														stroke-width="2"
														d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
													/>
												</svg>
												<span class="truncate">{index === 0 ? (type === 'event' ? '이벤트 참여' : '공식 사이트') : `링크 ${index + 1}`}</span>
											</a>
											{#if index === 0}
												<span class="text-[10px] text-blue-600 px-1.5 py-0.5 bg-blue-50 rounded shrink-0">메인</span>
											{/if}
										</div>
									{/each}
								</div>
								{#if isAdmin}
									<button
										onclick={copyEventUrl}
										class="mt-2 flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors {copied
											? 'bg-green-100 text-green-700'
											: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
										title={copied ? '복사됨!' : '메인 링크 복사'}
									>
										{#if copied}
											<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
											</svg>
											복사됨
										{:else}
											<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
											</svg>
											메인 복사
										{/if}
									</button>
								{/if}
							</div>
						{/if}

						<!-- 북마크/참여 또는 방문 -->
						<div class="mt-3 pt-3 border-t border-gray-100 flex gap-2">
							<button
								onclick={onBookmarkToggle}
								class="flex-1 py-2 text-sm rounded transition-colors {getBookmarked()
									? 'bg-yellow-100 text-yellow-700'
									: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
							>
								{getBookmarked() ? '★ 북마크됨' : '☆ 북마크'}
							</button>
							{#if type === 'event' && onParticipateToggle}
								<button
									onclick={onParticipateToggle}
									class="flex-1 py-2 text-sm rounded transition-colors {isParticipated
										? 'bg-green-100 text-green-700'
										: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
								>
									{isParticipated ? '✓ 참여완료' : '참여체크'}
								</button>
							{:else if type === 'popup' && onVisitToggle}
								<button
									onclick={onVisitToggle}
									class="flex-1 py-2 text-sm rounded transition-colors {getVisited()
										? 'bg-green-100 text-green-700'
										: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
								>
									{getVisited() ? '✓ 방문완료' : '방문하기'}
								</button>
							{/if}
						</div>

						<!-- 오프라인 토글 (이벤트, 관리자 전용) -->
						{#if type === 'event' && isAdmin && onOfflineToggle && event}
							<button
								onclick={onOfflineToggle}
								class="w-full mt-2 py-2 text-sm rounded transition-colors {event.is_offline
									? 'bg-green-100 text-green-700 hover:bg-green-200'
									: 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
							>
								{event.is_offline ? '📍 오프라인 이벤트' : '🌐 온라인 이벤트'} (클릭하여 변경)
							</button>
						{/if}

						<!-- 출처 목록 -->
						{#if item?.id}
							<div class="mt-3 pt-3 border-t border-gray-100">
								<SourcesList
									entityType={type === 'event' ? 'events' : 'popups'}
									entityId={item.id}
									{isAdmin}
								/>
							</div>
						{/if}

						<!-- 삭제 (이벤트만) -->
						{#if type === 'event' && onDelete}
							<button
								onclick={onDelete}
								class="w-full mt-2 py-2 text-sm text-red-600 hover:bg-red-50 rounded transition-colors"
							>
								이벤트 삭제
							</button>
						{/if}
					</div>
				{:else}
					<!-- 원본 피드 탭 -->
					<div class="flex justify-center py-4">
						{#if loadingPost}
							<div
								class="bg-white rounded-xl p-8 flex items-center justify-center w-full max-w-[468px] h-[300px]"
							>
								<div
									class="animate-spin rounded-full h-12 w-12 border-b-2 border-{themeColor}-600"
								></div>
							</div>
						{:else if instagramPost}
							<FeedCard
								post={instagramPost}
								detailMode={true}
								{onClose}
								onDelete={onDeletePost}
								{onRecrawl}
								{onRequestLlmAnalysis}
								{availableTags}
								onTagsUpdate={onTagsUpdate}
							/>
						{:else}
							<div class="bg-white rounded-xl p-8 text-center w-full max-w-[468px]">
								<p class="text-gray-500 mb-4">Instagram 게시물을 불러올 수 없습니다.</p>
								{#if getInstagramUrl()}
									<a
										href={getInstagramUrl()}
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
