<script lang="ts">
	import type { InstagramPost } from '$lib/types';

	interface Props {
		post: InstagramPost;
		onOpenDetail?: (post: InstagramPost) => void;
	}

	let { post, onOpenDetail }: Props = $props();

	let isExpanded = $state(false);
	let imageLoading = $state(true);
	let currentImageIndex = $state(0);

	function toggleExpand() {
		isExpanded = !isExpanded;
	}

	function handleImageLoad() {
		imageLoading = false;
	}

	function handleClick() {
		if (onOpenDetail) {
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
		// Split by lines first, then format each line
		const lines = text.split('\n');
		return lines
			.map((line) => {
				// Format hashtags and mentions
				return line.replace(
					/([@#][\w\uAC00-\uD7AF]+)/g,
					(match) => {
						if (match.startsWith('#')) {
							return `<span class="text-gray-500 hover:text-gray-700 cursor-pointer">${match}</span>`;
						}
						if (match.startsWith('@')) {
							return `<span class="font-semibold text-gray-900 hover:opacity-70 cursor-pointer">${match}</span>`;
						}
						return match;
					}
				);
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
</script>

<article class="feed-card bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-all duration-300 overflow-hidden">
	<!-- Header -->
	<div class="flex items-center justify-between px-4 py-3">
		<div class="flex items-center gap-3">
			<div class="w-10 h-10 rounded-full bg-gradient-to-br from-purple-500 via-pink-500 to-orange-400 p-[2px]">
				<div class="w-full h-full rounded-full bg-white flex items-center justify-center">
					<span class="text-sm font-bold text-gray-700">
						{post.account.charAt(0).toUpperCase()}
					</span>
				</div>
			</div>
			<div class="flex flex-col">
				<div class="flex items-center gap-2">
					<span class="font-semibold text-sm text-gray-900">@{post.account}</span>
					{#if post.is_ad}
						<span class="px-1.5 py-0.5 text-xs bg-yellow-100 text-yellow-800 rounded">광고</span>
					{/if}
				</div>
				{#if post.tags && post.tags.length > 0}
					<div class="flex flex-wrap gap-1 mt-0.5">
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
			</div>
		</div>
		<button
			onclick={handleClick}
			class="p-2 hover:bg-gray-100 rounded-full transition-colors duration-200"
			aria-label="상세 보기"
		>
			<svg class="w-5 h-5 text-gray-600" fill="currentColor" viewBox="0 0 20 20">
				<path d="M6 10a2 2 0 11-4 0 2 2 0 014 0zM12 10a2 2 0 11-4 0 2 2 0 014 0zM16 12a2 2 0 100-4 2 2 0 000 4z" />
			</svg>
		</button>
	</div>

	<!-- Image -->
	<div class="relative w-full aspect-square bg-gray-100 overflow-hidden">
		{#if imageLoading}
			<div class="absolute inset-0 bg-gradient-to-r from-gray-200 via-gray-100 to-gray-200 animate-pulse"></div>
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
							class="w-1.5 h-1.5 rounded-full transition-colors"
							class:bg-white={idx === currentImageIndex}
							class:bg-white/50={idx !== currentImageIndex}
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
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
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
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
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
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
					</svg>
				{:else}
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
					</svg>
				{/if}
			</span>
		</button>

		<div
			class="overflow-hidden transition-all duration-300 ease-out"
			class:max-h-0={!isExpanded}
			class:opacity-0={!isExpanded}
			class:max-h-[1000px]={isExpanded}
			class:opacity-100={isExpanded}
		>
			{#if post.caption}
				<div class="text-sm text-gray-700 leading-relaxed pb-3">
					{@html formatContent(post.caption)}
				</div>
			{/if}
			<p class="text-xs text-gray-400 uppercase tracking-wide">
				{post.display_time || formatDateTime(post.posted_at)}
			</p>
		</div>
	</div>
</article>

<style>
	.feed-card {
		max-width: 468px;
	}
</style>
