<script lang="ts">
	import { onMount } from 'svelte';

	// === 타입 정의 ===
	interface Category {
		id: number;
		name: string;
		full_path: string;
		parent_id: number | null;
		importance: 'high' | 'medium' | 'low';
		target_folder_template: string | null;
		description: string | null;
		sort_order: number;
		children: Category[];
	}

	// === 상태 ===
	let categories: Category[] = [];
	let loading = false;
	let expandedCategories = new Set<number>();

	// 추가/수정 모달
	let showModal = false;
	let modalMode: 'create' | 'edit' = 'create';
	let editingCategory: Partial<Category> = {};
	let selectedParentId: number | null = null;

	// === 마운트 ===
	onMount(async () => {
		await loadCategories();
	});

	// === API 호출 ===
	async function loadCategories() {
		loading = true;
		try {
			const res = await fetch('/api/ic/categories?include_tree=true');
			const data = await res.json();
			categories = data.categories || [];
		} catch (e) {
			console.error('카테고리 로드 실패:', e);
		} finally {
			loading = false;
		}
	}

	async function createCategory() {
		try {
			const res = await fetch('/api/ic/categories', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					name: editingCategory.name,
					parent_id: selectedParentId,
					importance: editingCategory.importance || 'medium',
					target_folder_template: editingCategory.target_folder_template || null,
					description: editingCategory.description || null
				})
			});

			if (!res.ok) {
				const error = await res.json();
				throw new Error(error.detail || '생성 실패');
			}

			await loadCategories();
			closeModal();
			alert('카테고리 생성 완료!');
		} catch (e) {
			console.error('카테고리 생성 실패:', e);
			alert('생성 실패: ' + e);
		}
	}

	async function updateCategory() {
		if (!editingCategory.id) return;

		try {
			const res = await fetch(`/api/ic/categories/${editingCategory.id}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					name: editingCategory.name,
					importance: editingCategory.importance,
					target_folder_template: editingCategory.target_folder_template,
					description: editingCategory.description,
					sort_order: editingCategory.sort_order
				})
			});

			if (!res.ok) {
				const error = await res.json();
				throw new Error(error.detail || '수정 실패');
			}

			await loadCategories();
			closeModal();
			alert('카테고리 수정 완료!');
		} catch (e) {
			console.error('카테고리 수정 실패:', e);
			alert('수정 실패: ' + e);
		}
	}

	async function deleteCategory(categoryId: number, force: boolean = false) {
		if (
			!confirm(
				force
					? '하위 카테고리와 매핑된 파일도 모두 삭제됩니다. 계속하시겠습니까?'
					: '이 카테고리를 삭제하시겠습니까?'
			)
		) {
			return;
		}

		try {
			const res = await fetch(`/api/ic/categories/${categoryId}?force=${force}`, {
				method: 'DELETE'
			});

			if (!res.ok) {
				const error = await res.json();
				if (error.detail && error.detail.includes('하위 카테고리')) {
					if (confirm(error.detail + '\n\n강제 삭제하시겠습니까?')) {
						await deleteCategory(categoryId, true);
					}
					return;
				}
				throw new Error(error.detail || '삭제 실패');
			}

			await loadCategories();
			alert('카테고리 삭제 완료!');
		} catch (e) {
			console.error('카테고리 삭제 실패:', e);
			alert('삭제 실패: ' + e);
		}
	}

	// === 모달 관리 ===
	function openCreateModal(parentId: number | null = null) {
		modalMode = 'create';
		selectedParentId = parentId;
		editingCategory = {
			name: '',
			importance: 'medium',
			target_folder_template: null,
			description: null
		};
		showModal = true;
	}

	function openEditModal(category: Category) {
		modalMode = 'edit';
		editingCategory = { ...category };
		showModal = true;
	}

	function closeModal() {
		showModal = false;
		editingCategory = {};
		selectedParentId = null;
	}

	function handleSubmit() {
		if (modalMode === 'create') {
			createCategory();
		} else {
			updateCategory();
		}
	}

	// === 헬퍼 ===
	function toggleCategory(categoryId: number) {
		if (expandedCategories.has(categoryId)) {
			expandedCategories.delete(categoryId);
		} else {
			expandedCategories.add(categoryId);
		}
		expandedCategories = new Set(expandedCategories);
	}

	function getImportanceBadge(importance: string): { label: string; color: string } {
		switch (importance) {
			case 'high':
				return { label: '높음', color: 'bg-red-100 text-red-700' };
			case 'low':
				return { label: '낮음', color: 'bg-gray-100 text-gray-600' };
			default:
				return { label: '보통', color: 'bg-blue-100 text-blue-700' };
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
</script>

<div class="max-w-6xl mx-auto">
	<!-- 헤더 -->
	<div class="mb-6 flex items-center justify-between">
		<div>
			<h1 class="text-3xl font-bold text-gray-900">🏷️ 카테고리 관리</h1>
			<p class="text-gray-600 mt-2">멀티레벨 카테고리 트리를 생성하고 편집합니다.</p>
		</div>
		<button
			on:click={() => openCreateModal(null)}
			class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
		>
			+ 루트 카테고리 추가
		</button>
	</div>

	<!-- 카테고리 트리 -->
	<div class="bg-white rounded-lg shadow">
		{#if loading}
			<div class="p-8 text-center text-gray-500">로딩 중...</div>
		{:else if categories.length === 0}
			<div class="p-8 text-center">
				<p class="text-gray-500 mb-4">카테고리가 없습니다.</p>
				<p class="text-sm text-gray-400">
					먼저 루트 카테고리를 생성하세요. 예: outdoor, indoor, personal 등
				</p>
			</div>
		{:else}
			<div class="p-6">
				{#each categories as category}
					{@const badge = getImportanceBadge(category.importance)}
					<div class="mb-4">
						<!-- 루트 카테고리 -->
						<div class="flex items-center gap-2 p-3 bg-gray-50 rounded-lg border border-gray-200">
							{#if category.children.length > 0}
								<button
									on:click={() => toggleCategory(category.id)}
									class="text-gray-600 hover:text-gray-900"
								>
									{expandedCategories.has(category.id) ? '▼' : '▶'}
								</button>
							{:else}
								<span class="w-4"></span>
							{/if}

							<span class="font-bold text-lg">{category.name}</span>
							<span class="text-xs px-2 py-1 rounded {badge.color}">
								{badge.label}
							</span>

							{#if category.description}
								<span class="text-sm text-gray-500">— {category.description}</span>
							{/if}

							<div class="ml-auto flex gap-2">
								<button
									on:click={() => openCreateModal(category.id)}
									class="text-sm text-blue-600 hover:underline"
								>
									+ 하위 추가
								</button>
								<button
									on:click={() => openEditModal(category)}
									class="text-sm text-gray-600 hover:underline"
								>
									✏️ 수정
								</button>
								<button
									on:click={() => deleteCategory(category.id)}
									class="text-sm text-red-600 hover:underline"
								>
									🗑️ 삭제
								</button>
							</div>
						</div>

						<!-- 하위 카테고리 -->
						{#if expandedCategories.has(category.id) && category.children.length > 0}
							<div class="ml-8 mt-2 space-y-2">
								{#each category.children as child}
									{@const childBadge = getImportanceBadge(child.importance)}
									<div
										class="flex items-center gap-2 p-2 bg-white rounded border border-gray-200 hover:bg-gray-50"
									>
										<span class="text-gray-400">└─</span>
										<span class="font-medium">{child.name}</span>
										<span class="text-xs text-gray-500">({child.full_path})</span>
										<span class="text-xs px-2 py-0.5 rounded {childBadge.color}">
											{childBadge.label}
										</span>

										<div class="ml-auto flex gap-2">
											{#if child.children.length === 0}
												<button
													on:click={() => openCreateModal(child.id)}
													class="text-xs text-blue-600 hover:underline"
												>
													+ 하위 추가
												</button>
											{/if}
											<button
												on:click={() => openEditModal(child)}
												class="text-xs text-gray-600 hover:underline"
											>
												✏️
											</button>
											<button
												on:click={() => deleteCategory(child.id)}
												class="text-xs text-red-600 hover:underline"
											>
												🗑️
											</button>
										</div>
									</div>

									<!-- 3단계 하위 카테고리 -->
									{#if child.children.length > 0}
										<div class="ml-8 space-y-1">
											{#each child.children as grandchild}
												{@const gcBadge = getImportanceBadge(grandchild.importance)}
												<div
													class="flex items-center gap-2 p-2 bg-white rounded border border-gray-100"
												>
													<span class="text-gray-300">└─</span>
													<span class="text-sm">{grandchild.name}</span>
													<span class="text-xs text-gray-400">({grandchild.full_path})</span>
													<span class="text-xs px-2 py-0.5 rounded {gcBadge.color}">
														{gcBadge.label}
													</span>

													<div class="ml-auto flex gap-2">
														<button
															on:click={() => openEditModal(grandchild)}
															class="text-xs text-gray-600 hover:underline"
														>
															✏️
														</button>
														<button
															on:click={() => deleteCategory(grandchild.id)}
															class="text-xs text-red-600 hover:underline"
														>
															🗑️
														</button>
													</div>
												</div>
											{/each}
										</div>
									{/if}
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>

	<!-- 예시 카테고리 -->
	<div class="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
		<h3 class="font-medium text-blue-900 mb-2">💡 카테고리 예시</h3>
		<div class="text-sm text-blue-800 space-y-2">
			<div>
				<strong>outdoor</strong> → travel, landscape, nature, beach, mountain
			</div>
			<div><strong>indoor</strong> → home, office, restaurant, cafe, shopping</div>
			<div>
				<strong>personal</strong> → identification, documents, receipts, family, friends
			</div>
			<div><strong>screenshot</strong> → work, study, meme, reference</div>
			<div><strong>download</strong> → wallpaper, meme, reference</div>
		</div>
	</div>
</div>

<!-- 모달 -->
{#if showModal}
	<div
		class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
		on:click={closeModal}
		on:keydown={(e) => e.key === 'Escape' && closeModal()}
	>
		<div
			class="bg-white rounded-lg shadow-xl p-6 w-full max-w-md"
			on:click|stopPropagation
			on:keydown|stopPropagation
		>
			<h2 class="text-xl font-bold mb-4">
				{modalMode === 'create' ? '카테고리 추가' : '카테고리 수정'}
			</h2>

			<form on:submit|preventDefault={handleSubmit} class="space-y-4">
				<!-- 이름 -->
				<div>
					<label class="block text-sm font-medium text-gray-700 mb-1">카테고리 이름 *</label>
					<input
						type="text"
						bind:value={editingCategory.name}
						required
						class="w-full px-3 py-2 border border-gray-300 rounded"
						placeholder="예: travel, documents 등"
					/>
				</div>

				<!-- 부모 (생성 시에만) -->
				{#if modalMode === 'create' && selectedParentId !== null}
					{@const parentCat = flattenCategories(categories).find(
						(c) => c.id === selectedParentId
					)}
					<div>
						<label class="block text-sm font-medium text-gray-700 mb-1">부모 카테고리</label>
						<input
							type="text"
							value={parentCat ? parentCat.full_path : ''}
							disabled
							class="w-full px-3 py-2 border border-gray-300 rounded bg-gray-50"
						/>
					</div>
				{/if}

				<!-- 중요도 -->
				<div>
					<label class="block text-sm font-medium text-gray-700 mb-1">중요도</label>
					<select
						bind:value={editingCategory.importance}
						class="w-full px-3 py-2 border border-gray-300 rounded"
					>
						<option value="high">높음</option>
						<option value="medium">보통</option>
						<option value="low">낮음</option>
					</select>
				</div>

				<!-- 설명 -->
				<div>
					<label class="block text-sm font-medium text-gray-700 mb-1">설명 (선택)</label>
					<textarea
						bind:value={editingCategory.description}
						rows="2"
						class="w-full px-3 py-2 border border-gray-300 rounded"
						placeholder="이 카테고리의 용도 설명..."
					></textarea>
				</div>

				<!-- 이동 경로 템플릿 (선택) -->
				<div>
					<label class="block text-sm font-medium text-gray-700 mb-1"
						>이동 경로 템플릿 (선택)</label
					>
					<input
						type="text"
						bind:value={editingCategory.target_folder_template}
						class="w-full px-3 py-2 border border-gray-300 rounded"
						placeholder="예: D:\정리\{'{'}category{'}'}\{'{'}year{'}'}"
					/>
					<p class="text-xs text-gray-500 mt-1">
						변수: {'{'}category{'}'}, {'{'}year{'}'}, {'{'}month{'}'}, {'{'}day{'}'}
					</p>
				</div>

				<!-- 버튼 -->
				<div class="flex gap-2 justify-end pt-4">
					<button
						type="button"
						on:click={closeModal}
						class="px-4 py-2 border border-gray-300 rounded hover:bg-gray-50"
					>
						취소
					</button>
					<button type="submit" class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
						{modalMode === 'create' ? '생성' : '수정'}
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}
