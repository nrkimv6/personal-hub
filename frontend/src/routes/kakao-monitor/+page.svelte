<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from '$lib/stores/toast';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import {
		getConfigs,
		createConfig,
		updateConfig,
		deleteConfig,
		toggleConfig,
		getKeywords,
		addKeyword,
		deleteKeyword,
		getPosts,
		getPost,
		deletePost,
		getStatus,
		triggerScan,
		getWindows,
		type KakaoConfig,
		type KakaoKeyword,
		type KakaoPost,
		type WorkerStatus,
		type WindowInfo,
	} from '$lib/api/kakaoMonitor';
	import { createPagePagination } from '$lib/utils/pagination.svelte';

	// ========== 탭 ==========
	type Tab = 'dashboard' | 'settings' | 'history' | 'windows';
	let activeTab = $state<Tab>('dashboard');

	// ========== 공통 상태 ==========
	let loading = $state(false);

	// ========== 대시보드 ==========
	let workerStatus = $state<WorkerStatus | null>(null);
	let configs = $state<KakaoConfig[]>([]);
	let recentPosts = $state<KakaoPost[]>([]);

	// ========== 감시 설정 ==========
	let showCreateModal = $state(false);
	let editingConfig = $state<KakaoConfig | null>(null);
	let configKeywords = $state<KakaoKeyword[]>([]);
	let newChatName = $state('');
	let newInterval = $state(3);
	let newKeywordsText = $state('');  // 쉼표 구분 키워드
	let addKwText = $state('');
	let addKwAction = $state('collect');

	// ========== 수집 이력 ==========
	const pager = createPagePagination(20);
	let posts = $state<KakaoPost[]>([]);
	let filterConfigId = $state<number | null>(null);
	let selectedPost = $state<KakaoPost | null>(null);
	let showPostModal = $state(false);

	// ========== 카카오 창 ==========
	let windows = $state<WindowInfo[]>([]);

	// ========== 초기 로드 ==========
	onMount(async () => {
		await loadDashboard();
	});

	async function loadDashboard() {
		loading = true;
		try {
			[workerStatus, configs] = await Promise.all([getStatus(), getConfigs()]);
			const resp = await getPosts({ limit: 5 });
			recentPosts = resp.items;
		} catch (e) {
			toast.error('데이터 로드 실패');
		} finally {
			loading = false;
		}
	}

	async function onTabChange(tab: Tab) {
		activeTab = tab;
		if (tab === 'dashboard') await loadDashboard();
		if (tab === 'settings') await loadConfigs();
		if (tab === 'history') await loadPosts();
		if (tab === 'windows') await loadWindows();
	}

	// ========== 감시 설정 ==========
	async function loadConfigs() {
		try {
			configs = await getConfigs();
		} catch (e) {
			toast.error('설정 로드 실패');
		}
	}

	async function handleCreateConfig() {
		if (!newChatName.trim()) { toast.error('채팅방 이름을 입력하세요'); return; }
		try {
			const keywords = newKeywordsText.split(',').map(s => s.trim()).filter(Boolean);
			await createConfig({ chat_name: newChatName.trim(), polling_interval_sec: newInterval, keywords });
			toast.success('감시 설정 추가 완료');
			showCreateModal = false;
			newChatName = '';
			newKeywordsText = '';
			newInterval = 3;
			await loadConfigs();
		} catch (e) {
			toast.error(e instanceof Error ? e.message : '추가 실패');
		}
	}

	async function handleToggle(config: KakaoConfig) {
		try {
			const updated = await toggleConfig(config.id);
			configs = configs.map(c => c.id === updated.id ? updated : c);
		} catch (e) {
			toast.error('토글 실패');
		}
	}

	async function handleDeleteConfig(id: number) {
		if (!confirm('설정과 모든 수집 이력을 삭제합니다. 계속하시겠습니까?')) return;
		try {
			await deleteConfig(id);
			toast.success('삭제 완료');
			await loadConfigs();
		} catch (e) {
			toast.error('삭제 실패');
		}
	}

	async function openEditConfig(config: KakaoConfig) {
		editingConfig = config;
		newChatName = config.chat_name;
		newInterval = config.polling_interval_sec;
		try {
			configKeywords = await getKeywords(config.id);
		} catch (e) {
			configKeywords = [];
		}
	}

	async function handleUpdateConfig() {
		if (!editingConfig) return;
		try {
			await updateConfig(editingConfig.id, { chat_name: newChatName.trim(), polling_interval_sec: newInterval });
			toast.success('수정 완료');
			editingConfig = null;
			await loadConfigs();
		} catch (e) {
			toast.error('수정 실패');
		}
	}

	async function handleAddKeyword() {
		if (!editingConfig || !addKwText.trim()) return;
		try {
			const kw = await addKeyword(editingConfig.id, { keyword: addKwText.trim(), action_type: addKwAction });
			configKeywords = [...configKeywords, kw];
			addKwText = '';
			toast.success('키워드 추가');
		} catch (e) {
			toast.error('키워드 추가 실패');
		}
	}

	async function handleDeleteKeyword(kwId: number) {
		try {
			await deleteKeyword(kwId);
			configKeywords = configKeywords.filter(k => k.id !== kwId);
		} catch (e) {
			toast.error('키워드 삭제 실패');
		}
	}

	// ========== 수집 이력 ==========
	async function loadPosts() {
		try {
			const resp = await getPosts({
				config_id: filterConfigId ?? undefined,
				skip: (pager.currentPage - 1) * 20,
				limit: 20,
			});
			posts = resp.items;
			pager.total = resp.total;
		} catch (e) {
			toast.error('이력 로드 실패');
		}
	}

	async function openPost(post: KakaoPost) {
		selectedPost = post;
		showPostModal = true;
	}

	async function handleDeletePost(id: number) {
		if (!confirm('게시물을 삭제하시겠습니까?')) return;
		try {
			await deletePost(id);
			posts = posts.filter(p => p.id !== id);
			if (selectedPost?.id === id) { showPostModal = false; selectedPost = null; }
			toast.success('삭제 완료');
		} catch (e) {
			toast.error('삭제 실패');
		}
	}

	// ========== 카카오 창 ==========
	async function loadWindows() {
		try {
			windows = await getWindows();
		} catch (e) {
			toast.error('창 목록 로드 실패');
		}
	}

	async function handleScan() {
		try {
			const res = await triggerScan();
			toast.success(res.message);
		} catch (e) {
			toast.error('스캔 트리거 실패');
		}
	}

	function useWindowAsConfig(win: WindowInfo) {
		newChatName = win.title;
		showCreateModal = true;
		activeTab = 'settings';
	}

	const tabList: { key: Tab; label: string }[] = [
		{ key: 'dashboard', label: '대시보드' },
		{ key: 'settings', label: '감시 설정' },
		{ key: 'history', label: '수집 이력' },
		{ key: 'windows', label: '카카오 창' },
	];

	function configName(id: number | null) {
		if (id == null) return '-';
		return configs.find(c => c.id === id)?.chat_name ?? String(id);
	}
