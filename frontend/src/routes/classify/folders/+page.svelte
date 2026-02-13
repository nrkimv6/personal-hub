<script lang="ts">
	import { onMount } from 'svelte';
  import { fetchWithTimeout } from '$lib/api/client';

	// === 타입 정의 ===
	interface Folder {
		id: number;
		folder_path: string;
		file_count: number;
		folder_status: 'clear' | 'unclear' | 'flat' | 'nested' | 'unknown';
		category_id: number | null;
		is_mixed: boolean;
		suggested_category?: string;
		ai_loading?: boolean;
	}

	interface Category {
		id: number;
		name: string;
		full_path: string;
		parent_id: number | null;
		children: Category[];
	}

	// === 상태 ===
	let folders: Folder[] = [];
	let categories: Category[] = [];
	let loading = false;
	let classifyLoading = false;
	let statusFilter: string = 'all';
	let expandedFolders = new Set<number>();

	// === 마운트 ===
	onMount(async () => {
		await loadCategories();
		await loadFolders();
	});

	// === API 호출 ===
	async function loadCategories() {
		try {
			const res = await fetchWithTimeout('/api/ic/categories?include_tree=true');
			const data = await res.json();
			categories = data.categories || [];
		} catch (e) {
			console.error('카테고리 로드 실패:', e);
		}
	}

	async function loadFolders() {
		loading = true;
		try {
			const params = new URLSearchParams();
			if (statusFilter !== 'all') {
				params.append('folder_status', statusFilter);
			}
			params.append('limit', '500');

			const res = await fetchWithTimeout(`/api/ic/scan/folders?${params}`);
			const data = await res.json();
			folders = data.folders || [];
		} catch (e) {
			console.error('폴더 로드 실패:', e);
		} finally {
			loading = false;
		}
	}

	async function classifyAllFolders() {
		classifyLoading = true;
		try {
			const res = await fetchWithTimeout('/api/ic/folders/classify', { method: 'POST' });
			const data = await res.json();
			alert(`분류 완료: ${JSON.stringify(data.stats)}`);
			await loadFolders();
		} catch (e) {
			console.error('폴더 분류 실패:', e);
			alert('폴더 분류 실패: ' + e);
		} finally {
			classifyLoading = false;
		}
	}

	async function requestAISuggestion(folder: Folder) {
		folder.ai_loading = true;
		folders = [...folders]; // 리렌더링

		try {
			const res = await fetchWithTimeout('/api/ic/folders/ai-suggest', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ folder_id: folder.id })
			});

			if (!res.ok) {
				const error = await res.json();
				throw new Error(error.detail || '추천 실패');
			}

			const data = await res.json();
			folder.suggested_category = data.suggested_category;
			folders = [...folders];
		} catch (e) {
			console.error('AI 추천 실패:', e);
			alert('AI 추천 실패: ' + e);
		} finally {
			folder.ai_loading = false;
			folders = [...folders];
		}
	}

	async function saveMapping(folder: Folder, categoryId: number) {
		try {
			const res = await fetchWithTimeout(`/api/ic/folders/${folder.id}/map`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ category_id: categoryId })
			});

			if (!res.ok) {
				throw new Error('매핑 저장 실패');
			}

			folder.category_id = categoryId;
			folders = [...folders];
			alert('매핑 저장 완료!');
		} catch (e) {
			console.error('매핑 저장 실패:', e);
			alert('매핑 저장 실패: ' + e);
		}
	}

	async function applyInheritance(folderId: number) {
		try {
			const res = await fetchWithTimeout('/api/ic/folders/inherit', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ parent_folder_id: folderId, apply_to_children: true })
			});

			if (!res.ok) {
				throw new Error('상속 적용 실패');
			}

			const data = await res.json();
			alert(`상속 완료: ${data.children_updated}개 하위 폴더에 적용`);
			await loadFolders();
		} catch (e) {
			console.error('상속 실패:', e);
			alert('상속 실패: ' + e);
		}
	}

	// === 헬퍼 ===
	function toggleFolder(folderId: number) {
		if (expandedFolders.has(folderId)) {
			expandedFolders.delete(folderId);
		} else {
			expandedFolders.add(folderId);
		}
		expandedFolders = new Set(expandedFolders);
	}

	function getCategoryName(categoryId: number | null): string {
		if (!categoryId) return '—미지정—';
		const cat = findCategory(categories, categoryId);
		return cat ? cat.full_path : '알 수 없음';
	}

	function findCategory(cats: Category[], id: number): Category | null {
		for (const cat of cats) {
			if (cat.id === id) return cat;
			if (cat.children.length > 0) {
				const found = findCategory(cat.children, id);
				if (found) return found;
			}
		}
		return null;
	}

	function getStatusBadge(status: string): { label: string; color: string } {
		switch (status) {
			case 'clear':
				return { label: '명확', color: 'bg-green-100 text-green-700' };
			case 'unclear':
				return { label: '불명확', color: 'bg-yellow-100 text-yellow-700' };
			case 'flat':
				return { label: '플랫 (혼합)', color: 'bg-orange-100 text-orange-700' };
			case 'nested':
				return { label: '중첩 (상속 권장)', color: 'bg-purple-100 text-purple-700' };
			default:
				return { label: '미판정', color: 'bg-gray-100 text-gray-600' };
		}
	}

	function flattenCategories(cats: Category[]): Category[] {
		let result: Category[] = [];
		for (const cat of cats) {
			result.push(cat);
			if (cat.children.length > 0) {
				result = result.concat(flattenCategories(cat.children));
			}
		}
		return result;
	}

	$: filteredFolders =
		statusFilter === 'all' ? folders : folders.filter((f) => f.folder_status === statusFilter);

	$: mappedCount = folders.filter((f) => f.category_id !== null).length;
	$: totalCount = folders.length;
