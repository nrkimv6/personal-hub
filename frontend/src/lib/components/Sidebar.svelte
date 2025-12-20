<script lang="ts">
	import { page } from '$app/stores';
	import { navGroups, isActive, getActiveGroupId, type NavGroup, type NavItem } from '$lib/navigation';

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
	{#each navGroups as group}
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

<!-- 푸터 -->
<div class="p-4 border-t border-gray-700 text-gray-400 text-sm {collapsed ? 'lg:hidden' : ''}">
	<a href="/docs" target="_blank" class="hover:text-white">API 문서 &rarr;</a>
</div>