</script>

<PageHeader title="카카오 모니터" subtitle="카카오톡 채팅방 자동 감시 및 게시물 수집" />

<!-- 탭 네비게이션 -->
<div class="border-b border-gray-200 mb-6">
	<nav class="-mb-px flex space-x-4">
		{#each tabList as { key, label }}
			<button
				class="py-2 px-4 text-sm font-medium border-b-2 transition-colors {activeTab === key
					? 'border-blue-500 text-blue-600'
					: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
				onclick={() => onTabChange(key)}
			>
				{label}
			</button>
		{/each}
	</nav>
</div>

<!-- ========== 대시보드 탭 ========== -->
{#if activeTab === 'dashboard'}
	<div class="space-y-6">
		<!-- 워커 상태 카드 -->
		<div class="bg-white rounded-lg border p-4">
			<h3 class="text-sm font-semibold text-gray-500 mb-3">카카오톡 상태</h3>
			{#if workerStatus}
				<div class="flex gap-4 flex-wrap">
					<span class="px-2 py-1 rounded text-xs font-medium {workerStatus.is_kakao_running ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}">
						{workerStatus.is_kakao_running ? '실행 중' : '미실행'}
					</span>
					<span class="text-xs text-gray-500">창 감지: {workerStatus.main_window_found ? '✓' : '✗'}</span>
					<span class="text-xs text-gray-500">활성 설정: {workerStatus.active_config_count}건</span>
					<button onclick={handleScan} class="ml-auto text-xs bg-blue-500 text-white px-3 py-1 rounded hover:bg-blue-600">
						수동 스캔
					</button>
				</div>
			{:else}
				<p class="text-sm text-gray-400">로드 중...</p>
			{/if}
		</div>

		<!-- 활성 감시 설정 요약 -->
		<div class="bg-white rounded-lg border p-4">
			<h3 class="text-sm font-semibold text-gray-500 mb-3">활성 감시 설정</h3>
			{#if configs.filter(c => c.is_active).length === 0}
				<p class="text-sm text-gray-400">활성 설정 없음</p>
			{:else}
				<ul class="space-y-2">
					{#each configs.filter(c => c.is_active) as config}
						<li class="flex items-center gap-3 text-sm">
							<span class="font-medium">{config.chat_name}</span>
							<span class="text-gray-400">키워드 {config.keyword_count}개</span>
							<span class="text-gray-400">폴링 {config.polling_interval_sec}초</span>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<!-- 최근 수집 게시물 -->
		<div class="bg-white rounded-lg border p-4">
			<h3 class="text-sm font-semibold text-gray-500 mb-3">최근 수집 (최대 5건)</h3>
			{#if recentPosts.length === 0}
				<p class="text-sm text-gray-400">수집된 게시물 없음</p>
			{:else}
				<table class="w-full text-sm">
					<thead>
						<tr class="text-left text-gray-400 text-xs border-b">
							<th class="pb-2 w-36">수집 시각</th>
							<th class="pb-2">키워드</th>
							<th class="pb-2">내용 미리보기</th>
							<th class="pb-2 w-16">상태</th>
						</tr>
					</thead>
					<tbody>
						{#each recentPosts as post}
							<tr class="border-b last:border-0">
								<td class="py-2 text-gray-500 text-xs">{post.collected_at?.slice(0, 16) ?? '-'}</td>
								<td class="py-2">{post.matched_keyword ?? '-'}</td>
								<td class="py-2 text-gray-600 truncate max-w-xs">{(post.collected_content ?? '').slice(0, 50)}</td>
								<td class="py-2">
									<span class="px-1.5 py-0.5 rounded text-xs {post.status === 'success' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}">{post.status}</span>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>
	</div>

<!-- ========== 감시 설정 탭 ========== -->
{:else if activeTab === 'settings'}
	<div class="space-y-4">
		<div class="flex justify-end">
			<button onclick={() => { showCreateModal = true; newChatName = ''; newKeywordsText = ''; newInterval = 3; }}
				class="bg-blue-500 text-white px-4 py-2 rounded text-sm hover:bg-blue-600">
				+ 새 설정 추가
			</button>
		</div>

		<table class="w-full text-sm bg-white rounded-lg border">
			<thead>
				<tr class="text-left text-gray-400 text-xs border-b">
					<th class="p-3">채팅방</th>
					<th class="p-3">키워드 수</th>
					<th class="p-3">폴링 간격</th>
					<th class="p-3">활성</th>
					<th class="p-3">작업</th>
				</tr>
			</thead>
			<tbody>
				{#each configs as config}
					<tr class="border-b last:border-0">
						<td class="p-3 font-medium">{config.chat_name}</td>
						<td class="p-3 text-gray-500">{config.keyword_count}개</td>
						<td class="p-3 text-gray-500">{config.polling_interval_sec}초</td>
						<td class="p-3">
							<button onclick={() => handleToggle(config)}
								class="px-2 py-0.5 rounded text-xs {config.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}">
								{config.is_active ? 'ON' : 'OFF'}
							</button>
						</td>
						<td class="p-3 flex gap-2">
							<button onclick={() => openEditConfig(config)} class="text-blue-500 text-xs hover:underline">편집</button>
							<button onclick={() => handleDeleteConfig(config.id)} class="text-red-400 text-xs hover:underline">삭제</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

<!-- ========== 수집 이력 탭 ========== -->
{:else if activeTab === 'history'}
	<div class="space-y-4">
		<!-- 필터 -->
		<div class="flex gap-3 items-center">
			<select bind:value={filterConfigId}
				onchange={() => { pager.reset(); loadPosts(); }}
				class="text-sm border rounded px-2 py-1">
				<option value={null}>전체 채팅방</option>
				{#each configs as c}
					<option value={c.id}>{c.chat_name}</option>
				{/each}
			</select>
			<button onclick={() => loadPosts()} class="text-sm bg-gray-100 px-3 py-1 rounded hover:bg-gray-200">새로고침</button>
		</div>

		<table class="w-full text-sm bg-white rounded-lg border">
			<thead>
				<tr class="text-left text-gray-400 text-xs border-b">
					<th class="p-3 w-36">수집 시각</th>
					<th class="p-3">채팅방</th>
					<th class="p-3">키워드</th>
					<th class="p-3">내용</th>
					<th class="p-3 w-16">상태</th>
					<th class="p-3 w-16">작업</th>
				</tr>
			</thead>
			<tbody>
				{#each posts as post}
					<tr class="border-b last:border-0 hover:bg-gray-50 cursor-pointer" onclick={() => openPost(post)}>
						<td class="p-3 text-gray-500 text-xs">{post.collected_at?.slice(0, 16) ?? '-'}</td>
						<td class="p-3">{configName(post.config_id)}</td>
						<td class="p-3">{post.matched_keyword ?? '-'}</td>
						<td class="p-3 text-gray-600 truncate max-w-xs">{(post.collected_content ?? '').slice(0, 50)}</td>
						<td class="p-3">
							<span class="px-1.5 py-0.5 rounded text-xs {post.status === 'success' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}">{post.status}</span>
						</td>
						<td class="p-3" onclick={(e) => { e.stopPropagation(); handleDeletePost(post.id); }}>
							<button class="text-red-400 text-xs hover:underline">삭제</button>
						</td>
					</tr>
				{/each}
				{#if posts.length === 0}
					<tr><td colspan="6" class="p-6 text-center text-gray-400">수집 이력 없음</td></tr>
				{/if}
			</tbody>
		</table>

		<!-- 페이지네이션 -->
		{#if pager.totalPages > 1}
			<div class="flex justify-center gap-2">
				{#each Array.from({ length: pager.totalPages }, (_, i) => i + 1) as page}
					<button onclick={() => { pager.goTo(page); loadPosts(); }}
						class="px-3 py-1 rounded text-sm {pager.currentPage === page ? 'bg-blue-500 text-white' : 'bg-gray-100'}">
						{page}
					</button>
				{/each}
			</div>
		{/if}
	</div>

<!-- ========== 카카오 창 탭 ========== -->
{:else if activeTab === 'windows'}
	<div class="space-y-4">
		<div class="flex justify-end">
			<button onclick={loadWindows} class="text-sm bg-gray-100 px-3 py-1 rounded hover:bg-gray-200">새로고침</button>
		</div>
		<table class="w-full text-sm bg-white rounded-lg border">
			<thead>
				<tr class="text-left text-gray-400 text-xs border-b">
					<th class="p-3">핸들 (hex)</th>
					<th class="p-3">채팅방 제목</th>
					<th class="p-3">작업</th>
				</tr>
			</thead>
			<tbody>
				{#each windows as win}
					<tr class="border-b last:border-0">
						<td class="p-3 font-mono text-xs text-gray-400">{win.hwnd_hex}</td>
						<td class="p-3">{win.title}</td>
						<td class="p-3">
							<button onclick={() => useWindowAsConfig(win)} class="text-blue-500 text-xs hover:underline">
								감시 추가
							</button>
						</td>
					</tr>
				{/each}
				{#if windows.length === 0}
					<tr><td colspan="3" class="p-6 text-center text-gray-400">열린 카카오 창 없음</td></tr>
				{/if}
			</tbody>
		</table>
	</div>
{/if}

<!-- ========== 모달: 설정 추가 ========== -->
{#if showCreateModal}
	<div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onclick={() => showCreateModal = false}>
		<div class="bg-white rounded-lg p-6 w-full max-w-md" onclick={(e) => e.stopPropagation()}>
			<h3 class="text-lg font-semibold mb-4">새 감시 설정 추가</h3>
			<div class="space-y-3">
				<div>
					<label class="text-sm font-medium text-gray-700">채팅방 이름</label>
					<input bind:value={newChatName} class="mt-1 w-full border rounded px-3 py-2 text-sm" placeholder="채팅방 이름 입력" />
				</div>
				<div>
					<label class="text-sm font-medium text-gray-700">폴링 간격 (초): {newInterval}</label>
					<input type="range" bind:value={newInterval} min="1" max="60" class="w-full mt-1" />
				</div>
				<div>
					<label class="text-sm font-medium text-gray-700">키워드 (쉼표 구분)</label>
					<input bind:value={newKeywordsText} class="mt-1 w-full border rounded px-3 py-2 text-sm" placeholder="키워드1, 키워드2" />
				</div>
			</div>
			<div class="flex justify-end gap-2 mt-5">
				<button onclick={() => showCreateModal = false} class="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">취소</button>
				<button onclick={handleCreateConfig} class="px-4 py-2 text-sm bg-blue-500 text-white rounded hover:bg-blue-600">추가</button>
			</div>
		</div>
	</div>
{/if}

<!-- ========== 모달: 설정 편집 ========== -->
{#if editingConfig}
	<div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onclick={() => editingConfig = null}>
		<div class="bg-white rounded-lg p-6 w-full max-w-lg" onclick={(e) => e.stopPropagation()}>
			<h3 class="text-lg font-semibold mb-4">{editingConfig.chat_name} 편집</h3>
			<div class="space-y-3 mb-4">
				<div>
					<label class="text-sm font-medium text-gray-700">채팅방 이름</label>
					<input bind:value={newChatName} class="mt-1 w-full border rounded px-3 py-2 text-sm" />
				</div>
				<div>
					<label class="text-sm font-medium text-gray-700">폴링 간격 (초): {newInterval}</label>
					<input type="range" bind:value={newInterval} min="1" max="60" class="w-full mt-1" />
				</div>
			</div>

			<!-- 키워드 관리 -->
			<div class="border-t pt-3">
				<h4 class="text-sm font-medium text-gray-700 mb-2">키워드</h4>
				<div class="flex flex-wrap gap-2 mb-3">
					{#each configKeywords as kw}
						<span class="flex items-center gap-1 bg-blue-50 text-blue-700 text-xs px-2 py-1 rounded">
							{kw.keyword}
							<button onclick={() => handleDeleteKeyword(kw.id)} class="text-blue-400 hover:text-red-500">×</button>
						</span>
					{/each}
				</div>
				<div class="flex gap-2">
					<input bind:value={addKwText} placeholder="새 키워드" class="flex-1 border rounded px-2 py-1 text-sm" />
					<select bind:value={addKwAction} class="border rounded px-2 py-1 text-sm">
						<option value="collect">수집</option>
						<option value="alert_only">알림만</option>
					</select>
					<button onclick={handleAddKeyword} class="bg-blue-500 text-white px-3 py-1 rounded text-sm hover:bg-blue-600">추가</button>
				</div>
			</div>

			<div class="flex justify-end gap-2 mt-5">
				<button onclick={() => editingConfig = null} class="px-4 py-2 text-sm text-gray-500">취소</button>
				<button onclick={handleUpdateConfig} class="px-4 py-2 text-sm bg-blue-500 text-white rounded hover:bg-blue-600">저장</button>
			</div>
		</div>
	</div>
{/if}

<!-- ========== 모달: 게시물 상세 ========== -->
{#if showPostModal && selectedPost}
	<div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onclick={() => showPostModal = false}>
		<div class="bg-white rounded-lg p-6 w-full max-w-2xl max-h-[80vh] overflow-y-auto" onclick={(e) => e.stopPropagation()}>
			<div class="flex items-center justify-between mb-4">
				<h3 class="text-lg font-semibold">수집 게시물 상세</h3>
				<button onclick={() => showPostModal = false} class="text-gray-400 hover:text-gray-600">✕</button>
			</div>
			<dl class="space-y-3 text-sm">
				<div class="flex gap-3">
					<dt class="w-28 text-gray-500 flex-shrink-0">수집 시각</dt>
					<dd>{selectedPost.collected_at?.slice(0, 19) ?? '-'}</dd>
				</div>
				<div class="flex gap-3">
					<dt class="w-28 text-gray-500 flex-shrink-0">채팅방</dt>
					<dd>{configName(selectedPost.config_id)}</dd>
				</div>
				<div class="flex gap-3">
					<dt class="w-28 text-gray-500 flex-shrink-0">매칭 키워드</dt>
					<dd>{selectedPost.matched_keyword ?? '-'}</dd>
				</div>
				<div class="flex gap-3">
					<dt class="w-28 text-gray-500 flex-shrink-0">트리거 메시지</dt>
					<dd class="text-gray-600">{selectedPost.trigger_message ?? '-'}</dd>
				</div>
				<div class="flex gap-3">
					<dt class="w-28 text-gray-500 flex-shrink-0 mt-1">수집 내용</dt>
					<dd class="flex-1 bg-gray-50 rounded p-3 whitespace-pre-wrap text-xs">{selectedPost.collected_content ?? '(없음)'}</dd>
				</div>
				{#if selectedPost.screenshot_path}
					<div class="flex gap-3">
						<dt class="w-28 text-gray-500 flex-shrink-0">스크린샷</dt>
						<dd class="text-xs text-gray-400 break-all">{selectedPost.screenshot_path}</dd>
					</div>
				{/if}
			</dl>
			<div class="flex justify-end gap-2 mt-5">
				<button onclick={() => handleDeletePost(selectedPost!.id)} class="px-4 py-2 text-sm text-red-500 hover:underline">삭제</button>
				<button onclick={() => showPostModal = false} class="px-4 py-2 text-sm bg-gray-100 rounded hover:bg-gray-200">닫기</button>
			</div>
		</div>
	</div>
{/if}
