<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { authStore } from '$lib/stores/auth';

	let status = $state<'loading' | 'success' | 'error'>('loading');
	let errorMessage = $state('');

	onMount(async () => {
		// URL에서 토큰 추출
		const token = $page.url.searchParams.get('token');
		const error = $page.url.searchParams.get('error');

		if (error) {
			status = 'error';
			errorMessage = error === 'access_denied' ? '로그인이 취소되었습니다' : `로그인 실패: ${error}`;
			return;
		}

		if (!token) {
			status = 'error';
			errorMessage = '인증 토큰이 없습니다';
			return;
		}

		// 토큰 저장 및 인증 상태 확인
		authStore.setToken(token);
		await authStore.checkAuth();

		status = 'success';

		// 홈으로 리디렉트
		setTimeout(() => {
			goto('/');
		}, 1000);
	});
</script>

<div class="min-h-screen flex items-center justify-center bg-gray-100">
	<div class="bg-white p-8 rounded-lg shadow-md max-w-md w-full text-center">
		{#if status === 'loading'}
			<div class="animate-spin w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
			<p class="text-gray-600">로그인 처리 중...</p>
		{:else if status === 'success'}
			<div class="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
				<svg class="w-6 h-6 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
				</svg>
			</div>
			<p class="text-green-600 font-medium">로그인 성공!</p>
			<p class="text-gray-500 text-sm mt-2">잠시 후 이동합니다...</p>
		{:else}
			<div class="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
				<svg class="w-6 h-6 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</div>
			<p class="text-red-600 font-medium">로그인 실패</p>
			<p class="text-gray-500 text-sm mt-2">{errorMessage}</p>
			<a href="/" class="inline-block mt-4 text-blue-500 hover:underline">홈으로 돌아가기</a>
		{/if}
	</div>
</div>
