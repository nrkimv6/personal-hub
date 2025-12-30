<script lang="ts">
	import { page } from '$app/stores';
</script>

<div class="min-h-screen bg-gray-50">
	<!-- 서브 네비게이션 -->
	<div class="bg-white shadow-sm border-b border-gray-200">
		<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
			<nav class="flex space-x-8 h-12" aria-label="Tabs">
				<a
					href="/crawl/requests"
					class="inline-flex items-center px-1 border-b-2 text-sm font-medium {$page.url.pathname.startsWith('/crawl/requests')
						? 'border-blue-500 text-blue-600'
						: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
				>
					단건 요청
				</a>
				<a
					href="/crawl/schedules"
					class="inline-flex items-center px-1 border-b-2 text-sm font-medium {$page.url.pathname.startsWith('/crawl/schedules')
						? 'border-blue-500 text-blue-600'
						: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
				>
					스케줄
				</a>
			</nav>
		</div>
	</div>

	<!-- 콘텐츠 -->
	<slot />
</div>