</script>

<div class="max-w-7xl mx-auto">
	<!-- 헤더 -->
	<div class="mb-6">
		<h1 class="text-3xl font-bold text-gray-900">📁 폴더 매핑</h1>
		<p class="text-gray-600 mt-2">
			폴더를 카테고리에 매핑하여 전체 파일의 ~70%를 자동 분류합니다.
		</p>
	</div>

	<!-- 진행률 -->
	<div class="bg-white rounded-lg shadow p-6 mb-6">
		<div class="flex items-center justify-between mb-2">
			<span class="text-sm font-medium text-gray-700">매핑 진행률</span>
			<span class="text-sm text-gray-500">
				{mappedCount} / {totalCount} 폴더
			</span>
		</div>
		<div class="w-full bg-gray-200 rounded-full h-3">
			<div
				class="bg-blue-600 h-3 rounded-full transition-all"
				style="width: {totalCount > 0 ? (mappedCount / totalCount) * 100 : 0}%"
			></div>
		</div>
	</div>

	<!-- 액션 바 -->
	<div class="bg-white rounded-lg shadow p-4 mb-6 flex items-center gap-4">
		<button
			on:click={classifyAllFolders}
			disabled={classifyLoading}
			class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
		>
			{classifyLoading ? '분류 중...' : '🔍 폴더 자동 분류'}
		</button>

		<select
			bind:value={statusFilter}
			on:change={loadFolders}
			class="px-4 py-2 border border-gray-300 rounded"
		>
			<option value="all">전체 폴더</option>
			<option value="unknown">미판정</option>
			<option value="clear">명확</option>
			<option value="unclear">불명확</option>
			<option value="flat">플랫</option>
			<option value="nested">중첩</option>
		</select>

		<button
			on:click={loadFolders}
			class="px-4 py-2 border border-gray-300 rounded hover:bg-gray-50"
		>
			🔄 새로고침
		</button>
	</div>

	<!-- 폴더 리스트 -->
	<div class="bg-white rounded-lg shadow">
		{#if loading}
			<div class="p-8 text-center text-gray-500">로딩 중...</div>
		{:else if filteredFolders.length === 0}
			<div class="p-8 text-center text-gray-500">폴더가 없습니다.</div>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full">
					<thead class="bg-gray-50 border-b">
						<tr>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">폴더</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase"
								>파일 수</th
							>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase"
								>AI 추천</th
							>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase"
								>카테고리</th
							>
							<th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">액션</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-gray-200">
						{#each filteredFolders as folder}
							{@const badge = getStatusBadge(folder.folder_status)}
							<tr class="hover:bg-gray-50">
								<td class="px-4 py-3 text-sm">
									<div class="font-mono text-xs text-gray-600">{folder.folder_path}</div>
								</td>
								<td class="px-4 py-3 text-sm text-gray-700">
									{folder.file_count.toLocaleString()}장
								</td>
								<td class="px-4 py-3 text-sm">
									<span class="px-2 py-1 text-xs rounded {badge.color}">
										{badge.label}
									</span>
								</td>
								<td class="px-4 py-3 text-sm">
									{#if folder.ai_loading}
										<span class="text-gray-500">분석 중...</span>
									{:else if folder.suggested_category}
										<span class="text-blue-600 font-medium">{folder.suggested_category}</span>
									{:else}
										<button
											on:click={() => requestAISuggestion(folder)}
											class="text-blue-600 hover:underline text-xs"
										>
											🔍 AI 추천
										</button>
									{/if}
								</td>
								<td class="px-4 py-3 text-sm">
									<select
										value={folder.category_id || ''}
										on:change={(e) => {
											const val = e.currentTarget.value;
											if (val) saveMapping(folder, parseInt(val));
										}}
										class="px-2 py-1 border border-gray-300 rounded text-sm"
									>
										<option value="">—선택—</option>
										{#each flattenCategories(categories) as cat}
											<option value={cat.id}>{cat.full_path}</option>
										{/each}
									</select>
								</td>
								<td class="px-4 py-3 text-sm">
									{#if folder.category_id && folder.folder_status === 'nested'}
										<button
											on:click={() => applyInheritance(folder.id)}
											class="text-purple-600 hover:underline text-xs"
										>
											⬇️ 하위 상속
										</button>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>

	<!-- 도움말 -->
	<div class="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
		<h3 class="font-medium text-blue-900 mb-2">💡 사용 팁</h3>
		<ul class="text-sm text-blue-800 space-y-1">
			<li>1. 먼저 "폴더 자동 분류" 버튼으로 모든 폴더의 상태를 판정합니다.</li>
			<li>2. 명확한 폴더는 카테고리 드롭다운에서 직접 선택하거나 AI 추천을 사용하세요.</li>
			<li>3. 불명확한 폴더는 AI 추천 기능이 샘플 이미지를 분석하여 추천합니다.</li>
			<li>
				4. 중첩 폴더는 상위 폴더에 매핑 후 "하위 상속" 버튼으로 한 번에 적용할 수 있습니다.
			</li>
			<li>5. 플랫 폴더(파일 500개+ 서브폴더 없음)는 혼합 폴더로 시간 클러스터링으로 넘어갑니다.</li>
		</ul>
	</div>
</div>

<style>
	table {
		min-width: 900px;
	}
</style>
