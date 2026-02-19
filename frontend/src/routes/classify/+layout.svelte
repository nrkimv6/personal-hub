<script lang="ts">
	import { page } from '$app/stores';
	import StatusBar from '$lib/components/classify/StatusBar.svelte';
	import {
		LayoutDashboard,
		FolderSearch,
		Images,
		Copy,
		Brain,
		FolderTree,
		Clock,
		Search,
		Tags,
		ListChecks,
		Settings,
		Menu,
		X,
		CheckCircle2
	} from 'lucide-svelte';

	const modules = [
		{ id: 'dashboard', label: '대시보드', path: '/classify/dashboard', icon: LayoutDashboard },
		{ id: 'scanner', label: '스캐너', path: '/classify/folders', icon: FolderSearch },
		{ id: 'gallery', label: '갤러리', path: '/classify/gallery', icon: Images },
		{ id: 'duplicates', label: '중복', path: '/classify/duplicates', icon: Copy },
		{ id: 'ai', label: 'AI 분류', path: '/classify/ai', icon: Brain },
		{ id: 'categories', label: '카테고리', path: '/classify/categories', icon: FolderTree },
		{ id: 'clusters', label: '클러스터', path: '/classify/clusters', icon: Clock },
		{ id: 'similar', label: '유사도', path: '/classify/similar', icon: Search },
		{ id: 'tags', label: '태그', path: '/classify/tags', icon: Tags },
		{ id: 'rules', label: '규칙', path: '/classify/rules', icon: ListChecks },
		{ id: 'settings', label: '설정', path: '/classify/settings', icon: Settings },
		{ id: 'history', label: '이력', path: '/classify/history', icon: Clock },
		{ id: 'review', label: '검토', path: '/classify/review', icon: CheckCircle2 }
	];

	let mobileMenuOpen = $state(false);

	function isActive(path: string): boolean {
		return $page.url.pathname === path;
	}
</script>

<div class="flex min-h-screen flex-col bg-background text-foreground">
	<!-- Top Navigation Bar -->
	<header class="sticky top-0 z-50 border-b border-border bg-card/80 backdrop-blur-xl">
		<div class="flex items-center justify-between px-4 py-2 lg:px-6">
			<div class="flex items-center gap-3">
				<div class="flex size-8 items-center justify-center rounded-lg bg-primary">
					<Brain class="size-4 text-primary-foreground" />
				</div>
				<h1 class="text-base font-semibold text-foreground">이미지 분류기</h1>
			</div>

			<!-- Desktop nav -->
			<nav class="hidden items-center gap-0.5 lg:flex">
				{#each modules as mod}
					<a
						href={mod.path}
						class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-all {isActive(
							mod.path
						)
							? 'bg-primary/15 text-primary'
							: 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
					>
						<mod.icon class="size-3.5" />
						<span>{mod.label}</span>
					</a>
				{/each}
			</nav>

			<!-- Mobile hamburger -->
			<button
				class="flex items-center justify-center rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-foreground lg:hidden"
				onclick={() => (mobileMenuOpen = !mobileMenuOpen)}
				aria-label="Toggle menu"
			>
				{#if mobileMenuOpen}
					<X class="size-5" />
				{:else}
					<Menu class="size-5" />
				{/if}
			</button>
		</div>

		<!-- Mobile nav -->
		{#if mobileMenuOpen}
			<nav class="border-t border-border bg-card px-4 py-3 lg:hidden">
				<div class="grid grid-cols-3 gap-2">
					{#each modules as mod}
						<a
							href={mod.path}
							onclick={() => (mobileMenuOpen = false)}
							class="flex flex-col items-center gap-1 rounded-lg px-2 py-2.5 text-xs font-medium transition-all {isActive(
								mod.path
							)
								? 'bg-primary/15 text-primary'
								: 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
						>
							<mod.icon class="size-4" />
							<span>{mod.label}</span>
						</a>
					{/each}
				</div>
			</nav>
		{/if}
	</header>

	<!-- Main Content -->
	<main class="flex-1 overflow-y-auto">
		<div class="mx-auto w-full max-w-[1600px] p-4 lg:p-6">
			<slot />
		</div>
	</main>

	<!-- Status Bar -->
	<StatusBar />
</div>
