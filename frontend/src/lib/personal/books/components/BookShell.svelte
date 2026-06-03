<script lang="ts">
	import { BookOpen, Highlighter, Inbox, Layers, ScanLine } from 'lucide-svelte';
	import { page } from '$app/stores';
	import UndoToast from './UndoToast.svelte';

	let { children } = $props<{ children: import('svelte').Snippet }>();

	const items = [
		{ href: '/personal/books', label: '전체 도서', short: '도서', icon: BookOpen },
		{ href: '/personal/books/organizer', label: '정리함', short: '정리함', icon: Inbox },
		{ href: '/personal/books/quick', label: '빠른 정리', short: '빠른정리', icon: Layers },
		{ href: '/personal/books/highlights', label: '하이라이트', short: '문장', icon: Highlighter },
		{ href: '/personal/books/scan', label: 'ISBN 등록', short: '등록', icon: ScanLine }
	];

	function active(pathname: string, href: string): boolean {
		return href === '/personal/books' ? pathname === href : pathname.startsWith(href);
	}
</script>

<div class="book-shell min-h-screen bg-background pb-16 text-foreground md:pb-0">
	<header class="sticky top-0 z-30 hidden border-b border-border bg-background/95 backdrop-blur md:block">
		<div class="mx-auto flex max-w-screen-2xl items-center gap-6 px-6 py-3">
			<a href="/personal/books" class="flex items-center gap-2 text-sm font-semibold">
				<BookOpen class="h-4 w-4 text-primary" />
				서재
			</a>
			<nav class="flex items-center gap-1">
				{#each items as item}
					<a
						href={item.href}
						class="rounded-md px-3 py-1.5 text-sm transition-colors {active($page.url.pathname, item.href) ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary/70 hover:text-foreground'}"
					>
						{item.label}
					</a>
				{/each}
			</nav>
			<a href="/personal/books/styleguide" class="ml-auto text-xs text-muted-foreground hover:text-foreground">styleguide</a>
		</div>
	</header>

	<main class="mx-auto w-full max-w-screen-2xl px-4 py-4 md:px-6 md:py-6">
		{@render children()}
	</main>

	<nav class="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-card/95 backdrop-blur md:hidden">
		<ul class="mx-auto flex max-w-screen-md items-stretch justify-around">
			{#each items as item}
				{@const Icon = item.icon}
				<li class="flex-1">
					<a href={item.href} class="flex flex-col items-center gap-0.5 py-2 text-[10px] {active($page.url.pathname, item.href) ? 'text-primary' : 'text-muted-foreground'}">
						<Icon class="h-5 w-5" />
						<span>{item.short}</span>
					</a>
				</li>
			{/each}
		</ul>
	</nav>

	<UndoToast />
</div>

