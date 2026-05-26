<script lang="ts">
	import { page } from '$app/stores';
	import {
		navEntries,
		isNavGroup,
		isActive,
		getActiveGroupId,
		type NavEntry,
		type NavGroup,
		type NavSingleItem
	} from '$lib/navigation';
	import { iconMap } from '$lib/iconMap';
	import { authStore, isAdmin, isLoggedIn, isAuthLoading } from '$lib/stores/auth';
	import { hiddenItems, collapsedGroups } from '$lib/stores/sidebarPrefs';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';

	// Props
	let {
		collapsed = false,
		onToggleCollapse
	}: {
		collapsed: boolean;
		onToggleCollapse?: () => void;
	} = $props();

	let editMode = $state(false);

	// 현재 경로의 그룹이 접혀있으면 자동 펼침
	$effect(() => {
		const activeGroupId = getActiveGroupId(getNavigationCurrent($page.url));
		if (!activeGroupId) return;
		collapsedGroups.expand(activeGroupId);
	});

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
	function getVisibleEntries(entries: NavEntry[], admin: boolean): NavEntry[] {
		if (admin) {
			// 관리자: publicOnly 항목은 사이드바에서 숨김
			return entries
				.map((entry) => {
					if (isNavGroup(entry)) {
						return { ...entry, items: entry.items.filter((item) => !item.publicOnly) };
					}
					return entry;
				})
				.filter((entry) => {
					if (isNavGroup(entry)) return (entry as NavGroup).items.length > 0;
					return true;
				});
		}
		return entries
			.map((entry) => {
				if (isNavGroup(entry)) {
					return { ...entry, items: entry.items.filter((item) => item.public) };
				}
				return entry;
			})
			.filter((entry) => {
				if (isNavGroup(entry)) return entry.items.length > 0;
				return (entry as NavSingleItem).public;
			});
	}

	let visibleEntries = $state<NavEntry[]>(getVisibleEntries(navEntries, false));

	$effect(() => {
		const admin = $isAdmin;
		visibleEntries = getVisibleEntries(navEntries, admin);
	});

	function isHidden(id: string): boolean {
		return $hiddenItems.includes(id);
	}

	function isGroupCollapsed(groupId: string): boolean {
		return $collapsedGroups.includes(groupId);
	}

	function getNavigationCurrent(url: URL): string {
		return `${url.pathname}${url.search}`;
	}

	// NavGroup에서 활성 항목이 있는지 확인
	function hasActiveItem(group: NavGroup, current: string): boolean {
		return group.items.some((item) => isActive(item.href, current));
	}
</script>

