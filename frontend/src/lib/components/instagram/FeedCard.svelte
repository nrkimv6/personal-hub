<script lang="ts">
	import { toPng } from 'html-to-image';
	import type { InstagramPost, InstagramTag } from '$lib/types';
	import { instagramApi } from '$lib/api';

	interface Props {
		post: InstagramPost;
		// 목록 모드용
		onOpenDetail?: (post: InstagramPost) => void;
		// 상세 모드용
		detailMode?: boolean;
		onClose?: () => void;
		onDelete?: (id: number) => void;
		onRecrawl?: (id: number) => void;
		onRequestLlmAnalysis?: (id: number) => Promise<void>;
		availableTags?: InstagramTag[];
		onTagsUpdate?: (postId: number, tagIds: number[]) => void;
		onLlmUpdate?: (updatedPost: InstagramPost) => void;
	}

	let {
		post,
		onOpenDetail,
		detailMode = false,
		onClose,
		onDelete,
		onRecrawl,
		onRequestLlmAnalysis,
		availableTags = [],
		onTagsUpdate,
		onLlmUpdate
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

	// LLM 분석 요청 상태
	let isRequestingLlm = $state(false);

	// LLM 편집 상태
	let editingLlm = $state(false);
	let savingLlm = $state(false);
	let llmForm = $state({
		llm_tag: '',
		llm_event_start: '',
		llm_event_end: '',
		llm_announcement_date: '',
		llm_prizes: '',  // 줄바꿈으로 구분
		llm_winner_count: '',
		llm_purchase_required: '',
		llm_organizer: '',
		llm_summary: '',
		llm_location_venue: '',
		llm_location_address: ''
	});

	const llmTagOptions = ['이벤트', '팝업', '홍보대사', '리그램', '기타'];
	const llmPurchaseOptions = [
		{ value: '', label: '선택안함' },
		{ value: '아니오', label: '불필요' },
		{ value: '예_부분', label: '부분 필요' },
		{ value: '예_전부', label: '전체 필요' }
	];

	function startEditLlm() {
		llmForm = {
			llm_tag: post.llm_tag || '',
			llm_event_start: post.llm_event_start || '',
			llm_event_end: post.llm_event_end || '',
			llm_announcement_date: post.llm_announcement_date || '',
			llm_prizes: post.llm_prizes?.join('\n') || '',
			llm_winner_count: post.llm_winner_count?.toString() || '',
			llm_purchase_required: post.llm_purchase_required || '',
			llm_organizer: post.llm_organizer || '',
			llm_summary: post.llm_summary || '',
			llm_location_venue: (post.llm_location as { venue_name?: string })?.venue_name || '',
			llm_location_address: (post.llm_location as { address?: string })?.address || ''
		};
		editingLlm = true;
	}

	function cancelEditLlm() {
		editingLlm = false;
	}

	async function saveLlm() {
		savingLlm = true;
		try {
			const data: Record<string, unknown> = {};

			// 변경된 필드만 전송
			if (llmForm.llm_tag) data.llm_tag = llmForm.llm_tag;
			data.llm_event_start = llmForm.llm_event_start || '';
			data.llm_event_end = llmForm.llm_event_end || '';
			data.llm_announcement_date = llmForm.llm_announcement_date || '';

			// 경품: 줄바꿈으로 분리하여 배열로
			const prizes = llmForm.llm_prizes.split('\n').map(s => s.trim()).filter(Boolean);
			data.llm_prizes = prizes;

			// 당첨자 수: 숫자로 변환
			data.llm_winner_count = llmForm.llm_winner_count ? parseInt(llmForm.llm_winner_count) : 0;

			data.llm_purchase_required = llmForm.llm_purchase_required || '';
			data.llm_organizer = llmForm.llm_organizer || '';
			data.llm_summary = llmForm.llm_summary || '';

			// 위치 정보
			if (llmForm.llm_location_venue || llmForm.llm_location_address) {
				data.llm_location = {
					venue_name: llmForm.llm_location_venue || '',
					address: llmForm.llm_location_address || ''
				};
			} else {
				data.llm_location = { venue_name: '', address: '' };
			}

			const updated = await instagramApi.updateLlmClassification(post.id, data as Parameters<typeof instagramApi.updateLlmClassification>[1]);

			// 부모에게 업데이트 알림
			if (onLlmUpdate) {
				onLlmUpdate(updated);
			}

			editingLlm = false;
		} catch (e) {
			console.error('LLM 분류 저장 실패:', e);
			alert('저장에 실패했습니다: ' + (e instanceof Error ? e.message : '알 수 없는 오류'));
		} finally {
			savingLlm = false;
		}
	}

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

	// LLM 분석 요청
	async function handleRequestLlmAnalysis() {
		if (!onRequestLlmAnalysis || isRequestingLlm) return;
		isRequestingLlm = true;
		try {
			await onRequestLlmAnalysis(post.id);
		} finally {
			isRequestingLlm = false;
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
		try {
			const dataUrl = await toPng(feedRef, {
				cacheBust: true,
				fetchRequestInit: {
					mode: 'cors',
					credentials: 'omit'
				},
				filter: (node) => {
					// 스크립트나 불필요한 요소 제외
					if (node instanceof Element) {
						const tagName = node.tagName?.toLowerCase();
						return tagName !== 'script' && tagName !== 'noscript';
					}
					return true;
				},
			});

			// 이미지가 base64로 이미 변환되어 있지 않으면, DOM을 직접 수정 후 재시도
			// html-to-image는 외부 이미지도 자동으로 fetch하여 인라인화 시도함
			const link = document.createElement('a');
			link.download = `${post.account}-${post.id}-${Date.now()}.png`;
			link.href = dataUrl;
			link.click();
		} catch (error) {
			console.error('캡쳐 실패:', error);
			// html-to-image 실패 시 대체 방법: 이미지를 먼저 교체하고 재시도
			try {
				// 원본 이미지 src 백업
				const imgEl = feedRef?.querySelector('img') as HTMLImageElement | null;
				const originalSrc = imgEl?.src;

				// base64로 이미지 교체
				if (imgEl && post.images?.[currentImageIndex]?.src) {
					const base64 = await loadImageAsBase64(post.images[currentImageIndex].src);
					if (base64.startsWith('data:')) {
						imgEl.src = base64;
					}
				}

				// 재시도
				const dataUrl = await toPng(feedRef!, { cacheBust: true });

				// 원본 복원
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
			<div
				class="w-10 h-10 rounded-full bg-gradient-to-br from-purple-500 via-pink-500 to-orange-400 p-[2px]"
			>
				<div class="w-full h-full rounded-full bg-white flex items-center justify-center">
					<span class="text-sm font-bold text-gray-700">
						{post.account.charAt(0).toUpperCase()}
					</span>
				</div>
			</div>
			<div class="flex flex-col">
				<div class="flex items-center gap-2">
					<span class="font-semibold text-sm text-gray-900">@{post.account}</span>
					{#if post.post_type === 'SPONSORED' || (post.is_ad && !post.post_type)}
						<span class="px-1.5 py-0.5 text-xs bg-yellow-100 text-yellow-800 rounded">광고</span>
					{:else if post.post_type === 'SUGGESTED'}
						<span class="px-1.5 py-0.5 text-xs bg-violet-100 text-violet-800 rounded">추천</span>
					{/if}
				</div>
				{#if post.llm_status}
					<div class="flex flex-wrap gap-1 mt-0.5">
						{#if post.llm_status === 'completed' && post.llm_tag}
							<span
								class="px-1.5 py-0.5 text-xs rounded-full bg-purple-100 text-purple-700"
								title="AI 분류"
							>
								{post.llm_tag}
							</span>
						{:else if post.llm_status === 'pending' || post.llm_status === 'processing'}
							<span
								class="px-1.5 py-0.5 text-xs rounded-full bg-gray-100 text-gray-500 animate-pulse"
								title="AI 분석 중"
							>
								AI
							</span>
						{/if}
					</div>
				{/if}
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

	<!-- Image -->
	<div class="relative w-full aspect-square bg-gray-100 overflow-hidden">
		{#if imageLoading}
			<div
				class="absolute inset-0 bg-gradient-to-r from-gray-200 via-gray-100 to-gray-200 animate-pulse"
			></div>
		{/if}
		{#if post.images && post.images.length > 0}
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
		{:else}
			<div class="absolute inset-0 flex items-center justify-center">
				<span class="text-gray-400 text-4xl">?</span>
			</div>
		{/if}
	</div>

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
				<details class="py-3 border-t border-gray-100">
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

			<!-- 상세 모드: LLM 분류 결과 -->
			{#if detailMode}
				<div
					class="py-3 border-t border-gray-100 bg-gradient-to-r from-purple-50 to-blue-50 rounded-lg px-3 my-2"
				>
					<div class="flex items-center justify-between mb-2">
						<h4 class="font-semibold text-sm text-gray-900 flex items-center gap-2">
							<svg
								class="w-4 h-4 text-purple-600"
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
							AI 분류
						</h4>
						<div class="flex items-center gap-2">
							{#if !editingLlm}
								<button
									onclick={startEditLlm}
									class="text-xs text-purple-600 hover:text-purple-800 underline"
								>
									수정
								</button>
							{/if}
							{#if post.llm_status}
								<span
									class="px-2 py-0.5 text-xs rounded-full {post.llm_status === 'completed'
										? 'bg-green-100 text-green-700'
										: post.llm_status === 'processing'
											? 'bg-yellow-100 text-yellow-700'
											: post.llm_status === 'pending'
												? 'bg-gray-100 text-gray-700'
												: 'bg-red-100 text-red-700'}"
								>
									{post.llm_status === 'completed'
										? '완료'
										: post.llm_status === 'processing'
											? '분석 중'
											: post.llm_status === 'pending'
												? '대기'
												: '실패'}
								</span>
							{/if}
						</div>
					</div>

					{#if editingLlm}
						<!-- 편집 모드 -->
						<div class="space-y-3 text-xs">
							<!-- 분류 -->
							<div class="flex items-center gap-2">
								<label class="text-gray-500 w-14 shrink-0">분류:</label>
								<div class="flex flex-wrap gap-1">
									{#each llmTagOptions as tag}
										<button
											type="button"
											onclick={() => llmForm.llm_tag = tag}
											class="px-2 py-1 rounded-full text-xs transition-colors {llmForm.llm_tag === tag
												? 'bg-purple-600 text-white'
												: 'bg-gray-200 text-gray-700 hover:bg-gray-300'}"
										>
											{tag}
										</button>
									{/each}
								</div>
							</div>
							<!-- 기간 -->
							<div class="flex items-center gap-2">
								<label class="text-gray-500 w-14 shrink-0">기간:</label>
								<input type="date" bind:value={llmForm.llm_event_start} class="px-2 py-1 border rounded text-xs" />
								<span>~</span>
								<input type="date" bind:value={llmForm.llm_event_end} class="px-2 py-1 border rounded text-xs" />
							</div>
							<!-- 발표일 -->
							<div class="flex items-center gap-2">
								<label class="text-gray-500 w-14 shrink-0">발표일:</label>
								<input type="date" bind:value={llmForm.llm_announcement_date} class="px-2 py-1 border rounded text-xs" />
							</div>
							<!-- 주최 -->
							<div class="flex items-center gap-2">
								<label class="text-gray-500 w-14 shrink-0">주최:</label>
								<input type="text" bind:value={llmForm.llm_organizer} placeholder="주최사/브랜드" class="flex-1 px-2 py-1 border rounded text-xs" />
							</div>
							<!-- 구매조건 -->
							<div class="flex items-center gap-2">
								<label class="text-gray-500 w-14 shrink-0">구매:</label>
								<select bind:value={llmForm.llm_purchase_required} class="px-2 py-1 border rounded text-xs">
									{#each llmPurchaseOptions as opt}
										<option value={opt.value}>{opt.label}</option>
									{/each}
								</select>
							</div>
							<!-- 당첨자 -->
							<div class="flex items-center gap-2">
								<label class="text-gray-500 w-14 shrink-0">당첨자:</label>
								<input type="number" bind:value={llmForm.llm_winner_count} placeholder="0" min="0" class="w-20 px-2 py-1 border rounded text-xs" />
								<span class="text-gray-500">명</span>
							</div>
							<!-- 경품 -->
							<div class="flex items-start gap-2">
								<label class="text-gray-500 w-14 shrink-0 pt-1">경품:</label>
								<textarea bind:value={llmForm.llm_prizes} placeholder="줄바꿈으로 구분" rows="2" class="flex-1 px-2 py-1 border rounded text-xs resize-none"></textarea>
							</div>
							<!-- 요약 -->
							<div class="flex items-start gap-2">
								<label class="text-gray-500 w-14 shrink-0 pt-1">요약:</label>
								<textarea bind:value={llmForm.llm_summary} placeholder="이벤트 요약" rows="2" class="flex-1 px-2 py-1 border rounded text-xs resize-none"></textarea>
							</div>
							<!-- 위치 (팝업) -->
							<details class="group">
								<summary class="text-gray-400 text-xs cursor-pointer">위치 정보 (팝업용)</summary>
								<div class="mt-2 space-y-2 pl-4">
									<div class="flex items-center gap-2">
										<label class="text-gray-500 w-14 shrink-0">장소명:</label>
										<input type="text" bind:value={llmForm.llm_location_venue} placeholder="팝업스토어명" class="flex-1 px-2 py-1 border rounded text-xs" />
									</div>
									<div class="flex items-center gap-2">
										<label class="text-gray-500 w-14 shrink-0">주소:</label>
										<input type="text" bind:value={llmForm.llm_location_address} placeholder="주소" class="flex-1 px-2 py-1 border rounded text-xs" />
									</div>
								</div>
							</details>
							<!-- 버튼 -->
							<div class="flex gap-2 pt-2">
								<button
									onclick={saveLlm}
									disabled={savingLlm}
									class="btn btn-primary btn-sm disabled:opacity-50"
								>
									{savingLlm ? '저장 중...' : '저장'}
								</button>
								<button onclick={cancelEditLlm} class="btn btn-secondary btn-sm">취소</button>
							</div>
						</div>
					{:else if post.llm_status === 'completed'}
						<!-- 보기 모드 -->
						<div class="space-y-1.5 text-xs">
							{#if post.llm_tag}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-14">분류:</span>
									<span
										class="px-2 py-0.5 font-medium rounded-full {post.llm_tag === '이벤트'
											? 'bg-purple-100 text-purple-700'
											: post.llm_tag === '팝업'
												? 'bg-blue-100 text-blue-700'
												: post.llm_tag === '홍보대사'
													? 'bg-pink-100 text-pink-700'
													: 'bg-gray-100 text-gray-700'}">{post.llm_tag}</span
									>
								</div>
							{/if}
							{#if post.llm_organizer}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-14">주최:</span>
									<span class="text-gray-900">{post.llm_organizer}</span>
								</div>
							{/if}
							{#if post.llm_event_start || post.llm_event_end}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-14">기간:</span>
									<span class="text-gray-900"
										>{post.llm_event_start || '?'} ~ {post.llm_event_end || '?'}</span
									>
								</div>
							{/if}
							{#if post.llm_announcement_date}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-14">발표일:</span>
									<span class="text-gray-900">{post.llm_announcement_date}</span>
								</div>
							{/if}
							{#if post.llm_purchase_required}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-14">구매:</span>
									<span
										class="px-1.5 py-0.5 rounded {post.llm_purchase_required === '아니오'
											? 'bg-green-100 text-green-700'
											: post.llm_purchase_required === '예_전부'
												? 'bg-red-100 text-red-700'
												: 'bg-yellow-100 text-yellow-700'}"
									>
										{post.llm_purchase_required === '아니오'
											? '불필요'
											: post.llm_purchase_required === '예_전부'
												? '전체 필요'
												: '부분 필요'}
									</span>
								</div>
							{/if}
							{#if post.llm_winner_count}
								<div class="flex items-center gap-2">
									<span class="text-gray-500 w-14">당첨자:</span>
									<span class="text-gray-900">{post.llm_winner_count}명</span>
								</div>
							{/if}
							{#if post.llm_prizes && post.llm_prizes.length > 0}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-14 shrink-0">경품:</span>
									<div class="flex flex-wrap gap-1">
										{#each post.llm_prizes as prize}
											<span class="px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded">{prize}</span>
										{/each}
									</div>
								</div>
							{/if}
							{#if post.llm_summary}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-14 shrink-0">요약:</span>
									<p class="text-gray-700">{post.llm_summary}</p>
								</div>
							{/if}
							{#if post.llm_urls && post.llm_urls.length > 0}
								<div class="flex items-start gap-2">
									<span class="text-gray-500 w-14 shrink-0">링크:</span>
									<div class="flex flex-col gap-0.5">
										{#each post.llm_urls as url}
											<a
												href={url}
												target="_blank"
												rel="noopener noreferrer"
												class="text-blue-600 hover:underline truncate max-w-[200px]">{url}</a
											>
										{/each}
									</div>
								</div>
							{/if}
						</div>
					{:else if post.llm_status === 'pending' || post.llm_status === 'processing'}
						<div class="flex items-center gap-2 text-xs text-gray-600">
							<div
								class="animate-spin w-3 h-3 border-2 border-purple-600 border-t-transparent rounded-full"
							></div>
							<span>분석 중...</span>
						</div>
					{:else}
						<p class="text-xs text-gray-500">분류 정보가 없습니다. "수정" 버튼으로 직접 입력할 수 있습니다.</p>
					{/if}
				</div>
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
				<div class="flex gap-2 flex-wrap pt-3 border-t border-gray-100 mt-3">
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
					<!-- AI 분석 요청 버튼 (미분석/실패 상태) -->
					{#if onRequestLlmAnalysis && (!post.llm_status || post.llm_status === 'failed')}
						<button
							onclick={handleRequestLlmAnalysis}
							disabled={isRequestingLlm}
							class="btn btn-sm bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50"
							title="AI로 게시물 분류 요청"
						>
							{#if isRequestingLlm}
								<span class="inline-block animate-spin mr-1">&#8635;</span>
								요청 중...
							{:else}
								🤖 AI 분석 요청
							{/if}
						</button>
					{/if}
					<!-- AI 재분석 버튼 (완료 상태) -->
					{#if onRequestLlmAnalysis && post.llm_status === 'completed'}
						<button
							onclick={handleRequestLlmAnalysis}
							disabled={isRequestingLlm}
							class="btn btn-sm bg-purple-100 text-purple-700 hover:bg-purple-200 disabled:opacity-50"
							title="AI로 게시물 다시 분류"
						>
							{#if isRequestingLlm}
								<span class="inline-block animate-spin mr-1">&#8635;</span>
								요청 중...
							{:else}
								🔄 AI 재분석
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
