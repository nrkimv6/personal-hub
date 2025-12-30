<script lang="ts">
	import { page } from '$app/stores';
	import { navGroups, isActive, getActiveGroupId, type NavGroup } from '$lib/navigation';
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
		const activeGroupId = getActiveGroupId($page.url.pathname);
		if (activeGroupId && collapsedGroups[activeGroupId]) {
			collapsedGroups[activeGroupId] = false;
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
	function getVisibleGroups(groups: NavGroup[], admin: boolean): NavGroup[] {
		// 관리자면 모든 메뉴 표시
		if (admin) {
			return groups;
		}
		// 비관리자: public 아이템만 보여줌
		return groups
			.map((group) => ({
				...group,
				items: group.items.filter((item) => item.public)
			}))
			.filter((group) => group.items.length > 0);
	}

	// 필터링된 네비게이션 그룹 - Svelte 5 runes와 스토어 호환을 위해 $effect 사용
	// 초기값: public 아이템만 (운영 모드 기본값)
	let visibleGroups = $state<NavGroup[]>(getVisibleGroups(navGroups, false));

	$effect(() => {
		const admin = $isAdmin;
		console.log('[Sidebar] Admin check:', { admin, willShowAll: admin });
		visibleGroups = getVisibleGroups(navGroups, admin);
	});
</script>

<!-- 헤더 -->
<div class="p-4 border-b border-gray-700 flex items-center justify-between">
	{#if !collapsed}
		<div>
			<h1 class="text-xl font-bold">모니터링</h1>
			<p class="text-gray-400 text-sm mt-1">v1.0.0</p>
		</div>
	{/if}
	<!-- 데스크톱 접기 버튼 -->
	{#if onToggleCollapse}
		<button
			onclick={onToggleCollapse}
			class="hidden lg:flex items-center justify-center w-8 h-8 rounded-lg hover:bg-gray-700 transition-colors"
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
	{#each visibleGroups as group}
		<div class="mb-2">
			<!-- 그룹 헤더 -->
			{#if !collapsed}
				<button
					onclick={() => toggleGroup(group.id)}
					class="w-full flex items-center justify-between px-3 py-2 text-sm font-semibold text-gray-400 hover:text-white rounded-lg hover:bg-gray-700/50 transition-colors"
				>
					<span class="flex items-center gap-2">
						<span>{group.icon}</span>
						<span>{group.label}</span>
					</span>
					<svg
						class="w-4 h-4 transition-transform {collapsedGroups[group.id] ? '-rotate-90' : ''}"
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
			{#if !collapsedGroups[group.id]}
				<ul class="space-y-1 {collapsed ? '' : 'mt-1 ml-2'}">
					{#each group.items as item}
						<li>
							<a
								href={item.href}
								onclick={handleNavClick}
								class="flex items-center gap-3 px-3 py-2 rounded-lg transition-colors
									{collapsed ? 'lg:justify-center lg:px-0' : ''}
									{isActive(item.href, $page.url.pathname)
									? 'bg-blue-600 text-white'
									: 'text-gray-300 hover:bg-gray-700'}"
								title={collapsed ? item.label : ''}
							>
								<span class="text-lg">{item.icon}</span>
								<span class={collapsed ? 'lg:hidden' : ''}>{item.label}</span>
							</a>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/each}
</nav>

<!-- 푸터 (인증 상태 + API 문서 링크) -->
<div class="p-4 border-t border-gray-700 {collapsed ? 'lg:hidden' : ''}">
	<!-- 인증 상태 -->
	{#if $isAuthLoading}
		<div class="text-gray-400 text-sm mb-3">로딩 중...</div>
	{:else if $isLoggedIn}
		<div class="mb-3">
			<div class="text-gray-300 text-sm truncate" title={$authStore.email ?? ''}>
				{$authStore.email}
			</div>
			{#if $isAdmin}
				<span class="inline-block mt-1 px-2 py-0.5 bg-green-600 text-white text-xs rounded">관리자</span>
			{/if}
		</div>
		<button
			onclick={handleLogout}
			class="w-full px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm rounded-lg transition-colors"
		>
			로그아웃
		</button>
	{:else}
		<!-- 관리자 로그인 (눈에 띄지 않는 작은 링크) -->
		<button
			onclick={handleLogin}
			class="text-gray-500 hover:text-gray-400 text-xs transition-colors"
		>
			관리자
		</button>
	{/if}

	<!-- API 문서 링크 -->
	<div class="mt-3 text-gray-400 text-sm">
		<a href="/docs" target="_blank" class="hover:text-white">API 문서 &rarr;</a>
	</div>
</div>
