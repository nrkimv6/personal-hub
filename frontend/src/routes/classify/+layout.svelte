<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		LayoutDashboard,
		FolderSearch,
		Images,
		Copy,
		FolderTree,
		Settings
	} from 'lucide-svelte';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';
	import StatusBar from '$lib/components/classify/StatusBar.svelte';

	let { children }: { children: Snippet } = $props();

	const modules = [
		{ id: 'dashboard', label: '대시보드', href: '/classify/dashboard', icon: LayoutDashboard },
		{ id: 'scanner', label: '스캐너', href: '/classify/folders', icon: FolderSearch },
		{ id: 'images', label: '이미지', href: '/classify/images', icon: Images },
		{ id: 'duplicates', label: '중복/유사', href: '/classify/duplicates', icon: Copy },
		{ id: 'categories', label: '카테고리', href: '/classify/categories', icon: FolderTree },
		{ id: 'settings', label: '설정', href: '/classify/settings', icon: Settings }
	];
</script>

<div class="flex min-h-screen flex-col bg-background text-foreground">
	<div class="mx-auto flex w-full max-w-[1600px] flex-1 flex-col">
		<TabbedPageLayout
			title="이미지 분류기"
			subtitle="대시보드, 스캐너, 이미지 리뷰, 규칙 화면을 같은 상단 계약으로 정렬합니다."
			primaryTabs={modules}
			primaryUrlBased
			density="compact"
			containerClass="flex-1 space-y-3 p-4 lg:p-6"
			contentClass="min-h-0"
		>
			{@render children()}
		</TabbedPageLayout>
	</div>

	<StatusBar />
</div>
