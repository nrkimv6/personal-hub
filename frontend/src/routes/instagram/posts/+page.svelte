<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { page as pageStore } from '$app/stores';
	import { instagramApi, instagramTagApi, accountApi } from '$lib/api';
	import type { InstagramPost, InstagramTag, Account } from '$lib/types';
	import FeedCard from '$lib/components/instagram/FeedCard.svelte';

	let posts: InstagramPost[] = [];
	let total = 0;
	let currentPage = 1;
	let limit = 20;
	let loading = true;
	let error: string | null = null;

	// 태그 목록
	let availableTags: InstagramTag[] = [];

	// 계정 목록 (URL 수집용)
	let accounts: Account[] = [];

	// 뷰 모드 (feed는 상세보기 전용으로 변경됨)
	type ViewMode = 'grid' | 'list';
	let viewMode: ViewMode = 'grid';

	// 필터
	let filterAccount = '';
	let filterSearch = '';  // 캡션 검색어
	let filterPostType: string | null = null;  // NORMAL, SPONSORED, SUGGESTED
	let filterTags: string[] = [];
	let filterDateFrom = '';
	let filterDateTo = '';
	let filterDateType: 'collected' | 'posted' = 'collected';
	let sortBy: string | null = null;
	let sortOrder: string = 'asc';
	let filterIsActive: boolean = true;  // 활성화된 항목만 보기 (기본값)

	// LLM 분류 필터
	let filterLlmTag: string | null = null;
	let filterLlmStatus: string | null = null;

	// 탭 (현재 페이지는 단일 탭이므로 항상 'all')
	let activeTab: 'all' = 'all';

	// LLM 태그 옵션
	const llmTagOptions = [
		{ label: '이벤트', value: 'event', color: 'bg-blue-100 text-blue-700' },
		{ label: '팝업', value: 'popup', color: 'bg-pink-100 text-pink-700' },
		{ label: '일반', value: 'normal', color: 'bg-gray-100 text-gray-700' }
	];

	// LLM 상태 옵션
	const llmStatusOptions = [
		{ label: '대기', value: 'pending', color: 'bg-yellow-100 text-yellow-700' },
		{ label: '분류됨', value: 'classified', color: 'bg-green-100 text-green-700' },
		{ label: '오류', value: 'error', color: 'bg-red-100 text-red-700' }
	];

	// 활성화 필터 토글
	function toggleIsActiveFilter() {
		filterIsActive = !filterIsActive;
		currentPage = 1;
		fetchPosts();
	}

	// 게시물 활성화/비활성화 토글
	async function togglePostActive(post: InstagramPost, event: Event) {
		event.stopPropagation();  // 행 클릭 이벤트 방지
		try {
			await instagramApi.toggleActive(post.id, !post.is_active);
			// 비활성화한 경우 filterIsActive가 true면 목록에서 제거됨
			if (filterIsActive && post.is_active) {
				posts = posts.filter(p => p.id !== post.id);
				total--;
			} else {
				post.is_active = !post.is_active;
				posts = [...posts];  // 반응형 업데이트
			}
		} catch (e) {
			console.error('활성화 상태 변경 실패:', e);
			alert('활성화 상태 변경에 실패했습니다.');
		}
	}

	// 상세보기 (FeedCard detailMode)
	let selectedPost: InstagramPost | null = null;

	// 모바일 필터 표시 상태
	let showFilters = false;

	// 활성 필터 카운트 계산
	$: activeFilterCount = [
		filterAccount,
		filterSearch,
		filterPostType !== null,
		filterTags.length > 0,
		filterDateFrom,
		filterDateTo,
		filterLlmTag,
		filterLlmStatus
	].filter(Boolean).length;

	// localStorage 키
	const STORAGE_KEY_VIEW_MODE = 'instagram_posts_view_mode';
	const STORAGE_KEY_DEFAULT_TAGS = 'instagram_posts_default_tags';

	async function fetchTags() {
		try {
			availableTags = await instagramTagApi.getTags();
			// 첫 로드 시 기본 태그 적용
			if (browser && filterTags.length === 0) {
				const savedTags = localStorage.getItem(STORAGE_KEY_DEFAULT_TAGS);
				if (savedTags) {
					try {
						const parsed = JSON.parse(savedTags);
						if (Array.isArray(parsed)) {
							// 저장된 태그 중 현재 존재하는 태그만 필터링
							filterTags = parsed.filter((t: string) =>
								availableTags.some((at) => at.name === t)
							);
						}
					} catch {
						// ignore
					}
				}
			}
		} catch (e) {
			console.error('태그 목록 로드 실패:', e);
		}
	}

	async function fetchPosts() {
		loading = true;
		try {
			const params: Record<string, unknown> = { page: currentPage, limit };
			if (filterAccount) params.account = filterAccount;
			if (filterSearch) params.search = filterSearch;
			if (filterPostType !== null) params.post_type = filterPostType;
			if (filterTags.length > 0) params.tags = filterTags;
			if (filterDateFrom) {
				if (filterDateType === 'collected') {
					params.date_from = filterDateFrom;
				} else {
					params.posted_from = filterDateFrom;
				}
			}
			if (filterDateTo) {
				if (filterDateType === 'collected') {
					params.date_to = filterDateTo;
				} else {
					params.posted_to = filterDateTo;
				}
			}
			if (sortBy) params.sort_by = sortBy;
			if (sortOrder) params.sort_order = sortOrder;
			// 활성화 상태 필터
			if (filterIsActive) params.is_active = true;

			const response = await instagramApi.posts(params);
			posts = response.posts;
			total = response.total;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : '데이터 로드 실패';
		} finally {
			loading = false;
		}
	}

	function toggleTagFilter(tagName: string) {
		if (filterTags.includes(tagName)) {
			filterTags = filterTags.filter((t) => t !== tagName);
		} else {
			filterTags = [...filterTags, tagName];
		}
	}

	function saveDefaultTags() {
		if (browser) {
			localStorage.setItem(STORAGE_KEY_DEFAULT_TAGS, JSON.stringify(filterTags));
		}
	}

	function formatDateTime(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleString('ko-KR', {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return '-';
		}
	}

	function formatDate(isoString: string | null): string {
		if (!isoString) return '-';
		try {
			const date = new Date(isoString);
			return date.toLocaleDateString('ko-KR', {
				month: 'short',
				day: 'numeric'
			});
		} catch {
			return '-';
		}
	}

	function truncate(text: string | null, maxLength: number): string {
		if (!text) return '';
		// 줄바꿈을 공백으로 변환하여 한 줄로 표시
		const singleLine = text.replace(/\n/g, ' ');
		if (singleLine.length <= maxLength) return singleLine;
		return singleLine.slice(0, maxLength) + '...';
	}


	// URL 수집 모달 상태
	let showUrlCrawlModal = false;
	let urlCrawlInput = '';
	let urlCrawlAccountId: number | null = null;
	let isUrlCrawling = false;
	let isUrlParsing = false;

	// URL 파싱 결과
	let parsedUrl: {
		url_type: string;
		url_type_description: string;
		is_supported: boolean;
		username: string | null;
		hashtag: string | null;
	} | null = null;

	// 피드 수집 옵션 (계정/해시태그/릴스용)
	let urlCrawlMaxPosts = 20;
	let urlCrawlScrollCount = 3;

	// URL 타입별 아이콘/스타일
	const urlTypeStyles: Record<string, { icon: string; color: string; bgColor: string }> = {
		single_post: { icon: '📷', color: 'text-blue-700', bgColor: 'bg-blue-100' },
		single_reel: { icon: '🎬', color: 'text-purple-700', bgColor: 'bg-purple-100' },
		account_profile: { icon: '👤', color: 'text-green-700', bgColor: 'bg-green-100' },
		account_reels: { icon: '🎥', color: 'text-pink-700', bgColor: 'bg-pink-100' },
		hashtag: { icon: '#', color: 'text-orange-700', bgColor: 'bg-orange-100' },
		reels_explore: { icon: '🔥', color: 'text-red-700', bgColor: 'bg-red-100' },
		story: { icon: '⏰', color: 'text-gray-700', bgColor: 'bg-gray-100' },
		unknown: { icon: '❓', color: 'text-gray-700', bgColor: 'bg-gray-100' },
	};

	// 피드 타입인지 (추가 옵션 표시용)
	$: isFeedType = parsedUrl && ['account_profile', 'account_reels', 'hashtag', 'reels_explore'].includes(parsedUrl.url_type);

	async function fetchAccounts() {
		try {
			const response = await accountApi.list();
			accounts = response.filter(a => a.is_logged_in);
			// 기본 계정 선택 (첫 번째 로그인된 계정)
			if (accounts.length > 0 && !urlCrawlAccountId) {
				urlCrawlAccountId = accounts[0].id;
			}
		} catch (e) {
			console.error('계정 목록 로드 실패:', e);
		}
	}

	function openUrlCrawlModal() {
		showUrlCrawlModal = true;
		urlCrawlInput = '';
		parsedUrl = null;
		urlCrawlMaxPosts = 20;
		urlCrawlScrollCount = 3;
	}

	function closeUrlCrawlModal() {
		showUrlCrawlModal = false;
		urlCrawlInput = '';
		parsedUrl = null;
	}

	// URL 입력 시 자동 파싱 (디바운스)
	let parseTimeout: ReturnType<typeof setTimeout> | null = null;
	async function onUrlInput() {
		if (parseTimeout) clearTimeout(parseTimeout);
		parsedUrl = null;

		const url = urlCrawlInput.trim();
		if (!url || !url.includes('instagram.com')) return;

		parseTimeout = setTimeout(async () => {
			isUrlParsing = true;
			try {
				parsedUrl = await instagramApi.parseUrl(url);
			} catch {
				parsedUrl = null;
			} finally {
				isUrlParsing = false;
			}
		}, 300);
	}

	async function submitUrlCrawl() {
		if (!urlCrawlInput.trim()) {
			alert('URL을 입력해주세요.');
			return;
		}
		if (!urlCrawlAccountId) {
			alert('수집에 사용할 계정을 선택해주세요.');
			return;
		}

		// 스토리는 지원 불가
		if (parsedUrl?.url_type === 'story') {
			alert('스토리 크롤링은 지원되지 않습니다.\nInstagram 정책상 스토리는 24시간 후 삭제되며 API 접근이 불가합니다.');
			return;
		}

		isUrlCrawling = true;
		try {
			// 피드 타입은 범용 API, 단일 게시물은 기존 API 사용
			if (isFeedType) {
				await instagramApi.crawlByGenericUrl(urlCrawlInput.trim(), urlCrawlAccountId, {
					maxPosts: urlCrawlMaxPosts,
					scrollCount: urlCrawlScrollCount
				});
			} else {
				await instagramApi.crawlByGenericUrl(urlCrawlInput.trim(), urlCrawlAccountId);
			}
			alert('수집 요청이 등록되었습니다. 워커가 처리하면 게시물이 추가됩니다.');
			closeUrlCrawlModal();
		} catch (e) {
			alert('수집 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		} finally {
			isUrlCrawling = false;
		}
	}

	function openDetail(post: InstagramPost) {
		selectedPost = post;
	}

	function closeDetail() {
		selectedPost = null;
	}

	async function deletePost(id: number) {
		if (!confirm('이 게시물을 삭제하시겠습니까?')) return;
		try {
			await instagramApi.deletePost(id);
			closeDetail();
			await fetchPosts();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function recrawlPost(id: number) {
		try {
			await instagramApi.recrawlPost(id);
			alert('재크롤링 요청이 등록되었습니다. 워커가 처리하면 게시물 정보가 업데이트됩니다.');
		} catch (e) {
			alert('재크롤링 요청 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		}
	}

	async function handleTagsUpdate(postId: number, tagIds: number[]) {
		try {
			const updated = await instagramApi.updatePost(postId, { tag_ids: tagIds });
			// 목록에서 해당 게시물 업데이트
			posts = posts.map((p) => (p.id === updated.id ? updated : p));
			if (selectedPost?.id === postId) {
				selectedPost = updated;
			}
		} catch (e) {
			alert('태그 저장 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
			throw e;
		}
	}

	function handleFilter() {
		currentPage = 1;
		fetchPosts();
	}

	function clearFilters() {
		filterAccount = '';
		filterSearch = '';
		filterPostType = null;
		filterTags = [];
		filterDateFrom = '';
		filterDateTo = '';
		filterLlmTag = null;
		filterLlmStatus = null;
		currentPage = 1;
		fetchPosts();
	}

	function prevPage() {
		if (currentPage > 1) {
			currentPage--;
			fetchPosts();
		}
	}

	function nextPage() {
		if (currentPage * limit < total) {
			currentPage++;
			fetchPosts();
		}
	}

	function setViewMode(mode: ViewMode) {
		viewMode = mode;
		if (browser) {
			localStorage.setItem(STORAGE_KEY_VIEW_MODE, mode);
		}
	}

	onMount(() => {
		// 저장된 뷰 모드 복원 (feed는 더 이상 목록 뷰 모드가 아니므로 grid로 폴백)
		if (browser) {
			const savedMode = localStorage.getItem(STORAGE_KEY_VIEW_MODE);
			if (savedMode === 'grid' || savedMode === 'list') {
				viewMode = savedMode;
			} else if (savedMode === 'feed') {
				// 기존 feed 사용자는 grid로 마이그레이션
				viewMode = 'grid';
				localStorage.setItem(STORAGE_KEY_VIEW_MODE, 'grid');
			}
		}

		// PWA Share Target에서 전달된 URL 처리
		const sharedUrl = $pageStore.url.searchParams.get('shared_url');
		if (sharedUrl) {
			// URL 수집 모달 열고 URL 자동 입력
			showUrlCrawlModal = true;
			urlCrawlInput = sharedUrl;
			// URL 파싱 트리거
			onUrlInput();
		}

		fetchAccounts();
		fetchTags().then(() => fetchPosts());
	});
</script>

<div class="p-4 md:p-6">
	<!-- 헤더 -->
	<div class="mb-4 md:mb-6 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
		<!-- 제목 + URL 수집 버튼 -->
		<div class="flex items-center justify-between sm:justify-start gap-3">
			<h2 class="text-xl md:text-2xl font-bold text-gray-900">게시물</h2>
			<button
				onclick={openUrlCrawlModal}
				class="btn btn-primary btn-sm"
				title="Instagram 게시물 URL을 입력하여 단일 게시물 수집"
			>
				+ URL 수집
			</button>
		</div>

		<!-- 뷰 모드 토글 + 필터 토글 -->
		<div class="flex items-center gap-2">
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

			<!-- 뷰 모드 토글 (전체 탭에서만) -->
			{#if activeTab === 'all'}
				<div class="flex border border-gray-300 rounded-lg overflow-hidden">
					<button
						onclick={() => setViewMode('grid')}
						class="px-3 py-1.5 text-sm transition-colors {viewMode === 'grid'
							? 'bg-blue-600 text-white'
							: 'bg-white text-gray-600 hover:bg-gray-100'}"
						title="그리드 뷰"
					>
						<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
							<path
								d="M5 3a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2V5a2 2 0 00-2-2H5zM5 11a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2v-2a2 2 0 00-2-2H5zM11 5a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V5zM11 13a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
							/>
						</svg>
					</button>
					<button
						onclick={() => setViewMode('list')}
						class="px-3 py-1.5 text-sm transition-colors {viewMode === 'list'
							? 'bg-blue-600 text-white'
							: 'bg-white text-gray-600 hover:bg-gray-100'}"
						title="리스트 뷰"
					>
						<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
							<path
								fill-rule="evenodd"
								d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z"
								clip-rule="evenodd"
							/>
						</svg>
					</button>
				</div>
			{/if}

			<!-- 데스크톱용 기본 필터 (인라인) -->
			<div class="hidden md:flex items-center gap-2">
				<input
					type="text"
					placeholder="캡션 검색"
					bind:value={filterSearch}
					class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm w-36"
				/>
				<input
					type="text"
					placeholder="계정명"
					bind:value={filterAccount}
					class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm w-28"
				/>
				<select
					bind:value={filterPostType}
					class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
				>
					<option value={null}>전체</option>
					<option value="SPONSORED">광고</option>
					<option value="SUGGESTED">추천</option>
					<option value="NORMAL">일반</option>
				</select>
				<button onclick={handleFilter} class="btn btn-primary btn-sm">필터 적용</button>
			</div>
		</div>
	</div>

	<!-- 탭: 게시물 / 이벤트(링크) / 팝업(링크) -->
	<div class="mb-4 border-b border-gray-200">
		<nav class="flex gap-4">
			<span class="pb-2 px-1 text-sm font-medium border-b-2 border-blue-600 text-blue-600">
				게시물
			</span>
			<a
				href="/events"
				class="pb-2 px-1 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700"
			>
				이벤트 →
			</a>
			<a
				href="/popups"
				class="pb-2 px-1 text-sm font-medium border-b-2 border-transparent text-gray-500 hover:text-gray-700"
			>
				팝업 →
			</a>
		</nav>
	</div>

	<!-- 모바일 필터 패널 (접이식) -->
	<div
		class="md:hidden mb-4 bg-white rounded-lg border border-gray-200 overflow-hidden transition-all duration-300"
		class:hidden={!showFilters}
	>
		<div class="p-4 space-y-4">
			<!-- 검색/계정/광고 필터 -->
			<div class="flex flex-col gap-2">
				<label class="text-sm font-medium text-gray-700">기본 필터</label>
				<input
					type="text"
					placeholder="캡션 검색"
					bind:value={filterSearch}
					class="px-3 py-2 border border-gray-300 rounded-lg text-sm"
				/>
				<input
					type="text"
					placeholder="계정명 필터"
					bind:value={filterAccount}
					class="px-3 py-2 border border-gray-300 rounded-lg text-sm"
				/>
				<select
					bind:value={filterPostType}
					class="px-3 py-2 border border-gray-300 rounded-lg text-sm"
				>
					<option value={null}>전체</option>
					<option value="SPONSORED">광고</option>
					<option value="SUGGESTED">추천</option>
					<option value="NORMAL">일반</option>
				</select>
			</div>

			<!-- 날짜 필터 -->
			<div class="flex flex-col gap-2">
				<label class="text-sm font-medium text-gray-700">날짜 필터</label>
				<select
					bind:value={filterDateType}
					class="px-3 py-2 border border-gray-300 rounded-lg text-sm"
				>
					<option value="collected">수집일</option>
					<option value="posted">업로드일</option>
				</select>
				<div class="flex items-center gap-2">
					<input
						type="date"
						bind:value={filterDateFrom}
						class="flex-1 px-2 py-2 border border-gray-300 rounded-lg text-sm"
					/>
					<span class="text-gray-400">~</span>
					<input
						type="date"
						bind:value={filterDateTo}
						class="flex-1 px-2 py-2 border border-gray-300 rounded-lg text-sm"
					/>
				</div>
			</div>

				<!-- AI 분류 필터 -->
			<div class="flex flex-col gap-2">
				<label class="text-sm font-medium text-gray-700">AI 분류</label>
				<div class="flex flex-wrap gap-2">
					{#each llmTagOptions as opt}
						<button
							onclick={() => {
								filterLlmTag = filterLlmTag === opt.value ? null : opt.value;
							}}
							class="px-3 py-1.5 text-sm rounded-full transition-colors {filterLlmTag === opt.value ? opt.color + ' ring-2 ring-offset-1 ring-purple-400' : 'bg-gray-100 text-gray-600'}"
						>
							{opt.label}
						</button>
					{/each}
				</div>
				<div class="flex flex-wrap gap-2">
					{#each llmStatusOptions as opt}
						<button
							onclick={() => {
								filterLlmStatus = filterLlmStatus === opt.value ? null : opt.value;
							}}
							class="px-2 py-1 text-xs rounded-full transition-colors {filterLlmStatus === opt.value ? opt.color + ' ring-2 ring-offset-1 ring-gray-400' : 'bg-gray-100 text-gray-600'}"
						>
							{opt.label}
						</button>
					{/each}
				</div>
			</div>

			<!-- 필터 액션 버튼 -->
			<div class="flex gap-2 pt-2 border-t border-gray-100">
				<button onclick={handleFilter} class="flex-1 btn btn-primary btn-sm">
					필터 적용
				</button>
				<button onclick={clearFilters} class="btn btn-secondary btn-sm">
					초기화
				</button>
			</div>
		</div>
	</div>

	<!-- 데스크톱 필터 영역 (전체 탭에서만) -->
	{#if activeTab === 'all'}
		<!-- 날짜 필터 -->
		<div class="hidden md:flex mb-4 flex-wrap gap-2 items-center">
			<span class="text-sm text-gray-500">날짜 필터:</span>
			<select
				bind:value={filterDateType}
				class="px-2 py-1 border border-gray-300 rounded text-sm"
			>
				<option value="collected">수집일</option>
				<option value="posted">업로드일</option>
			</select>
			<input
				type="date"
				bind:value={filterDateFrom}
				class="px-2 py-1 border border-gray-300 rounded text-sm"
			/>
			<span class="text-gray-400">~</span>
			<input
				type="date"
				bind:value={filterDateTo}
				class="px-2 py-1 border border-gray-300 rounded text-sm"
			/>
			{#if filterDateFrom || filterDateTo}
				<button
					onclick={() => {
						filterDateFrom = '';
						filterDateTo = '';
						handleFilter();
					}}
					class="text-sm text-gray-500 hover:text-gray-700 underline"
				>
					날짜 초기화
				</button>
			{/if}
		</div>

		<!-- LLM 분류 필터 -->
		<div class="hidden md:flex mb-4 flex-wrap gap-2 items-center">
			<span class="text-sm text-gray-500">AI 분류:</span>
			{#each llmTagOptions as opt}
				<button
					onclick={() => {
						filterLlmTag = filterLlmTag === opt.value ? null : opt.value;
						handleFilter();
					}}
					class="px-3 py-1 text-sm rounded-full transition-colors {filterLlmTag === opt.value ? opt.color + ' ring-2 ring-offset-1 ring-purple-400' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
				>
					{opt.label}
					{#if filterLlmTag === opt.value}
						<span class="ml-1">✓</span>
					{/if}
				</button>
			{/each}
			<span class="text-gray-300 mx-1">|</span>
			<span class="text-sm text-gray-500">상태:</span>
			{#each llmStatusOptions as opt}
				<button
					onclick={() => {
						filterLlmStatus = filterLlmStatus === opt.value ? null : opt.value;
						handleFilter();
					}}
					class="px-2 py-1 text-xs rounded-full transition-colors {filterLlmStatus === opt.value ? opt.color + ' ring-2 ring-offset-1 ring-gray-400' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
				>
					{opt.label}
				</button>
			{/each}
			{#if filterLlmTag || filterLlmStatus}
				<button
					onclick={() => {
						filterLlmTag = null;
						filterLlmStatus = null;
						handleFilter();
					}}
					class="text-sm text-gray-500 hover:text-gray-700 underline"
				>
					AI 필터 초기화
				</button>
			{/if}
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
	{:else if posts.length === 0}
		<div class="text-center py-12 text-gray-500">
			<p class="text-lg">수집된 게시물이 없습니다</p>
			<p class="text-sm mt-2">Instagram 수집을 시작하면 여기에 게시물이 표시됩니다</p>
			{#if filterTags.length > 0 || filterAccount || filterPostType !== null || filterDateFrom || filterDateTo}
				<button onclick={clearFilters} class="mt-4 btn btn-secondary btn-sm">
					필터 초기화
				</button>
			{/if}
		</div>
	{:else}
		<!-- 리스트/그리드 뷰 -->
		{#if viewMode === 'list'}
			<!-- 리스트 뷰 (데스크톱) -->
			<div class="hidden md:block bg-white rounded-lg border border-gray-200 overflow-x-auto mb-6">
				<table class="w-full min-w-[700px]">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">PK</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">이미지</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">계정</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">내용</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">업로드일</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">수집일</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each posts as post (post.id)}
							<tr
								class="hover:bg-gray-50 cursor-pointer"
								onclick={() => openDetail(post)}
								onkeydown={(e) => e.key === 'Enter' && openDetail(post)}
								tabindex="0"
							>
								<td class="px-4 py-3 text-xs text-gray-500 font-mono">
									{post.id}
								</td>
								<td class="px-4 py-3">
									{#if post.images && post.images.length > 0}
										<img
											src={post.images[0].src}
											alt={post.images[0].alt || '게시물 이미지'}
											class="w-12 h-12 object-cover rounded"
											loading="lazy"
										/>
									{:else}
										<div class="w-12 h-12 bg-gray-200 rounded flex items-center justify-center">
											<span class="text-gray-400">?</span>
										</div>
									{/if}
								</td>
								<td class="px-4 py-3">
									<div class="flex items-center gap-2">
										<span class="font-medium text-sm text-gray-900">@{post.account}</span>
										{#if post.is_ad}
											<span class="px-1.5 py-0.5 text-xs bg-yellow-100 text-yellow-800 rounded">광고</span>
										{/if}
									</div>
								</td>
								<td class="px-4 py-3 max-w-xs">
									<p class="text-sm text-gray-600 truncate">{truncate(post.caption, 60)}</p>
								</td>
								<td class="px-4 py-3 text-sm text-gray-500">
									{post.display_time || formatDate(post.posted_at)}
								</td>
								<td class="px-4 py-3 text-sm text-gray-500">
									{formatDate(post.collected_at)}
								</td>
								<td class="px-4 py-3">
									<div class="flex gap-1" onclick={(e) => e.stopPropagation()}>
										{#if post.url}
											<a
												href={post.url}
												target="_blank"
												rel="noopener noreferrer"
												class="text-blue-600 hover:text-blue-800 text-sm"
											>
												원본
											</a>
										{/if}
										<button
											onclick={() => deletePost(post.id)}
											class="text-red-600 hover:text-red-800 text-sm ml-2"
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
			<!-- 리스트 뷰 (모바일용 카드 리스트) -->
			<div class="md:hidden space-y-3 mb-6">
				{#each posts as post (post.id)}
					<div
						class="bg-white rounded-lg border border-gray-200 p-3 flex gap-3 cursor-pointer hover:shadow-md transition-shadow"
						onclick={() => openDetail(post)}
						onkeydown={(e) => e.key === 'Enter' && openDetail(post)}
						role="button"
						tabindex="0"
					>
						<!-- 썸네일 -->
						<div class="w-16 h-16 flex-shrink-0">
							{#if post.images && post.images.length > 0}
								<img
									src={post.images[0].src}
									alt={post.images[0].alt || '게시물 이미지'}
									class="w-full h-full object-cover rounded"
									loading="lazy"
								/>
							{:else}
								<div class="w-full h-full bg-gray-200 rounded flex items-center justify-center">
									<span class="text-gray-400">?</span>
								</div>
							{/if}
						</div>
						<!-- 정보 -->
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2 mb-1">
								<span class="font-medium text-sm text-gray-900">@{post.account}</span>
								{#if post.is_ad}
									<span class="px-1.5 py-0.5 text-xs bg-yellow-100 text-yellow-800 rounded">광고</span>
								{/if}
							</div>
							<p class="text-xs text-gray-600 truncate">{truncate(post.caption, 40)}</p>
							<div class="flex items-center gap-1 mt-1 flex-wrap">
								<span class="text-xs text-gray-400 ml-auto">{formatDate(post.collected_at)}</span>
							</div>
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<!-- 그리드 뷰 -->
			<div class="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 md:gap-4 mb-6">
				{#each posts as post (post.id)}
					<div
						class="card cursor-pointer hover:shadow-lg transition-shadow"
						onclick={() => openDetail(post)}
						onkeydown={(e) => e.key === 'Enter' && openDetail(post)}
						role="button"
						tabindex="0"
					>
						<!-- 이미지 -->
						{#if post.images && post.images.length > 0}
							<div class="aspect-square bg-gray-100 rounded-lg mb-2 md:mb-3 overflow-hidden">
								<img
									src={post.images[0].src}
									alt={post.images[0].alt || '게시물 이미지'}
									class="w-full h-full object-cover"
									loading="lazy"
								/>
							</div>
						{:else}
							<div
								class="aspect-square bg-gray-200 rounded-lg mb-2 md:mb-3 flex items-center justify-center"
							>
								<span class="text-gray-400 text-2xl md:text-4xl">?</span>
							</div>
						{/if}

						<!-- 정보 -->
						<div class="space-y-1">
							<div class="flex items-center justify-between">
								<span class="font-medium text-xs md:text-sm text-gray-900 truncate">@{post.account}</span>
								{#if post.is_ad}
									<span class="px-1.5 py-0.5 text-xs bg-yellow-100 text-yellow-800 rounded-full flex-shrink-0"
										>광고</span
									>
								{/if}
							</div>
							<p class="text-xs text-gray-500 line-clamp-2 hidden md:block">{truncate(post.caption, 50)}</p>
							<p class="text-xs text-gray-400">
								{post.display_time || formatDateTime(post.collected_at)}
							</p>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- 페이지네이션 -->
		<div class="flex flex-col sm:flex-row justify-between items-center gap-3">
			<span class="text-sm text-gray-500">
				전체 {total}개 중 {(currentPage - 1) * limit + 1} - {Math.min(currentPage * limit, total)}
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
					{currentPage} / {Math.ceil(total / limit)}
				</span>
				<button
					onclick={nextPage}
					disabled={currentPage * limit >= total}
					class="btn btn-secondary btn-sm disabled:opacity-50"
				>
					다음
				</button>
			</div>
		</div>
	{/if}
</div>

<!-- 상세보기 (FeedCard detailMode) -->
{#if selectedPost}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center sm:p-4"
		onclick={closeDetail}
		onkeydown={(e) => e.key === 'Escape' && closeDetail()}
		role="dialog"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div
			class="w-full sm:max-w-lg max-h-[95vh] sm:max-h-[90vh] overflow-auto rounded-t-xl sm:rounded-xl"
			onclick={(e) => e.stopPropagation()}
		>
			<FeedCard
				post={selectedPost}
				detailMode={true}
				onClose={closeDetail}
				onDelete={deletePost}
				onRecrawl={recrawlPost}
				{availableTags}
				onTagsUpdate={handleTagsUpdate}
			/>
		</div>
	</div>
{/if}

<!-- URL 수집 모달 -->
{#if showUrlCrawlModal}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center sm:p-4"
		onclick={closeUrlCrawlModal}
		onkeydown={(e) => e.key === 'Escape' && closeUrlCrawlModal()}
		role="dialog"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div
			class="bg-white rounded-t-xl sm:rounded-xl w-full sm:max-w-lg"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<h3 class="text-lg font-bold text-gray-900">URL로 수집</h3>
					<button onclick={closeUrlCrawlModal} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<div class="space-y-4">
					<div>
						<label for="url-input" class="block text-sm font-medium text-gray-700 mb-1">
							Instagram URL
						</label>
						<input
							id="url-input"
							type="text"
							bind:value={urlCrawlInput}
							oninput={onUrlInput}
							placeholder="https://www.instagram.com/..."
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						/>

						<!-- URL 파싱 결과 표시 -->
						{#if isUrlParsing}
							<p class="mt-2 text-xs text-gray-500 flex items-center gap-1">
								<span class="animate-spin inline-block w-3 h-3 border border-gray-400 border-t-transparent rounded-full"></span>
								URL 분석 중...
							</p>
						{:else if parsedUrl}
							{@const style = urlTypeStyles[parsedUrl.url_type] || urlTypeStyles.unknown}
							<div class="mt-2 p-2 rounded-lg {style.bgColor}">
								<div class="flex items-center gap-2">
									<span class="text-lg">{style.icon}</span>
									<span class="text-sm font-medium {style.color}">{parsedUrl.url_type_description}</span>
									{#if !parsedUrl.is_supported}
										<span class="px-1.5 py-0.5 text-xs bg-red-100 text-red-700 rounded">지원 불가</span>
									{/if}
								</div>
								{#if parsedUrl.username}
									<p class="mt-1 text-xs {style.color}">계정: @{parsedUrl.username}</p>
								{/if}
								{#if parsedUrl.hashtag}
									<p class="mt-1 text-xs {style.color}">해시태그: #{parsedUrl.hashtag}</p>
								{/if}
								{#if parsedUrl.url_type === 'story'}
									<p class="mt-1 text-xs text-red-600">스토리는 24시간 후 삭제되며 API 접근이 불가합니다.</p>
								{/if}
							</div>
						{:else if urlCrawlInput.trim()}
							<p class="mt-1 text-xs text-gray-500">
								지원: 게시물, 릴스, 계정 피드, 해시태그
							</p>
						{:else}
							<p class="mt-1 text-xs text-gray-500">
								예: instagram.com/p/..., instagram.com/username/, instagram.com/explore/tags/...
							</p>
						{/if}
					</div>

					<!-- 피드 수집 옵션 (계정/해시태그/릴스용) -->
					{#if isFeedType}
						<div class="p-3 bg-gray-50 rounded-lg space-y-3">
							<p class="text-sm font-medium text-gray-700">피드 수집 옵션</p>
							<div class="grid grid-cols-2 gap-3">
								<div>
									<label for="max-posts" class="block text-xs text-gray-600 mb-1">최대 게시물 수</label>
									<input
										id="max-posts"
										type="number"
										min="1"
										max="100"
										bind:value={urlCrawlMaxPosts}
										class="w-full px-2 py-1.5 border border-gray-300 rounded text-sm"
									/>
								</div>
								<div>
									<label for="scroll-count" class="block text-xs text-gray-600 mb-1">스크롤 횟수</label>
									<input
										id="scroll-count"
										type="number"
										min="1"
										max="20"
										bind:value={urlCrawlScrollCount}
										class="w-full px-2 py-1.5 border border-gray-300 rounded text-sm"
									/>
								</div>
							</div>
							<p class="text-xs text-gray-500">
								계정/해시태그 피드는 스크롤하며 게시물을 수집합니다.
							</p>
						</div>
					{/if}

					<div>
						<label for="account-select" class="block text-sm font-medium text-gray-700 mb-1">
							수집에 사용할 계정
						</label>
						{#if accounts.length > 0}
							<select
								id="account-select"
								bind:value={urlCrawlAccountId}
								class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
							>
								{#each accounts as account (account.id)}
									<option value={account.id}>{account.name}</option>
								{/each}
							</select>
						{:else}
							<p class="text-sm text-red-600">로그인된 계정이 없습니다. 먼저 계정에 로그인해주세요.</p>
						{/if}
					</div>
				</div>

				<div class="mt-6 flex gap-2 justify-end">
					<button onclick={closeUrlCrawlModal} class="btn btn-secondary btn-sm">
						취소
					</button>
					<button
						onclick={submitUrlCrawl}
						disabled={isUrlCrawling || accounts.length === 0 || (parsedUrl && !parsedUrl.is_supported)}
						class="btn btn-primary btn-sm disabled:opacity-50"
					>
						{#if isUrlCrawling}
							수집 중...
						{:else}
							수집 요청
						{/if}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
