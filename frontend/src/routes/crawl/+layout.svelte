<script lang="ts">
	import { page } from '$app/stores';
</script>

<div class="min-h-screen bg-background">
	<!-- 서브 네비게이션 -->
	<div class="bg-white shadow-sm border-b border-border">
		<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
			<nav class="flex space-x-8 h-12" aria-label="Tabs">
				<a
					href="/crawl/requests"
					class="inline-flex items-center px-1 border-b-2 text-sm font-medium {$page.url.pathname.startsWith('/crawl/requests')
						? 'border-blue-500 text-primary'
						: 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'}"
				>
					단건 요청
				</a>
				<a
					href="/crawl/schedules"
					class="inline-flex items-center px-1 border-b-2 text-sm font-medium {$page.url.pathname.startsWith('/crawl/schedules')
						? 'border-blue-500 text-primary'
						: 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'}"
				>
					스케줄
				</a>
			</nav>
		</div>
	</div>

	<!-- 콘텐츠 -->
	<slot />
</div>
