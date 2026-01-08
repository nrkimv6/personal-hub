<script lang="ts">
	import { page } from '$app/stores';
	import { navEntries, isNavGroup, isActive, getActiveEntryId, type NavEntry, type NavGroup, type NavSingleItem } from '$lib/navigation';
	import { authStore, isAdmin, isLoggedIn, isAuthLoading } from '$lib/stores/auth';

	// Props
	let {
		collapsed = false,
		onToggleCollapse
	}: {
		collapsed: boolean;
		onToggleCollapse?: () => void;
	} = $props();

	// 그룹 접힘 상태 (그룹 ID -> 접힘 여부)
	let collapsedGroups = $state<Record<string, boolean>>({});

	// 현재 경로에 따라 활성 그룹 자동 펼침
	$effect(() => {
		const activeId = getActiveEntryId($page.url.pathname);
		if (activeId && collapsedGroups[activeId]) {
			collapsedGroups[activeId] = false;
		}
	});

	function toggleGroup(groupId: string) {
		collapsedGroups[groupId] = !collapsedGroups[groupId];
	}

	function handleNavClick() {
		// 모바일에서는 부모에서 처리
	}

	function handleLogin() {
		authStore.login();
	}

	async function handleLogout() {
		await authStore.logout();
	}

	// 앱 모드와 관리자 여부에 따라 메뉴 필터링
	// - 관리자: 모든 메뉴 표시
	// - 비관리자: public 아이템만 표시 (운영/개발 모드 상관없음)
	function getVisibleEntries(entries: NavEntry[], admin: boolean): NavEntry[] {
		// 관리자면 모든 메뉴 표시
		if (admin) {
			return entries;
		}
		// 비관리자: public 아이템만 보여줌
		return entries
			.map((entry) => {
				if (isNavGroup(entry)) {
					return {
						...entry,
						items: entry.items.filter((item) => item.public)
					};
				}
				return entry;
			})
			.filter((entry) => {
				if (isNavGroup(entry)) {
					return entry.items.length > 0;
				}
				return (entry as NavSingleItem).public;
			});
	}

	// 필터링된 네비게이션 - Svelte 5 runes와 스토어 호환을 위해 $effect 사용
	// 초기값: public 아이템만 (운영 모드 기본값)
	let visibleEntries = $state<NavEntry[]>(getVisibleEntries(navEntries, false));

	$effect(() => {
		const admin = $isAdmin;
		console.log('[Sidebar] Admin check:', { admin, willShowAll: admin });
		visibleEntries = getVisibleEntries(navEntries, admin);
	});
</script>

<!-- 헤더 -->
<div class="p-4 border-b border-sidebar-border flex items-center justify-between">
	{#if !collapsed}
		<div>
			<h1 class="text-xl font-bold text-sidebar-primary-foreground">모니터링</h1>
			<p class="text-sidebar-muted text-sm mt-1">v1.0.0</p>
		</div>
	{/if}
	<!-- 데스크톱 접기 버튼 -->
	{#if onToggleCollapse}
		<button
			onclick={onToggleCollapse}
			class="hidden lg:flex items-center justify-center w-8 h-8 rounded-lg hover:bg-sidebar-accent text-sidebar-foreground transition-colors"
			title={collapsed ? '메뉴 펼치기' : '메뉴 접기'}
		>
			<svg
				class="w-5 h-5 transition-transform {collapsed ? 'rotate-180' : ''}"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
				/>
			</svg>
		</button>
	{/if}
</div>

<!-- 네비게이션 -->
<nav class="flex-1 p-2 lg:p-4 overflow-y-auto">
	{#each visibleEntries as entry}
		<div class="mb-2">
			{#if isNavGroup(entry)}
				<!-- 그룹 메뉴 (하위 아이템이 2개 이상) -->
				<!-- 그룹 헤더 -->
				{#if !collapsed}
					<button
						onclick={() => toggleGroup(entry.id)}
						class="w-full flex items-center justify-between px-3 py-2 text-sm font-semibold text-sidebar-muted hover:text-sidebar-foreground rounded-lg hover:bg-sidebar-accent/50 transition-colors"
					>
						<span class="flex items-center gap-2">
							<span>{entry.icon}</span>
							<span>{entry.label}</span>
						</span>
						<svg
							class="w-4 h-4 transition-transform {collapsedGroups[entry.id] ? '-rotate-90' : ''}"
							fill="none"
							stroke="currentColor"
							viewBox="0 0 24 24"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M19 9l-7 7-7-7"
							/>
						</svg>
					</button>
				{/if}

				<!-- 그룹 아이템들 -->
				{#if !collapsedGroups[entry.id]}
					<ul class="space-y-1 {collapsed ? '' : 'mt-1 ml-2'}">
						{#each entry.items as item}
							<li>
								<a
									href={item.href}
									onclick={handleNavClick}
									class="flex items-center gap-3 px-3 py-2 rounded-lg transition-colors
										{collapsed ? 'lg:justify-center lg:px-0' : ''}
										{isActive(item.href, $page.url.pathname)
										? 'bg-sidebar-primary text-sidebar-primary-foreground'
										: 'text-sidebar-foreground hover:bg-sidebar-accent'}"
									title={collapsed ? item.label : ''}
								>
									<span class="text-lg">{item.icon}</span>
									<span class={collapsed ? 'lg:hidden' : ''}>{item.label}</span>
								</a>
							</li>
						{/each}
					</ul>
				{/if}
			{:else}
				<!-- 단일 메뉴 아이템 -->
				<a
					href={entry.href}
					onclick={handleNavClick}
					class="flex items-center gap-3 px-3 py-2 rounded-lg transition-colors
						{collapsed ? 'lg:justify-center lg:px-0' : ''}
						{isActive(entry.href, $page.url.pathname)
						? 'bg-sidebar-primary text-sidebar-primary-foreground'
						: 'text-sidebar-foreground hover:bg-sidebar-accent'}"
					title={collapsed ? entry.label : ''}
				>
					<span class="text-lg">{entry.icon}</span>
					<span class={collapsed ? 'lg:hidden' : ''}>{entry.label}</span>
				</a>
			{/if}
		</div>
	{/each}
</nav>

<!-- 푸터 (인증 상태 + API 문서 링크) -->
<div class="p-4 border-t border-sidebar-border {collapsed ? 'lg:hidden' : ''}">
	<!-- 인증 상태 -->
	{#if $isAuthLoading}
		<div class="text-sidebar-muted text-sm mb-3">로딩 중...</div>
	{:else if $isLoggedIn}
		<div class="mb-3">
			<div class="text-sidebar-foreground text-sm truncate" title={$authStore.email ?? ''}>
				{$authStore.email}
			</div>
			{#if $isAdmin}
				<span class="inline-block mt-1 px-2 py-0.5 bg-success text-success-foreground text-xs rounded">관리자</span>
			{/if}
		</div>
		<button
			onclick={handleLogout}
			class="w-full px-3 py-2 bg-sidebar-accent hover:bg-sidebar-accent/80 text-sidebar-foreground text-sm rounded-lg transition-colors"
		>
			로그아웃
		</button>
	{:else}
		<!-- 관리자 로그인 (눈에 띄지 않는 작은 링크) -->
		<button
			onclick={handleLogin}
			class="text-sidebar-muted hover:text-sidebar-foreground text-xs transition-colors"
		>
			관리자
		</button>
	{/if}

	<!-- API 문서 링크 -->
	<div class="mt-3 text-sidebar-muted text-sm">
		<a href="/docs" target="_blank" class="hover:text-sidebar-foreground">API 문서 &rarr;</a>
	</div>
</div>
