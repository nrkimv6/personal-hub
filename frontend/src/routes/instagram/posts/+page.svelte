<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { instagramApi, instagramTagApi } from '$lib/api';
	import type { InstagramPost, InstagramTag } from '$lib/types';

	let posts: InstagramPost[] = [];
	let total = 0;
	let page = 1;
	let limit = 20;
	let loading = true;
	let error: string | null = null;

	// 태그 목록
	let availableTags: InstagramTag[] = [];

	// 뷰 모드
	type ViewMode = 'grid' | 'list';
	let viewMode: ViewMode = 'grid';

	// 필터
	let filterAccount = '';
	let filterIsAd: boolean | null = null;
	let filterTags: string[] = [];
	let filterDateFrom = '';
	let filterDateTo = '';
	let filterDateType: 'collected' | 'posted' = 'collected';

	// 모달
	let selectedPost: InstagramPost | null = null;
	let showModal = false;

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

	function openModal(post: InstagramPost) {
		selectedPost = post;
		showModal = true;
	}

	function closeModal() {
		showModal = false;
		selectedPost = null;
	}

	async function deletePost(id: number) {
		if (!confirm('이 게시물을 삭제하시겠습니까?')) return;
		try {
			await instagramApi.deletePost(id);
			await fetchPosts();
		} catch (e) {
			alert('삭제 실패: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
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
		// 저장된 뷰 모드 복원
		if (browser) {
			const savedMode = localStorage.getItem(STORAGE_KEY_VIEW_MODE);
			if (savedMode === 'grid' || savedMode === 'list') {
				viewMode = savedMode;
			}
		}
		fetchTags().then(() => fetchPosts());
	});
</script>

<div class="p-6">
	<!-- 헤더 -->
	<div class="mb-6 flex flex-wrap justify-between items-center gap-4">
		<h2 class="text-2xl font-bold text-gray-900">게시물 목록</h2>
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
								onclick={() => openModal(post)}
								onkeydown={(e) => e.key === 'Enter' && openModal(post)}
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
									{#if post.tags && post.tags.length > 0}
										<div class="flex flex-wrap gap-1">
											{#each post.tags as tag}
												<span
													class="px-1.5 py-0.5 text-xs rounded-full text-white"
													style="background-color: {tag.color};"
												>
													{tag.display_name}
												</span>
											{/each}
										</div>
									{:else}
										<span class="text-gray-400 text-sm">-</span>
									{/if}
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
						onclick={() => openModal(post)}
						onkeydown={(e) => e.key === 'Enter' && openModal(post)}
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
							{#if post.tags && post.tags.length > 0}
								<div class="flex flex-wrap gap-1">
									{#each post.tags as tag}
										<span
											class="px-1.5 py-0.5 text-xs rounded-full text-white"
											style="background-color: {tag.color};"
										>
											{tag.display_name}
										</span>
									{/each}
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

<!-- 상세 모달 -->
{#if showModal && selectedPost}
	<div
		class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
		onclick={closeModal}
		onkeydown={(e) => e.key === 'Escape' && closeModal()}
		role="dialog"
		tabindex="-1"
	>
		<div
			class="bg-white rounded-xl max-w-2xl w-full max-h-[90vh] overflow-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="p-6">
				<div class="flex justify-between items-start mb-4">
					<div>
						<h3 class="text-lg font-bold text-gray-900">@{selectedPost.account}</h3>
						<p class="text-sm text-gray-500">
							{selectedPost.display_time || formatDateTime(selectedPost.posted_at)}
						</p>
					</div>
					<button onclick={closeModal} class="text-gray-400 hover:text-gray-600 text-2xl">
						&times;
					</button>
				</div>

				<!-- 이미지 캐러셀 -->
				{#if selectedPost.images && selectedPost.images.length > 0}
					<div class="mb-4">
						{#each selectedPost.images as img, idx}
							<img
								src={img.src}
								alt={img.alt || `이미지 ${idx + 1}`}
								class="w-full rounded-lg mb-2"
							/>
						{/each}
					</div>
				{/if}

				<!-- 캡션 -->
				{#if selectedPost.caption}
					<div class="mb-4 p-3 bg-gray-50 rounded-lg">
						<p class="text-sm text-gray-700 whitespace-pre-wrap break-words">{selectedPost.caption}</p>
					</div>
				{/if}

				<!-- 태그 -->
				{#if selectedPost.tags && selectedPost.tags.length > 0}
					<div class="mb-4">
						<span class="text-sm text-gray-500 mr-2">태그:</span>
						{#each selectedPost.tags as tag}
							<span
								class="inline-block px-2 py-0.5 text-xs rounded-full text-white mr-1"
								style="background-color: {tag.color};"
							>
								{tag.display_name}
							</span>
						{/each}
					</div>
				{/if}

				<!-- 메타 정보 -->
				<div class="grid grid-cols-2 gap-2 text-sm mb-4">
					<div>
						<span class="text-gray-500">수집 시간:</span>
						<span class="ml-1">{formatDateTime(selectedPost.collected_at)}</span>
					</div>
					<div>
						<span class="text-gray-500">광고:</span>
						<span class="ml-1">{selectedPost.is_ad ? '예' : '아니오'}</span>
					</div>
				</div>

				<!-- 액션 버튼 -->
				<div class="flex gap-2">
					{#if selectedPost.url}
						<a
							href={selectedPost.url}
							target="_blank"
							rel="noopener noreferrer"
							class="btn btn-primary btn-sm"
						>
							원본 보기
						</a>
					{/if}
					<button
						onclick={() => {
							deletePost(selectedPost!.id);
							closeModal();
						}}
						class="btn btn-danger btn-sm"
					>
						삭제
					</button>
					<button onclick={closeModal} class="btn btn-secondary btn-sm">닫기</button>
				</div>
			</div>
		</div>
	</div>
{/if}
