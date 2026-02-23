<script lang="ts">
	import { page } from '$app/stores';
	import {
		LayoutDashboard,
		Files,
		CheckSquare,
		FolderOutput,
		ListFilter,
		Settings,
		Menu,
		X,
		FolderSearch,
		BookOpen
	} from 'lucide-svelte';

	const modules = [
		{ id: 'dashboard', label: '대시보드', path: '/organize/dashboard', icon: LayoutDashboard },
		{ id: 'files', label: '파일 목록', path: '/organize/files', icon: Files },
		{ id: 'review', label: '분류 리뷰', path: '/organize/review', icon: CheckSquare },
		{ id: 'move', label: '이동', path: '/organize/move', icon: FolderOutput },
		{ id: 'rules', label: '규칙', path: '/organize/rules', icon: ListFilter },
		{ id: 'settings', label: '설정', path: '/organize/settings', icon: Settings },
		{ id: 'obsidian', label: '옵시디언', path: '/organize/obsidian', icon: BookOpen }
	];

	let mobileMenuOpen = $state(false);

	function isActive(path: string): boolean {
		return $page.url.pathname.startsWith(path);
	}
</script>

<div class="flex min-h-screen flex-col bg-background text-foreground">
	<!-- Top Navigation Bar -->
	<header class="sticky top-0 z-30 border-b border-border bg-card/80 backdrop-blur-xl">
		<div class="flex items-center justify-between px-4 py-2 lg:px-6">
			<div class="flex items-center gap-3">
				<div class="flex size-8 items-center justify-center rounded-lg bg-primary">
					<FolderSearch class="size-4 text-primary-foreground" />
				</div>
				<h1 class="text-base font-semibold text-foreground">파일 정리기</h1>
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
</div>
