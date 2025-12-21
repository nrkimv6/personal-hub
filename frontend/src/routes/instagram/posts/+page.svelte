<script lang="ts">
	import { onMount } from 'svelte';
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

	// 필터
	let filterAccount = '';
	let filterIsAd: boolean | null = null;
	let filterTags: string[] = [];

	// 모달
	let selectedPost: InstagramPost | null = null;
	let showModal = false;

	async function fetchTags() {
		try {
			availableTags = await instagramTagApi.getTags();
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

	function truncate(text: string | null, maxLength: number): string {
		if (!text) return '';
		if (text.length <= maxLength) return text;
		return text.slice(0, maxLength) + '...';
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

	onMount(() => {
		fetchTags();
		fetchPosts();
	});
</script>

<div class="p-6">
	<div class="mb-6 flex flex-wrap justify-between items-center gap-4">
		<h2 class="text-2xl font-bold text-gray-900">게시물 목록</h2>
		<div class="flex flex-wrap gap-2 items-center">
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
			<button onclick={handleFilter} class="btn btn-primary btn-sm"> 필터 적용 </button>
		</div>
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
		</div>
	{:else}
		<!-- 게시물 그리드 -->
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
	<div class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
		<div class="bg-white rounded-xl max-w-2xl w-full max-h-[90vh] overflow-auto">
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
						<p class="text-sm text-gray-700 whitespace-pre-wrap">{selectedPost.caption}</p>
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
					<button onclick={closeModal} class="btn btn-secondary btn-sm"> 닫기 </button>
				</div>
			</div>
		</div>
	</div>
{/if}
