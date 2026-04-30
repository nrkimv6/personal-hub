<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		LayoutDashboard,
		Files,
		CheckSquare,
		FolderOutput,
		ListFilter,
		Settings,
		FolderSearch,
		BookOpen
	} from 'lucide-svelte';
	import TabbedPageLayout from '$lib/components/layout/TabbedPageLayout.svelte';

	let { children }: { children: Snippet } = $props();

	const modules = [
		{ id: 'dashboard', label: '대시보드', href: '/organize/dashboard', icon: LayoutDashboard },
		{ id: 'files', label: '파일 목록', href: '/organize/files', icon: Files },
		{ id: 'review', label: '분류 리뷰', href: '/organize/review', icon: CheckSquare },
		{ id: 'move', label: '이동', href: '/organize/move', icon: FolderOutput },
		{ id: 'rules', label: '규칙', href: '/organize/rules', icon: ListFilter },
		{ id: 'settings', label: '설정', href: '/organize/settings', icon: Settings },
		{ id: 'obsidian', label: '옵시디언', href: '/organize/obsidian', icon: BookOpen }
	];
</script>

<div class="min-h-screen bg-background text-foreground">
	<TabbedPageLayout
		title="파일 정리기"
		subtitle="상단 규약은 공통으로, 실제 도메인 작업은 각 화면 콘텐츠로 분리합니다."
		primaryTabs={modules}
		primaryUrlBased
		density="compact"
		containerClass="mx-auto max-w-[1600px] space-y-3 p-4 lg:p-6"
	>
		{@render children()}
	</TabbedPageLayout>
</div>
