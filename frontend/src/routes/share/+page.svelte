<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { crawlApi } from '$lib/api';
	import { toast } from '$lib/stores/toast';

	let sharedUrl = $state('');
	let sharedText = $state('');
	let sharedTitle = $state('');
	let urlType = $state<'instagram' | 'event_form' | 'other'>('other');
	let processing = $state(true);
	let submitting = $state(false);
	let autoSubmitDone = $state(false);

	const URL_PATTERNS = {
		instagram: [/instagram\.com\/(p|reel|stories)\//, /instagr\.am\//],
		event_form: [
			/forms\.gle\//,
			/docs\.google\.com\/forms/,
			/naver\.me\//,
			/form\.naver\.com/,
			/bit\.ly\//,
			/surveymonkey\.com/,
			/typeform\.com/,
			/blog\.naver\.com/
		]
	};

	function detectUrlType(url: string): 'instagram' | 'event_form' | 'other' {
		for (const pattern of URL_PATTERNS.instagram) {
			if (pattern.test(url)) return 'instagram';
		}
		for (const pattern of URL_PATTERNS.event_form) {
			if (pattern.test(url)) return 'event_form';
		}
		return 'other';
	}

	function extractUrl(text: string): string | null {
		const urlRegex = /https?:\/\/[^\s]+/g;
		const matches = text.match(urlRegex);
		return matches ? matches[0] : null;
	}

	async function submitCrawlRequest() {
		if (!sharedUrl || submitting) return;

		submitting = true;
		try {
			const response = await crawlApi.createRequest({
				url: sharedUrl,
				auto_analyze: true,
				priority: 0
			});

			if (response.success) {
				toast.success(`크롤링 요청 등록 완료 (${response.url_type})`);
				// 1.5초 후 홈으로 이동
				setTimeout(() => {
					window.location.href = '/';
				}, 1500);
			} else {
				toast.error('크롤링 요청 등록 실패');
			}
		} catch (error) {
			const message = error instanceof Error ? error.message : '알 수 없는 오류';
			// Instagram URL인 경우 특별 처리
			if (message.includes('Instagram')) {
				toast.warning('Instagram URL은 Instagram 크롤러를 사용하세요.');
				// Instagram 페이지로 이동
				window.location.href = `/instagram/posts?shared_url=${encodeURIComponent(sharedUrl)}`;
				return;
			}
			toast.error(`오류: ${message}`);
		} finally {
			submitting = false;
		}
	}

	onMount(async () => {
		const params = $page.url.searchParams;
		sharedUrl = params.get('url') || '';
		sharedText = params.get('text') || '';
		sharedTitle = params.get('title') || '';

		// URL이 없으면 text에서 추출 시도
		if (!sharedUrl && sharedText) {
			sharedUrl = extractUrl(sharedText) || '';
		}

		if (sharedUrl) {
			urlType = detectUrlType(sharedUrl);

			// Instagram이면 바로 Instagram 페이지로 이동
			if (urlType === 'instagram') {
				window.location.href = `/instagram/posts?shared_url=${encodeURIComponent(sharedUrl)}`;
				return;
			}

			// 폼이나 기타 URL은 자동으로 크롤링 요청 생성
			if (urlType === 'event_form' || urlType === 'other') {
				await submitCrawlRequest();
				autoSubmitDone = true;
			}
		}

		processing = false;
	});

	// PWA standalone 모드에서는 goto()가 동작하지 않을 수 있으므로 window.location 사용
	function handleInstagram() {
		window.location.href = `/instagram/posts?shared_url=${encodeURIComponent(sharedUrl)}`;
	}

	function handleEventForm() {
		window.location.href = `/events?action=add&url=${encodeURIComponent(sharedUrl)}`;
	}

	function handleManualSubmit() {
		submitCrawlRequest();
	}

	function handleCancel() {
		window.location.href = '/';
	}
</script>

<svelte:head>
	<title>공유 받기 - Monitor Page</title>
</svelte:head>

<div class="p-4 max-w-lg mx-auto">
	<h1 class="text-2xl font-bold mb-6">공유 받은 URL</h1>

	{#if processing || submitting}
		<div class="flex items-center justify-center py-8">
			<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
			<span class="ml-3 text-gray-600">
				{#if submitting}
					크롤링 요청 등록 중...
				{:else}
					처리 중...
				{/if}
			</span>
		</div>
	{:else if !sharedUrl}
		<div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
			<p class="text-yellow-800">공유된 URL이 없습니다.</p>
			<button onclick={handleCancel} class="mt-4 px-4 py-2 bg-gray-200 rounded-lg hover:bg-gray-300">
				홈으로 돌아가기
			</button>
		</div>
	{:else if autoSubmitDone}
		<div class="bg-green-50 border border-green-200 rounded-lg p-4">
			<div class="flex items-center gap-2 mb-2">
				<span class="text-green-600 text-xl">✓</span>
				<p class="text-green-800 font-medium">크롤링 요청이 등록되었습니다.</p>
			</div>
			<p class="text-sm text-green-700">잠시 후 홈으로 이동합니다...</p>
		</div>
	{:else}
		<div class="space-y-4">
			<!-- 공유 받은 정보 표시 -->
			<div class="bg-gray-50 rounded-lg p-4 space-y-2">
				{#if sharedTitle}
					<div>
						<span class="text-sm text-gray-500">제목:</span>
						<p class="font-medium">{sharedTitle}</p>
					</div>
				{/if}
				<div>
					<span class="text-sm text-gray-500">URL:</span>
					<p class="font-mono text-sm break-all text-blue-600">{sharedUrl}</p>
				</div>
				{#if sharedText && sharedText !== sharedUrl}
					<div>
						<span class="text-sm text-gray-500">텍스트:</span>
						<p class="text-sm text-gray-700">{sharedText}</p>
					</div>
				{/if}
			</div>

			<!-- URL 타입 표시 -->
			<div class="flex items-center gap-2">
				<span class="text-sm text-gray-500">감지된 타입:</span>
				{#if urlType === 'instagram'}
					<span class="px-2 py-1 bg-pink-100 text-pink-800 rounded text-sm">Instagram</span>
				{:else if urlType === 'event_form'}
					<span class="px-2 py-1 bg-green-100 text-green-800 rounded text-sm">이벤트 폼</span>
				{:else}
					<span class="px-2 py-1 bg-gray-100 text-gray-800 rounded text-sm">기타</span>
				{/if}
			</div>

			<!-- 액션 버튼 -->
			<div class="space-y-3 pt-4">
				{#if urlType === 'instagram'}
					<button
						onclick={handleInstagram}
						class="w-full px-4 py-3 bg-gradient-to-r from-pink-500 to-purple-500 text-white rounded-lg hover:from-pink-600 hover:to-purple-600 font-medium"
					>
						Instagram 크롤링으로 이동
					</button>
				{:else}
					<button
						onclick={handleManualSubmit}
						disabled={submitting}
						class="w-full px-4 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 font-medium disabled:opacity-50 disabled:cursor-not-allowed"
					>
						{#if submitting}
							<span class="flex items-center justify-center gap-2">
								<span class="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></span>
								등록 중...
							</span>
						{:else}
							크롤링 요청 등록
						{/if}
					</button>
				{/if}

				<button
					onclick={handleEventForm}
					class="w-full px-4 py-3 bg-green-500 text-white rounded-lg hover:bg-green-600 font-medium"
				>
					직접 이벤트로 등록
				</button>

				<button
					onclick={handleCancel}
					class="w-full px-4 py-3 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
				>
					취소
				</button>
			</div>
		</div>
	{/if}
</div>
