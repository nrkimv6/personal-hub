<script lang="ts">
	import { toPng } from 'html-to-image';
	import type { InstagramPost, InstagramTag } from '$lib/types';

	interface Props {
		post: InstagramPost;
		// 목록 모드용
		onOpenDetail?: (post: InstagramPost) => void;
		// 상세 모드용
		detailMode?: boolean;
		onClose?: () => void;
		onDelete?: (id: number) => void;
		onRecrawl?: (id: number) => void;
		availableTags?: InstagramTag[];
		onTagsUpdate?: (postId: number, tagIds: number[]) => void;
	}

	let {
		post,
		onOpenDetail,
		detailMode = false,
		onClose,
		onDelete,
		onRecrawl,
		availableTags = [],
		onTagsUpdate,
	}: Props = $props();

	// 상세 모드에서는 캡션 기본 펼침
	let isExpanded = $state(detailMode);
	let imageLoading = $state(true);
	let currentImageIndex = $state(0);

	// 태그 편집 상태
	let editingTags = $state(false);
	let editTagIds = $state<number[]>([]);
	let savingTags = $state(false);

	// 재크롤링 상태
	let isRecrawling = $state(false);

	// 캡쳐 상태
	let isCapturing = $state(false);
	let feedRef: HTMLElement | null = $state(null);

	function toggleExpand() {
		isExpanded = !isExpanded;
	}

	function handleImageLoad() {
		imageLoading = false;
	}

	function handleClick() {
		if (!detailMode && onOpenDetail) {
			onOpenDetail(post);
		}
	}

	function nextImage(e: MouseEvent) {
		e.stopPropagation();
		if (post.images && currentImageIndex < post.images.length - 1) {
			currentImageIndex++;
			imageLoading = true;
		}
	}

	function prevImage(e: MouseEvent) {
		e.stopPropagation();
		if (currentImageIndex > 0) {
			currentImageIndex--;
			imageLoading = true;
		}
	}

	function formatContent(text: string): string {
		const lines = text.split('\n');
		return lines
			.map((line) => {
				return line.replace(/([@#][\w\uAC00-\uD7AF]+)/g, (match) => {
					if (match.startsWith('#')) {
						return `<span class="text-gray-500 hover:text-gray-700 cursor-pointer">${match}</span>`;
					}
					if (match.startsWith('@')) {
						return `<span class="font-semibold text-gray-900 hover:opacity-70 cursor-pointer">${match}</span>`;
					}
					return match;
				});
			})
			.join('<br/>');
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

	// 태그 편집 함수
	function startEditTags() {
		editTagIds =
			post.tags
				?.map((t) => availableTags.find((at) => at.name === t.name)?.id)
				.filter((id): id is number => id !== undefined) || [];
		editingTags = true;
	}

	function cancelEditTags() {
		editingTags = false;
	}

	function toggleEditTag(tagId: number) {
		if (editTagIds.includes(tagId)) {
			editTagIds = editTagIds.filter((id) => id !== tagId);
		} else {
			editTagIds = [...editTagIds, tagId];
		}
	}

	async function saveTags() {
		if (!onTagsUpdate) return;
		savingTags = true;
		try {
			await onTagsUpdate(post.id, editTagIds);
			editingTags = false;
		} finally {
			savingTags = false;
		}
	}

	// 삭제
	function handleDelete() {
		if (onDelete) {
			onDelete(post.id);
		}
	}

	// 재크롤링
	async function handleRecrawl() {
		if (isRecrawling || !onRecrawl) return;
		isRecrawling = true;
		try {
			await onRecrawl(post.id);
		} finally {
			isRecrawling = false;
		}
	}

	// 이미지를 프록시를 통해 base64로 변환
	async function loadImageAsBase64(url: string): Promise<string> {
		try {
			const proxyUrl = `/api/v1/instagram/proxy-image?url=${encodeURIComponent(url)}`;
			const response = await fetch(proxyUrl);
			if (!response.ok) throw new Error('Proxy fetch failed');
			const blob = await response.blob();
			return new Promise((resolve, reject) => {
				const reader = new FileReader();
				reader.onloadend = () => resolve(reader.result as string);
				reader.onerror = reject;
				reader.readAsDataURL(blob);
			});
		} catch {
			return url; // 실패 시 원본 URL 반환
		}
	}

	// 캡쳐 다운로드
	async function handleCapture() {
		if (!feedRef || isCapturing) return;
		isCapturing = true;

		// 캡처 제외 요소들을 숨기고 복원할 준비
		const excludeElements = feedRef.querySelectorAll('[data-capture-exclude]');
		const originalDisplays: string[] = [];
		excludeElements.forEach((el, i) => {
			const htmlEl = el as HTMLElement;
			originalDisplays[i] = htmlEl.style.display;
			htmlEl.style.display = 'none';
		});

		try {
			const dataUrl = await toPng(feedRef, {
				cacheBust: true,
				fetchRequestInit: {
					mode: 'cors',
					credentials: 'omit'
				},
			});

			const link = document.createElement('a');
			link.download = `${post.account}-${post.id}-${Date.now()}.png`;
			link.href = dataUrl;
			link.click();
		} catch (error) {
			console.error('캡쳐 실패:', error);
			// html-to-image 실패 시 대체 방법: 이미지를 먼저 교체하고 재시도
			try {
				const imgEl = feedRef?.querySelector('img') as HTMLImageElement | null;
				const originalSrc = imgEl?.src;

				if (imgEl && post.images?.[currentImageIndex]?.src) {
					const base64 = await loadImageAsBase64(post.images[currentImageIndex].src);
					if (base64.startsWith('data:')) {
						imgEl.src = base64;
					}
				}

				const dataUrl = await toPng(feedRef!, { cacheBust: true });

				if (imgEl && originalSrc) {
					imgEl.src = originalSrc;
				}

				const link = document.createElement('a');
				link.download = `${post.account}-${post.id}-${Date.now()}.png`;
				link.href = dataUrl;
				link.click();
			} catch (retryError) {
				console.error('캡쳐 재시도 실패:', retryError);
				alert('캡쳐에 실패했습니다. 이미지 로딩 문제일 수 있습니다.');
			}
		} finally {
			// 숨긴 요소들 복원
			excludeElements.forEach((el, i) => {
				(el as HTMLElement).style.display = originalDisplays[i];
			});
			isCapturing = false;
		}
	}
</script>

<article
	bind:this={feedRef}
	class="feed-card bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden"
	class:hover:shadow-md={!detailMode}
	class:transition-all={!detailMode}
	class:duration-300={!detailMode}
>
	<!-- Header -->
	<div class="flex items-center justify-between px-4 py-3">
		<div class="flex items-center gap-3">
			<div class="flex flex-col">
				<div class="flex items-center gap-2">
					<span class="font-semibold text-sm text-gray-900">@{post.account}</span>
					{#if post.post_type === 'SPONSORED' || (post.is_ad && !post.post_type)}
						<span class="px-1.5 py-0.5 text-xs bg-yellow-100 text-yellow-800 rounded">광고</span>
					{:else if post.post_type === 'SUGGESTED'}
						<span class="px-1.5 py-0.5 text-xs bg-violet-100 text-violet-800 rounded">추천</span>
					{/if}
				</div>
			</div>
		</div>
		{#if detailMode && onClose}
			<!-- 상세 모드: 닫기 버튼 -->
			<button
				onclick={onClose}
				class="p-2 hover:bg-gray-100 rounded-full transition-colors duration-200"
				aria-label="닫기"
			>
				<svg class="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M6 18L18 6M6 6l12 12"
					/>
				</svg>
			</button>
		{:else}
			<!-- 목록 모드: 상세 보기 버튼 -->
			<button
				onclick={handleClick}
				class="p-2 hover:bg-gray-100 rounded-full transition-colors duration-200"
				aria-label="상세 보기"
			>
				<svg class="w-5 h-5 text-gray-600" fill="currentColor" viewBox="0 0 20 20">
					<path
						d="M6 10a2 2 0 11-4 0 2 2 0 014 0zM12 10a2 2 0 11-4 0 2 2 0 014 0zM16 12a2 2 0 100-4 2 2 0 000 4z"
					/>
				</svg>
			</button>
		{/if}
	</div>

	<!-- Image (이미지가 있을 때만 표시) -->
	{#if post.images && post.images.length > 0}
		<div class="relative w-full aspect-square bg-gray-100 overflow-hidden">
			{#if imageLoading}
				<div
					class="absolute inset-0 bg-gradient-to-r from-gray-200 via-gray-100 to-gray-200 animate-pulse"
				></div>
			{/if}
			<img
				src={post.images[currentImageIndex].src}
				alt={post.images[currentImageIndex].alt || `${post.account}의 게시물`}
				class="w-full h-full object-cover transition-opacity duration-300"
				class:opacity-0={imageLoading}
				class:opacity-100={!imageLoading}
				onload={handleImageLoad}
			/>
			<!-- Image navigation -->
			{#if post.images.length > 1}
				<div class="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1">
					{#each post.images as _, idx}
						<div
							class="w-1.5 h-1.5 rounded-full transition-colors {idx === currentImageIndex
								? 'bg-white'
								: 'bg-white/50'}"
						></div>
					{/each}
				</div>
				{#if currentImageIndex > 0}
					<button
						onclick={prevImage}
						class="absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-white/80 hover:bg-white flex items-center justify-center shadow-lg transition-all"
						aria-label="이전 이미지"
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M15 19l-7-7 7-7"
							/>
						</svg>
					</button>
				{/if}
				{#if currentImageIndex < post.images.length - 1}
					<button
						onclick={nextImage}
						class="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-white/80 hover:bg-white flex items-center justify-center shadow-lg transition-all"
						aria-label="다음 이미지"
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M9 5l7 7-7 7"
							/>
						</svg>
					</button>
				{/if}
			{/if}
		</div>
	{/if}

	<!-- Content -->
	<div class="px-4 pb-4">
		{#if !detailMode}
			<!-- 목록 모드: 펼치기/접기 토글 -->
			<button
				onclick={toggleExpand}
				class="w-full flex items-center justify-between py-3 text-left group"
			>
				<span class="font-semibold text-sm text-gray-900 hover:opacity-70 transition-opacity">
					@{post.account}
				</span>
				<span class="text-gray-500 transition-transform duration-300 group-hover:text-gray-700">
					{#if isExpanded}
						<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M5 15l7-7 7 7"
							/>
						</svg>
					{:else}
						<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M19 9l-7 7-7-7"
							/>
						</svg>
					{/if}
				</span>
			</button>
		{:else}
			<!-- 상세 모드: 항상 표시 -->
			<div class="py-3"></div>
		{/if}

		<div
			class="overflow-hidden transition-all duration-300 ease-out"
			class:max-h-0={!isExpanded}
			class:opacity-0={!isExpanded}
			class:max-h-[2000px]={isExpanded}
			class:opacity-100={isExpanded}
		>
			<!-- 캡션 -->
			{#if post.caption}
				<div class="text-sm text-gray-700 leading-relaxed pb-3">
					{@html formatContent(post.caption)}
				</div>
			{/if}

			<!-- 상세 모드: 내부 태그 (AI 분석 트리거용, 접히는 섹션) -->
			{#if detailMode && availableTags.length > 0}
				<details class="py-3 border-t border-gray-100" data-capture-exclude>
					<summary class="cursor-pointer text-xs text-gray-400 hover:text-gray-600">
						내부 태그 (AI 분석 트리거용)
					</summary>
					<div class="mt-2">
						<div class="flex items-center gap-2 mb-2">
							{#if !editingTags}
								<button
									onclick={startEditTags}
									class="text-xs text-blue-600 hover:text-blue-800 underline"
								>
									편집
								</button>
							{/if}
						</div>
						{#if editingTags}
							<!-- 편집 모드 -->
							<div class="flex flex-wrap gap-2 mb-2">
								{#each availableTags as tag (tag.id)}
									<button
										onclick={() => toggleEditTag(tag.id)}
										class="px-2 py-1 text-xs rounded-full transition-colors border"
										style="background-color: {editTagIds.includes(tag.id)
											? tag.color
											: 'white'}; color: {editTagIds.includes(tag.id)
											? 'white'
											: tag.color}; border-color: {tag.color};"
									>
										{tag.display_name}
										{#if editTagIds.includes(tag.id)}
											<span class="ml-1">✓</span>
										{/if}
									</button>
								{/each}
							</div>
							<div class="flex gap-2">
								<button
									onclick={saveTags}
									disabled={savingTags}
									class="btn btn-primary btn-sm disabled:opacity-50"
								>
									{savingTags ? '저장 중...' : '저장'}
								</button>
								<button onclick={cancelEditTags} class="btn btn-secondary btn-sm"> 취소 </button>
							</div>
						{:else}
							<!-- 보기 모드 -->
							{#if post.tags && post.tags.length > 0}
								{#each post.tags as tag}
									<span
										class="inline-block px-2 py-0.5 text-xs rounded-full text-white mr-1"
										style="background-color: {tag.color};"
									>
										{tag.display_name}
									</span>
								{/each}
							{:else}
								<span class="text-gray-400 text-sm">태그 없음</span>
							{/if}
						{/if}
					</div>
				</details>
			{/if}

			<!-- 메타 정보 -->
			<div class="text-xs text-gray-400 pt-2 border-t border-gray-100">
				<div class="flex justify-between">
					<span>업로드: {post.display_time || formatDateTime(post.posted_at)}</span>
					<span>수집: {formatDateTime(post.collected_at)}</span>
				</div>
			</div>

			<!-- 상세 모드: 액션 버튼 -->
			{#if detailMode}
				<div class="flex gap-2 flex-wrap pt-3 border-t border-gray-100 mt-3" data-capture-exclude>
					{#if post.url}
						<a
							href={post.url}
							target="_blank"
							rel="noopener noreferrer"
							class="btn btn-primary btn-sm"
						>
							원본 보기
						</a>
						<button
							onclick={handleRecrawl}
							disabled={isRecrawling}
							class="btn btn-secondary btn-sm disabled:opacity-50"
							title="게시물 URL로 다시 크롤링"
						>
							{#if isRecrawling}
								<span class="inline-block animate-spin mr-1">&#8635;</span>
								재크롤링 중...
							{:else}
								&#8635; 재크롤링
							{/if}
						</button>
					{/if}
					<!-- 캡쳐 다운로드 버튼 -->
					<button
						onclick={handleCapture}
						disabled={isCapturing}
						class="btn btn-secondary btn-sm disabled:opacity-50"
						title="피드 캡쳐 다운로드"
					>
						{#if isCapturing}
							<span class="inline-block animate-spin mr-1">&#8635;</span>
							캡쳐 중...
						{:else}
							<svg class="w-4 h-4 inline-block mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
							</svg>
							캡쳐
						{/if}
					</button>
					<button onclick={handleDelete} class="btn btn-danger btn-sm"> 삭제 </button>
				</div>
			{/if}
		</div>
	</div>
</article>

<style>
	.feed-card {
		max-width: 468px;
	}
</style>
