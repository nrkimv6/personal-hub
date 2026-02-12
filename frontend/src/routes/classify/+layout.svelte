<script lang="ts">
	import { page } from '$app/stores';

	const menuItems = [
		{ path: '/classify/dashboard', label: '대시보드', icon: '📊' },
		{ path: '/classify/duplicates', label: '중복 이미지', icon: '🔍', badge: 'Phase 1' },
		{ path: '/classify/folders', label: '폴더 매핑', icon: '📁', badge: 'Phase 2' },
		{ path: '/classify/categories', label: '카테고리', icon: '🏷️' },
		{ path: '/classify/similar', label: '유사 분류', icon: '🎯', badge: 'Phase 3' },
		{ path: '/classify/clusters', label: '시간 클러스터', icon: '⏰', badge: 'Phase 4' },
		{ path: '/classify/review', label: '검토', icon: '✅', badge: 'Phase 5' },
		{ path: '/classify/history', label: '이동 이력', icon: '📝', badge: 'Phase 6' },
		{ path: '/classify/rules', label: '분류 규칙', icon: '⚙️' },
		{ path: '/classify/settings', label: '설정', icon: '🔧' }
	];
</script>

<div class="flex h-screen bg-gray-100">
	<!-- 사이드바 -->
	<aside class="w-64 bg-white shadow-md">
		<div class="p-4 border-b">
			<h1 class="text-xl font-bold text-gray-800">🖼️ 이미지 분류</h1>
			<p class="text-sm text-gray-500 mt-1">30만 장 자동 정리</p>
		</div>

		<nav class="p-4 space-y-1">
			{#each menuItems as item}
				<a
					href={item.path}
					class="block px-4 py-2 rounded-md transition-colors {$page.url.pathname ===
					item.path
						? 'bg-blue-50 text-blue-700 font-medium'
						: 'text-gray-700 hover:bg-gray-50'}"
				>
					<span class="mr-2">{item.icon}</span>
					{item.label}
					{#if item.badge}
						<span class="ml-2 text-xs bg-blue-100 text-blue-600 px-2 py-0.5 rounded">
							{item.badge}
						</span>
					{/if}
				</a>
			{/each}
		</nav>

		<div class="p-4 border-t mt-auto">
			<p class="text-xs text-gray-500">이미지 분류 v0.1.0</p>
			<p class="text-xs text-gray-400 mt-1">CLI 모드 (추가 비용 $0)</p>
		</div>
	</aside>

	<!-- 메인 컨텐츠 -->
	<main class="flex-1 overflow-y-auto p-8">
		<slot />
	</main>
</div>

<style>
	:global(body) {
		margin: 0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
			sans-serif;
	}
</style>
