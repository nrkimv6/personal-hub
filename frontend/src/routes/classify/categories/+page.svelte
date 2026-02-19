<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import {
		FolderTree,
		ChevronRight,
		ChevronDown,
		Plus,
		Pencil,
		Trash2,
		Save,
		X,
		FolderOpen
	} from 'lucide-svelte';

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
	let categories: Category[] = $state([]);
	let loading = $state(false);
	let expandedCategories = $state(new Set<number>());

	// 모달 관련 (create용 - 인라인 폼으로 대체하지 않고 기존 함수 보존)
	let showModal = false;
	let modalMode: 'create' | 'edit' = 'create';
	let editingCategory: Partial<Category> = {};
	let selectedParentId: number | null = null;

	// 새 Svelte 5 상태
	let selected = $state<Category | null>(null);
	let editing = $state(false);
	let editForm = $state<Partial<Category>>({});

	// 신규 생성 인라인 폼
	let showCreateForm = $state(false);
	let createParentId = $state<number | null>(null);
	let createForm = $state<Partial<Category>>({
		name: '',
		importance: 'medium',
		target_folder_template: null,
		description: null
	});

	// === 마운트 ===
	onMount(async () => {
		await loadCategories();
	});

	// === API 호출 ===
	async function loadCategories() {
		loading = true;
		try {
			const res = await fetchWithTimeout('/api/ic/categories?include_tree=true');
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
			const res = await fetchWithTimeout('/api/ic/categories', {
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
			const res = await fetchWithTimeout(`/api/ic/categories/${editingCategory.id}`, {
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

	async function saveEdit() {
		if (!selected) return;
		editingCategory = { ...editForm };
		await updateCategory();
		editing = false;
		// 선택된 카테고리를 갱신
		const updated = flattenCategories(categories).find((c) => c.id === selected?.id);
		if (updated) selected = updated;
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
			const res = await fetchWithTimeout(`/api/ic/categories/${categoryId}?force=${force}`, {
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

			if (selected?.id === categoryId) selected = null;
			await loadCategories();
			alert('카테고리 삭제 완료!');
		} catch (e) {
			console.error('카테고리 삭제 실패:', e);
			alert('삭제 실패: ' + e);
		}
	}

	async function submitCreate() {
		try {
			const res = await fetchWithTimeout('/api/ic/categories', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					name: createForm.name,
					parent_id: createParentId,
					importance: createForm.importance || 'medium',
					target_folder_template: createForm.target_folder_template || null,
					description: createForm.description || null
				})
			});

			if (!res.ok) {
				const error = await res.json();
				throw new Error(error.detail || '생성 실패');
			}

			showCreateForm = false;
			createForm = { name: '', importance: 'medium', target_folder_template: null, description: null };
			createParentId = null;
			await loadCategories();
		} catch (e) {
			alert('생성 실패: ' + e);
		}
	}

	// === 모달 관리 (기존 함수 보존) ===
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
				return { label: '높음', color: 'bg-destructive/10 text-destructive' };
			case 'low':
				return { label: '낮음', color: 'bg-muted text-muted-foreground' };
			default:
				return { label: '보통', color: 'bg-primary/10 text-primary' };
		}
	}

	function importanceClass(importance: string): string {
		switch (importance) {
			case 'high':
				return 'bg-destructive/10 text-destructive';
			case 'low':
				return 'bg-muted text-muted-foreground';
			default:
				return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400';
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

	function openAddChild(cat: Category) {
		createParentId = cat.id;
		createForm = { name: '', importance: 'medium', target_folder_template: null, description: null };
		showCreateForm = true;
	}

	function openAddRoot() {
		createParentId = null;
		createForm = { name: '', importance: 'medium', target_folder_template: null, description: null };
		showCreateForm = true;
	}
</script>

<svelte:head>
	<title>카테고리 — 이미지 분류기</title>
</svelte:head>

<!-- 헤더 -->
<div class="mb-4">
	<div class="flex items-center gap-2">
		<FolderTree class="size-5 text-primary" />
		<h1 class="text-2xl font-bold tracking-tight">카테고리</h1>
	</div>
	<p class="mt-1 text-sm text-muted-foreground">멀티레벨 카테고리 트리를 생성하고 편집합니다.</p>
</div>

<!-- 2패널 레이아웃 -->
<div class="flex flex-col lg:flex-row gap-6">
	<!-- 패널 a: 카테고리 트리 -->
	<div class="lg:w-96 flex-shrink-0">
		<div class="rounded-xl border bg-card overflow-hidden">
			<!-- 트리 헤더 -->
			<div class="flex items-center justify-between px-4 py-3 border-b bg-muted/20">
				<span class="text-sm font-semibold">카테고리 트리</span>
				<button
					class="flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
					onclick={openAddRoot}
				>
					<Plus class="size-3.5" />
					루트 추가
				</button>
			</div>

			<!-- 트리 컨텐츠 -->
			{#if loading}
				<div class="p-6 text-center text-sm text-muted-foreground animate-pulse">로딩 중...</div>
			{:else if categories.length === 0}
				<div class="p-6 text-center text-sm text-muted-foreground">카테고리가 없습니다.</div>
			{:else}
				<div class="p-2 space-y-0.5 max-h-[600px] overflow-y-auto">
					{#snippet treeNode(cat: Category, depth: number)}
						<div>
							<div
								class="flex w-full items-center gap-1.5 rounded-md text-sm transition-colors {selected?.id === cat.id
									? 'bg-primary/10 text-primary'
									: 'text-foreground hover:bg-accent'}"
								style="padding-left: {depth * 16 + 8}px; padding-right: 8px; padding-top: 6px; padding-bottom: 6px;"
							>
								<!-- 확장 토글 -->
								{#if cat.children.length > 0}
									<button
										class="flex-shrink-0 rounded hover:bg-muted p-0.5"
										onclick={(e) => {
											e.stopPropagation();
											toggleCategory(cat.id);
										}}
									>
										{#if expandedCategories.has(cat.id)}
											<ChevronDown class="size-3 text-muted-foreground" />
										{:else}
											<ChevronRight class="size-3 text-muted-foreground" />
										{/if}
									</button>
								{:else}
									<span class="size-4 flex-shrink-0"></span>
								{/if}

								<!-- 폴더 아이콘 + 이름 (클릭 시 선택) -->
								<button
									class="flex flex-1 items-center gap-1.5 min-w-0 text-left"
									onclick={() => {
										selected = cat;
										editing = false;
										editForm = { ...cat };
									}}
								>
									<FolderOpen class="size-3.5 text-muted-foreground flex-shrink-0" />
									<span class="flex-1 truncate">{cat.name}</span>
									<span
										class="text-[10px] px-1.5 py-0.5 rounded flex-shrink-0 {importanceClass(cat.importance)}"
									>
										{cat.importance === 'high' ? '높음' : cat.importance === 'low' ? '낮음' : '보통'}
									</span>
								</button>
							</div>

							{#if expandedCategories.has(cat.id) && cat.children.length > 0}
								{#each cat.children as child}
									{@render treeNode(child, depth + 1)}
								{/each}
							{/if}
						</div>
					{/snippet}

					{#each categories as cat}
						{@render treeNode(cat, 0)}
					{/each}
				</div>
			{/if}

			<!-- 하단 대시 버튼 -->
			<div class="p-2 border-t">
				<button
					class="w-full rounded-lg border border-dashed py-2 text-xs text-muted-foreground hover:text-foreground hover:border-foreground/40 transition-colors"
					onclick={openAddRoot}
				>
					<Plus class="size-3 inline mr-1" />
					루트 카테고리 추가
				</button>
			</div>
		</div>
	</div>

	<!-- 패널 b: Editor -->
	<div class="flex-1">
		<div class="rounded-xl border bg-card overflow-hidden min-h-[400px]">
			{#if !selected}
				<!-- 미선택 상태 -->
				<div class="flex flex-col items-center justify-center h-full min-h-[400px] gap-3 text-muted-foreground">
					<FolderTree class="size-10 opacity-30" />
					<p class="text-sm">카테고리를 선택하면 상세 정보를 볼 수 있습니다</p>
				</div>
			{:else if !editing}
				<!-- View 모드 -->
				<div class="p-6">
					<div class="flex items-start justify-between gap-4 mb-4">
						<div>
							<h2 class="text-xl font-semibold">{selected.name}</h2>
							<p class="text-sm font-mono text-muted-foreground mt-0.5">{selected.full_path}</p>
						</div>
						<div class="flex items-center gap-2 flex-shrink-0">
							<button
								class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-accent transition-colors"
								onclick={() => {
									editing = true;
									editingCategory = { ...selected! };
									editForm = { ...selected! };
								}}
							>
								<Pencil class="size-3.5" />
								편집
							</button>
							<button
								class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-accent transition-colors"
								onclick={() => openAddChild(selected!)}
							>
								<Plus class="size-3.5" />
								하위 추가
							</button>
							<button
								class="flex items-center gap-1.5 rounded-lg border border-destructive/40 px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors"
								onclick={() => deleteCategory(selected!.id)}
							>
								<Trash2 class="size-3.5" />
								삭제
							</button>
						</div>
					</div>

					<!-- 상세 정보 -->
					<div class="space-y-4">
						<div class="flex items-center gap-2">
							<span class="text-xs font-medium text-muted-foreground w-28">중요도</span>
							<span
								class="text-xs px-2 py-0.5 rounded-full {importanceClass(selected.importance)}"
							>
								{selected.importance === 'high' ? '높음' : selected.importance === 'low' ? '낮음' : '보통'}
							</span>
						</div>

						{#if selected.target_folder_template}
							<div class="flex items-start gap-2">
								<span class="text-xs font-medium text-muted-foreground w-28 pt-0.5">폴더 템플릿</span>
								<code class="text-xs bg-muted px-2 py-1 rounded font-mono break-all">
									{selected.target_folder_template}
								</code>
							</div>
						{/if}

						{#if selected.description}
							<div class="flex items-start gap-2">
								<span class="text-xs font-medium text-muted-foreground w-28 pt-0.5">설명</span>
								<p class="text-sm">{selected.description}</p>
							</div>
						{/if}

						<div class="flex items-center gap-2">
							<span class="text-xs font-medium text-muted-foreground w-28">하위</span>
							<span class="text-xs bg-muted px-2 py-0.5 rounded-full">
								{selected.children.length}
							</span>
						</div>

						{#if selected.children.length > 0}
							<div class="mt-2 flex flex-wrap gap-1.5">
								{#each selected.children as child}
									<button
										class="text-xs px-2.5 py-1 rounded-full border hover:bg-accent transition-colors"
										onclick={() => {
											selected = child;
											editForm = { ...child };
										}}
									>
										{child.name}
									</button>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{:else}
				<!-- Edit 모드 -->
				<div class="p-6">
					<div class="flex items-center justify-between mb-5">
						<h2 class="text-base font-semibold">카테고리 편집</h2>
						<div class="flex items-center gap-2">
							<button
								class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-muted-foreground border hover:bg-accent transition-colors"
								onclick={() => (editing = false)}
							>
								<X class="size-3.5" />
								취소
							</button>
							<button
								class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
								onclick={saveEdit}
							>
								<Save class="size-3.5" />
								저장
							</button>
						</div>
					</div>

					<div class="space-y-4 max-w-md">
						<!-- 이름 -->
						<div>
							<label for="edit-name" class="block text-xs font-medium text-muted-foreground mb-1.5">이름</label>
							<input
								id="edit-name"
								type="text"
								class="w-full px-3 py-2 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
								bind:value={editForm.name}
								placeholder="카테고리 이름"
							/>
						</div>

						<!-- Importance 세그먼트 -->
						<div>
							<p class="text-xs font-medium text-muted-foreground mb-1.5">중요도</p>
							<div class="flex rounded-lg border bg-muted/40 p-0.5 gap-0.5 w-fit">
								{#each [['high', '높음'], ['medium', '보통'], ['low', '낮음']] as [val, label]}
									<button
										class="px-4 py-1.5 text-xs font-medium rounded-md transition-colors {editForm.importance === val
											? 'bg-background text-foreground shadow-sm'
											: 'text-muted-foreground hover:text-foreground'}"
										onclick={() => (editForm.importance = val as 'high' | 'medium' | 'low')}
									>
										{label}
									</button>
								{/each}
							</div>
						</div>

						<!-- Folder Template -->
						<div>
							<label for="edit-folder-template" class="block text-xs font-medium text-muted-foreground mb-1.5">
								폴더 템플릿
							</label>
							<input
								id="edit-folder-template"
								type="text"
								class="w-full px-3 py-2 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono"
								bind:value={editForm.target_folder_template}
								placeholder="예: D:\정리\{'{'}category{'}'}\{'{'}year{'}'}"
							/>
							<p class="text-[11px] text-muted-foreground mt-1">
								변수: {'{'}category{'}'}, {'{'}year{'}'}, {'{'}month{'}'}, {'{'}day{'}'}
							</p>
						</div>

						<!-- Description -->
						<div>
							<label for="edit-description" class="block text-xs font-medium text-muted-foreground mb-1.5">설명</label>
							<textarea
								id="edit-description"
								class="w-full px-3 py-2 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
								rows="3"
								bind:value={editForm.description}
								placeholder="이 카테고리의 용도 설명..."
							></textarea>
						</div>
					</div>
				</div>
			{/if}
		</div>
	</div>
</div>

<!-- 인라인 생성 폼 (오버레이 방식) -->
{#if showCreateForm}
	<div
		class="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50"
		onclick={() => (showCreateForm = false)}
		onkeydown={(e) => e.key === 'Escape' && (showCreateForm = false)}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
	>
		<div
			class="bg-card rounded-xl border shadow-xl p-6 w-full max-w-md"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="presentation"
		>
			<div class="flex items-center justify-between mb-4">
				<h2 class="text-base font-semibold">
					{createParentId ? '하위 카테고리 추가' : '루트 카테고리 추가'}
				</h2>
				<button
					class="text-muted-foreground hover:text-foreground transition-colors"
					onclick={() => (showCreateForm = false)}
				>
					<X class="size-4" />
				</button>
			</div>

			<div class="space-y-4">
				{#if createParentId !== null}
					{@const parentCat = flattenCategories(categories).find((c) => c.id === createParentId)}
					{#if parentCat}
						<div>
							<p class="text-xs font-medium text-muted-foreground mb-1.5">상위</p>
							<div class="px-3 py-2 text-sm bg-muted rounded-lg font-mono">{parentCat.full_path}</div>
						</div>
					{/if}
				{/if}

				<div>
					<label for="create-name" class="block text-xs font-medium text-muted-foreground mb-1.5">이름 *</label>
					<input
						id="create-name"
						type="text"
						class="w-full px-3 py-2 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
						bind:value={createForm.name}
						placeholder="예: travel, documents..."
					/>
				</div>

				<div>
					<p class="text-xs font-medium text-muted-foreground mb-1.5">중요도</p>
					<div class="flex rounded-lg border bg-muted/40 p-0.5 gap-0.5 w-fit">
						{#each [['high', '높음'], ['medium', '보통'], ['low', '낮음']] as [val, label]}
							<button
								class="px-4 py-1.5 text-xs font-medium rounded-md transition-colors {createForm.importance === val
									? 'bg-background text-foreground shadow-sm'
									: 'text-muted-foreground hover:text-foreground'}"
								onclick={() => (createForm.importance = val as 'high' | 'medium' | 'low')}
							>
								{label}
							</button>
						{/each}
					</div>
				</div>

				<div>
					<label for="create-folder-template" class="block text-xs font-medium text-muted-foreground mb-1.5">
						폴더 템플릿
					</label>
					<input
						id="create-folder-template"
						type="text"
						class="w-full px-3 py-2 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono"
						bind:value={createForm.target_folder_template}
						placeholder="선택 사항"
					/>
				</div>

				<div>
					<label for="create-description" class="block text-xs font-medium text-muted-foreground mb-1.5">설명</label>
					<textarea
						id="create-description"
						class="w-full px-3 py-2 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
						rows="2"
						bind:value={createForm.description}
						placeholder="선택 사항"
					></textarea>
				</div>

				<div class="flex gap-2 justify-end pt-2">
					<button
						class="px-4 py-2 text-sm border rounded-lg hover:bg-accent transition-colors"
						onclick={() => (showCreateForm = false)}
					>
						취소
					</button>
					<button
						class="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors font-medium"
						onclick={submitCreate}
					>
						만들기
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
