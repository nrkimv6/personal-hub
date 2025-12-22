<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { instagramApi, instagramTagApi, accountApi } from '$lib/api';
	import type { InstagramPost, InstagramTag, Account } from '$lib/types';
	import FeedCard from '$lib/components/instagram/FeedCard.svelte';

	let posts: InstagramPost[] = [];
	let total = 0;
	let page = 1;
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
	let filterIsAd: boolean | null = null;
	let filterTags: string[] = [];
	let filterDateFrom = '';
	let filterDateTo = '';
	let filterDateType: 'collected' | 'posted' = 'collected';

	// 상세보기 (FeedCard detailMode)
	let selectedPost: InstagramPost | null = null;

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
			const params: Record<string, unknown> = { page, limit };
			if (filterAccount) params.account = filterAccount;
			if (filterIsAd !== null) params.is_ad = filterIsAd;
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
	}

	function closeUrlCrawlModal() {
		showUrlCrawlModal = false;
		urlCrawlInput = '';
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
		isUrlCrawling = true;
		try {
			await instagramApi.crawlByUrl(urlCrawlInput.trim(), urlCrawlAccountId);
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
		page = 1;
		fetchPosts();
	}

	function clearFilters() {
		filterAccount = '';
		filterIsAd = null;
		filterTags = [];
		filterDateFrom = '';
		filterDateTo = '';
		page = 1;
		fetchPosts();
	}

	function prevPage() {
		if (page > 1) {
			page--;
			fetchPosts();
		}
	}

	function nextPage() {
		if (page * limit < total) {
			page++;
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
		fetchAccounts();
		fetchTags().then(() => fetchPosts());
	});
</script>

<div class="p-6">
	<!-- 헤더 -->
	<div class="mb-6 flex flex-wrap justify-between items-center gap-4">
		<div class="flex items-center gap-3">
			<h2 class="text-2xl font-bold text-gray-900">게시물 목록</h2>
			<button
				onclick={openUrlCrawlModal}
				class="btn btn-primary btn-sm"
				title="Instagram 게시물 URL을 입력하여 단일 게시물 수집"
			>
				+ URL 수집
			</button>
		</div>
		<div class="flex flex-wrap gap-2 items-center">
			<!-- 뷰 모드 토글 -->
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
			<input
				type="text"
				placeholder="계정명 필터"
				bind:value={filterAccount}
				class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
			/>
			<select
				bind:value={filterIsAd}
				class="px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
			>
				<option value={null}>전체</option>
				<option value={true}>광고만</option>
				<option value={false}>일반만</option>
			</select>
			<button onclick={handleFilter} class="btn btn-primary btn-sm">필터 적용</button>
		</div>
	</div>

	<!-- 날짜 필터 -->
	<div class="mb-4 flex flex-wrap gap-2 items-center">
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

	<!-- 태그 필터 -->
	{#if availableTags.length > 0}
		<div class="mb-4 flex flex-wrap gap-2 items-center">
			<span class="text-sm text-gray-500">태그 필터:</span>
			{#each availableTags as tag (tag.id)}
				<button
					onclick={() => {
						toggleTagFilter(tag.name);
						handleFilter();
					}}
					class="px-3 py-1 text-sm rounded-full transition-colors"
					style="background-color: {filterTags.includes(tag.name)
						? tag.color
						: '#f3f4f6'}; color: {filterTags.includes(tag.name) ? 'white' : '#374151'};"
				>
					{tag.display_name}
					{#if filterTags.includes(tag.name)}
						<span class="ml-1">✓</span>
					{/if}
				</button>
			{/each}
			{#if filterTags.length > 0}
				<button
					onclick={() => {
						filterTags = [];
						handleFilter();
					}}
					class="text-sm text-gray-500 hover:text-gray-700 underline"
				>
					초기화
				</button>
				<button onclick={saveDefaultTags} class="text-sm text-blue-600 hover:text-blue-800 underline">
					기본값 저장
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
			{#if filterTags.length > 0 || filterAccount || filterIsAd !== null || filterDateFrom || filterDateTo}
				<button onclick={clearFilters} class="mt-4 btn btn-secondary btn-sm">
					필터 초기화
				</button>
			{/if}
		</div>
	{:else}
		<!-- 리스트 뷰 -->
		{#if viewMode === 'list'}
			<div class="bg-white rounded-lg border border-gray-200 overflow-hidden mb-6">
				<table class="w-full">
					<thead class="bg-gray-50 border-b border-gray-200">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">이미지</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">계정</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">내용</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">태그</th>
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
								<td class="px-4 py-3">
									<div class="flex flex-wrap gap-1">
										{#if post.tags && post.tags.length > 0}
											{#each post.tags as tag}
												<span
													class="px-1.5 py-0.5 text-xs rounded-full text-white"
													style="background-color: {tag.color};"
												>
													{tag.display_name}
												</span>
											{/each}
										{/if}
										{#if post.llm_status === 'completed' && post.llm_tag}
											<span class="px-1.5 py-0.5 text-xs rounded-full bg-purple-100 text-purple-700" title="AI 분류">
												{post.llm_tag}
											</span>
										{:else if post.llm_status === 'pending' || post.llm_status === 'processing'}
											<span class="px-1.5 py-0.5 text-xs rounded-full bg-gray-100 text-gray-500 animate-pulse" title="AI 분석 중">
												AI
											</span>
										{/if}
										{#if !post.tags?.length && !post.llm_status}
											<span class="text-gray-400 text-sm">-</span>
										{/if}
									</div>
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
		{:else}
			<!-- 그리드 뷰 -->
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 mb-6">
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
							<div class="aspect-square bg-gray-100 rounded-lg mb-3 overflow-hidden">
								<img
									src={post.images[0].src}
									alt={post.images[0].alt || '게시물 이미지'}
									class="w-full h-full object-cover"
									loading="lazy"
								/>
							</div>
						{:else}
							<div
								class="aspect-square bg-gray-200 rounded-lg mb-3 flex items-center justify-center"
							>
								<span class="text-gray-400 text-4xl">?</span>
							</div>
						{/if}

						<!-- 정보 -->
						<div class="space-y-1">
							<div class="flex items-center justify-between">
								<span class="font-medium text-sm text-gray-900">@{post.account}</span>
								{#if post.is_ad}
									<span class="px-2 py-0.5 text-xs bg-yellow-100 text-yellow-800 rounded-full"
										>광고</span
									>
								{/if}
							</div>
							<!-- 태그 표시 -->
							{#if post.tags?.length || post.llm_status}
								<div class="flex flex-wrap gap-1">
									{#if post.tags && post.tags.length > 0}
										{#each post.tags as tag}
											<span
												class="px-1.5 py-0.5 text-xs rounded-full text-white"
												style="background-color: {tag.color};"
											>
												{tag.display_name}
											</span>
										{/each}
									{/if}
									{#if post.llm_status === 'completed' && post.llm_tag}
										<span class="px-1.5 py-0.5 text-xs rounded-full bg-purple-100 text-purple-700" title="AI 분류">
											{post.llm_tag}
										</span>
									{:else if post.llm_status === 'pending' || post.llm_status === 'processing'}
										<span class="px-1.5 py-0.5 text-xs rounded-full bg-gray-100 text-gray-500 animate-pulse" title="AI 분석 중">
											AI
										</span>
									{/if}
								</div>
							{/if}
							<p class="text-xs text-gray-500">{truncate(post.caption, 50)}</p>
							<p class="text-xs text-gray-400">
								{post.display_time || formatDateTime(post.collected_at)}
							</p>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- 페이지네이션 -->
		<div class="flex justify-between items-center">
			<span class="text-sm text-gray-500">
				전체 {total}개 중 {(page - 1) * limit + 1} - {Math.min(page * limit, total)}
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
					{page} / {Math.ceil(total / limit)}
				</span>
				<button
					onclick={nextPage}
					disabled={page * limit >= total}
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
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={closeDetail}
		onkeydown={(e) => e.key === 'Escape' && closeDetail()}
		role="dialog"
		tabindex="-1"
	>
		<div class="max-w-lg w-full max-h-[90vh] overflow-auto" onclick={(e) => e.stopPropagation()}>
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
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={closeUrlCrawlModal}
		onkeydown={(e) => e.key === 'Escape' && closeUrlCrawlModal()}
		role="dialog"
		tabindex="-1"
	>
		<div
			class="bg-white rounded-xl max-w-lg w-full"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<h3 class="text-lg font-bold text-gray-900">URL로 게시물 수집</h3>
					<button onclick={closeUrlCrawlModal} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<div class="space-y-4">
					<div>
						<label for="url-input" class="block text-sm font-medium text-gray-700 mb-1">
							Instagram 게시물 URL
						</label>
						<input
							id="url-input"
							type="text"
							bind:value={urlCrawlInput}
							placeholder="https://www.instagram.com/p/..."
							class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
						/>
						<p class="mt-1 text-xs text-gray-500">
							예: https://www.instagram.com/p/ABC123/
						</p>
					</div>

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
						disabled={isUrlCrawling || accounts.length === 0}
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
