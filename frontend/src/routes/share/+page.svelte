<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { crawlApi, collectApi } from '$lib/api';
	import { toast } from '$lib/stores/toast';

	let sharedUrl = $state('');
	let sharedText = $state('');
	let sharedTitle = $state('');
	let urlType = $state<'instagram' | 'event_form' | 'other'>('other');
	let processing = $state(true);
	let submitting = $state(false);
	let autoSubmitDone = $state(false);
	let shareCompleted = $state(false);  // 공유 완료 상태 (창 닫기 실패 시 표시)

	const URL_PATTERNS = {
		instagram: [/instagram\.com\/(p|reel|stories|reels)\//, /instagram\.com\/[^/]+\/?$/, /instagr\.am\//],
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

	// PWA 공유 창 닫기 시도
	function tryCloseWindow() {
		// window.close()는 스크립트로 열린 창만 닫을 수 있음
		// PWA share target의 경우 실패할 수 있으므로 완료 화면 표시
		try {
			window.close();
		} catch {
			// ignore
		}
		// 창이 안 닫히면 완료 상태 표시
		setTimeout(() => {
			shareCompleted = true;
			processing = false;
		}, 300);
	}

	// Instagram URL 자동 크롤링 요청
	async function submitInstagramCrawl() {
		if (!sharedUrl || submitting) return;

		submitting = true;
		try {
			// Instagram 계정 목록 가져오기
			const accounts = await collectApi.getAccounts();
			if (accounts.length === 0) {
				toast.error('등록된 Instagram 계정이 없습니다.');
				// 계정이 없으면 Instagram 페이지로 이동
				window.location.replace(`/collect?shared_url=${encodeURIComponent(sharedUrl)}`);
				return;
			}

			// 기본 계정 선택 (ID=4 우선, 없으면 첫 번째)
			const defaultAccount = accounts.find(a => a.id === 4);
			const accountId = defaultAccount?.id ?? accounts[0].id;

			// 크롤링 요청
			await collectApi.crawlByGenericUrl(sharedUrl, accountId);
			toast.success('Instagram 수집 요청 완료');

			// 창 닫기 시도
			tryCloseWindow();
		} catch (error) {
			const message = error instanceof Error ? error.message : '알 수 없는 오류';
			toast.error(`오류: ${message}`);
			// 실패 시 Instagram 페이지로 이동
			window.location.replace(`/instagram/posts?shared_url=${encodeURIComponent(sharedUrl)}`);
		} finally {
			submitting = false;
		}
	}

	async function submitCrawlRequest() {
		if (!sharedUrl || submitting) return;

		submitting = true;
		try {
			const response = await crawlApi.createUrlRequest({
				url: sharedUrl,
				auto_analyze: true,
				priority: 0
			});

			if (response.success) {
				toast.success(`크롤링 요청 등록 완료 (${response.url_type})`);
				// 창 닫기 시도
				tryCloseWindow();
			} else {
				toast.error('크롤링 요청 등록 실패');
			}
		} catch (error) {
			const message = error instanceof Error ? error.message : '알 수 없는 오류';
			// Instagram URL인 경우 특별 처리
			if (message.includes('Instagram')) {
				toast.warning('Instagram URL은 Instagram 크롤러를 사용하세요.');
				// Instagram 페이지로 이동 (replace로 히스토리에서 /share 제거)
				window.location.replace(`/collect?shared_url=${encodeURIComponent(sharedUrl)}`);
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

			// Instagram이면 바로 크롤링 요청 후 창 닫기
			if (urlType === 'instagram') {
				await submitInstagramCrawl();
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
	// replace()를 사용하여 /share 페이지를 히스토리에서 제거 (뒤로가기 시 건너뜀)
	function handleInstagram() {
		window.location.replace(`/collect?shared_url=${encodeURIComponent(sharedUrl)}`);
	}

	function handleEventForm() {
		window.location.replace(`/events?action=add&url=${encodeURIComponent(sharedUrl)}`);
	}

	function handleManualSubmit() {
		submitCrawlRequest();
	}

	function handleCancel() {
		window.location.replace('/');
	}

	function handleGoBack() {
		// 이전 앱으로 돌아가기 (히스토리 뒤로가기)
		window.history.back();
	}
</script>

<svelte:head>
	<title>공유 받기 - Monitor Page</title>
</svelte:head>

<div class="p-4 max-w-lg mx-auto">
	<h1 class="text-2xl font-bold mb-6">공유 받은 URL</h1>

	{#if shareCompleted}
		<!-- 공유 완료 (창 닫기 실패 시) -->
		<div class="bg-green-50 border border-green-200 rounded-lg p-6 text-center">
			<div class="text-green-600 text-4xl mb-3">✓</div>
			<p class="text-green-800 font-medium text-lg mb-2">수집 요청 완료</p>
			<p class="text-sm text-green-700 mb-4">이전 앱으로 돌아가세요</p>
			<button
				onclick={handleGoBack}
				class="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium"
			>
				뒤로가기
			</button>
		</div>
	{:else if processing || submitting}
		<div class="flex items-center justify-center py-8">
			<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
			<span class="ml-3 text-muted-foreground">
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
			<button onclick={handleCancel} class="mt-4 px-4 py-2 bg-secondary rounded-lg hover:bg-gray-300">
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
			<div class="bg-background rounded-lg p-4 space-y-2">
				{#if sharedTitle}
					<div>
						<span class="text-sm text-muted-foreground">제목:</span>
						<p class="font-medium">{sharedTitle}</p>
					</div>
				{/if}
				<div>
					<span class="text-sm text-muted-foreground">URL:</span>
					<p class="font-mono text-sm break-all text-blue-600">{sharedUrl}</p>
				</div>
				{#if sharedText && sharedText !== sharedUrl}
					<div>
						<span class="text-sm text-muted-foreground">텍스트:</span>
						<p class="text-sm text-foreground">{sharedText}</p>
					</div>
				{/if}
			</div>

			<!-- URL 타입 표시 -->
			<div class="flex items-center gap-2">
				<span class="text-sm text-muted-foreground">감지된 타입:</span>
				{#if urlType === 'instagram'}
					<span class="px-2 py-1 bg-pink-100 text-pink-800 rounded text-sm">Instagram</span>
				{:else if urlType === 'event_form'}
					<span class="px-2 py-1 bg-green-100 text-green-800 rounded text-sm">이벤트 폼</span>
				{:else}
					<span class="px-2 py-1 bg-muted text-foreground rounded text-sm">기타</span>
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
					class="w-full px-4 py-3 bg-secondary text-foreground rounded-lg hover:bg-gray-300"
				>
					취소
				</button>
			</div>
		</div>
	{/if}
</div>