<!-- 헤더 -->
<div class="px-2 py-2 border-b border-sidebar-border flex items-center {collapsed ? 'justify-center' : 'justify-end'}">
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
<nav class="flex-1 min-h-0 p-2 lg:p-4 overflow-y-auto space-y-0.5">
	{#each visibleEntries as entry}
		{#if isNavGroup(entry)}
			<!-- NavGroup: 아코디언 메뉴 -->
			{@const groupCollapsed = isGroupCollapsed(entry.id)}
			{@const currentRoute = getNavigationCurrent($page.url)}
			{@const groupActive = hasActiveItem(entry, currentRoute)}

			{#if !collapsed}
				<!-- 그룹 헤더 버튼 -->
				<button
					onclick={() => collapsedGroups.toggle(entry.id)}
					class="w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm font-semibold transition-colors
						{groupActive && groupCollapsed
						? 'text-sidebar-primary-foreground bg-sidebar-primary/20'
						: 'text-sidebar-foreground hover:bg-sidebar-accent'}"
				>
					<span class="flex items-center gap-2">
						<svelte:component this={iconMap[entry.icon]} size={18} />
						<span>{entry.label}</span>
					</span>
					<svg
						class="w-4 h-4 transition-transform text-sidebar-muted {groupCollapsed ? '-rotate-90' : ''}"
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

				<!-- 하위 아이템 목록 -->
				{#if !groupCollapsed}
					<ul class="mt-0.5 ml-3 pl-3 border-l border-sidebar-border/40 space-y-0.5 mb-1">
						{#each entry.items as item}
							<li>
								<a
									href={item.href}
									onclick={handleNavClick}
									class="flex items-center gap-3 px-3 py-1.5 rounded-lg transition-colors text-sm
										{isActive(item.href, currentRoute)
										? 'bg-sidebar-primary text-sidebar-primary-foreground'
										: 'text-sidebar-foreground hover:bg-sidebar-accent'}"
								>
									<span>{item.label}</span>
								</a>
							</li>
						{/each}
					</ul>
				{/if}
			{:else}
				<!-- 접힌 사이드바: 그룹 아이콘만 표시 -->
				<div class="flex flex-col items-center gap-1 my-1">
					<div
						class="flex items-center justify-center w-10 h-10 rounded-lg transition-colors
							{groupActive
							? 'bg-sidebar-primary/20 text-sidebar-primary'
							: 'text-sidebar-foreground hover:bg-sidebar-accent'}"
						title={entry.label}
					>
						<svelte:component this={iconMap[entry.icon]} size={20} />
					</div>
					<div class="border-t border-sidebar-border/30 w-6 my-1"></div>
				</div>
			{/if}
		{:else}
			<!-- 단일 메뉴 아이템 (대시보드 등) -->
			{@const hidden = isHidden(entry.id)}
			{@const currentRoute = getNavigationCurrent($page.url)}

			{#if editMode || !hidden}
				<div class="flex items-center group/item {hidden ? 'opacity-40' : ''}">
					<a
						href={entry.href}
						onclick={handleNavClick}
						class="flex-1 flex items-center gap-3 px-3 py-2 rounded-lg transition-colors
							{collapsed ? 'lg:justify-center lg:px-0' : ''}
							{isActive(entry.href, currentRoute)
							? 'bg-sidebar-primary text-sidebar-primary-foreground'
							: 'text-sidebar-foreground hover:bg-sidebar-accent'}"
						title={collapsed ? entry.label : ''}
					>
						<svelte:component this={iconMap[entry.icon]} size={20} />
						<span class={collapsed ? 'lg:hidden' : ''}>{entry.label}</span>
					</a>

					<!-- 편집 모드: 숨기기 토글 -->
					{#if editMode && !collapsed}
						<button
							onclick={() => hiddenItems.toggle(entry.id)}
							class="flex-shrink-0 p-1.5 rounded hover:bg-sidebar-accent transition-colors
								{hidden ? 'text-sidebar-muted/40' : 'text-sidebar-muted/70 hover:text-sidebar-foreground'}"
							title={hidden ? '메뉴에 표시' : '메뉴에서 숨기기'}
						>
							{#if hidden}
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21"
									/>
								</svg>
							{:else}
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
									/>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
									/>
								</svg>
							{/if}
						</button>
					{/if}
				</div>
			{/if}
		{/if}
	{/each}

	<!-- 메뉴 편집 버튼 -->
	{#if !collapsed}
		<div class="mt-4 pt-3 border-t border-sidebar-border/20">
			<button
				onclick={() => (editMode = !editMode)}
				class="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-sidebar-muted/50 hover:text-sidebar-muted transition-colors rounded-lg hover:bg-sidebar-accent/30"
			>
				{#if editMode}
					<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M5 13l4 4L19 7"
						/>
					</svg>
					<span>편집 완료</span>
				{:else}
					<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
						/>
					</svg>
					<span>메뉴 편집</span>
				{/if}
			</button>
		</div>
	{/if}
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
				<span
					class="inline-block mt-1 px-2 py-0.5 bg-success text-success-foreground text-xs rounded"
					>관리자</span
				>
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

	<!-- 다크 모드 토글 -->
	<div class="mt-3">
		<ThemeToggle {collapsed} />
	</div>

	<!-- API 문서 링크 -->
	<div class="mt-3 text-sidebar-muted text-sm {collapsed ? 'lg:hidden' : ''}">
		<a href="/docs" target="_blank" class="hover:text-sidebar-foreground">API 문서 &rarr;</a>
	</div>
</div>
