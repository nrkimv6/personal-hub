<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import {
		FolderOpen,
		FolderSearch,
		Plus,
		Trash2,
		Play,
		Square,
		CheckCircle2,
		FileImage,
		Folder,
		RefreshCw,
		Brain
	} from 'lucide-svelte';

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

	// === 보존된 기존 상태 ===
	let folders: Folder[] = $state([]);
	let categories: Category[] = $state([]);
	let loading = $state(false);
	let classifyLoading = $state(false);
	let statusFilter: string = $state('all');
	let expandedFolders = $state(new Set<number>());

	// === 추가 상태 ===
	let scanning = $state(false);
	let progress = $state(0);
	let scanRoots = $state<string[]>([]);
	let extensions = $state(['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'raw']);
	let scanDone = $state(false);
	let newFolderInput = $state('');

	const mappedCount = $derived(folders.filter((f) => f.category_id !== null).length);
	const totalCount = $derived(folders.length);
	const unmappedCount = $derived(totalCount - mappedCount);
	const mappingPct = $derived(totalCount > 0 ? Math.round((mappedCount / totalCount) * 100) : 0);

	const filteredFolders = $derived(
		statusFilter === 'all' ? folders : folders.filter((f) => f.folder_status === statusFilter)
	);

	// === 마운트 ===
	onMount(async () => {
		await loadSettings();
		await loadCategories();
		await loadFolders();
	});

	// === 보존된 API 호출 ===
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

	let classifyStatus = $state('');

	async function classifyAllFolders() {
		classifyLoading = true;
		scanning = true;
		scanDone = false;
		progress = 0;
		classifyStatus = '';

		try {
			const res = await fetchWithTimeout('/api/ic/folders/classify', { method: 'POST' });

			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.detail || '폴더 분류 시작 실패');
			}

			// 폴링으로 진행률 확인
			const pollInterval = setInterval(async () => {
				try {
					const statusRes = await fetchWithTimeout('/api/ic/folders/classify/status');
					const status = await statusRes.json();

					if (status.total > 0) {
						progress = Math.round((status.processed / status.total) * 100);
						classifyStatus = `폴더 분류 중... (${status.processed}/${status.total})`;
					}

					if (!status.is_running) {
						clearInterval(pollInterval);
						progress = 100;
						scanDone = true;
						scanning = false;
						classifyLoading = false;
						classifyStatus = '';
						await loadFolders();
					}
				} catch {
					clearInterval(pollInterval);
					scanning = false;
					classifyLoading = false;
				}
			}, 1000);
		} catch (e: any) {
			alert(e.message);
			scanning = false;
			classifyLoading = false;
		}
	}

	async function requestAISuggestion(folder: Folder) {
		folder.ai_loading = true;
		folders = [...folders];

		try {
			const res = await fetchWithTimeout('/api/ic/folders/ai-suggest', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ folder_id: folder.id })
			});

			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.detail || '추천 실패');
			}

			const data = await res.json();
			folder.suggested_category = data.suggested_category;
			folders = [...folders];
		} catch (e) {
			console.error('AI 추천 실패:', e);
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

			if (!res.ok) throw new Error('매핑 저장 실패');

			folder.category_id = categoryId;
			folders = [...folders];
		} catch (e) {
			console.error('매핑 저장 실패:', e);
		}
	}

	async function applyInheritance(folderId: number) {
		try {
			const res = await fetchWithTimeout('/api/ic/folders/inherit', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ parent_folder_id: folderId, apply_to_children: true })
			});

			if (!res.ok) throw new Error('상속 적용 실패');

			const data = await res.json();
			await loadFolders();
		} catch (e) {
			console.error('상속 실패:', e);
		}
	}

	// === 보존된 헬퍼 ===
	function toggleFolder(folderId: number) {
		if (expandedFolders.has(folderId)) {
			expandedFolders.delete(folderId);
		} else {
			expandedFolders.add(folderId);
		}
		expandedFolders = new Set(expandedFolders);
	}

	function getCategoryName(categoryId: number | null): string {
		if (!categoryId) return '—';
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
				return { label: '명확', color: 'bg-emerald-100 text-emerald-700' };
			case 'unclear':
				return { label: '불명확', color: 'bg-yellow-100 text-yellow-700' };
			case 'flat':
				return { label: '플랫', color: 'bg-orange-100 text-orange-700' };
			case 'nested':
				return { label: '중첩', color: 'bg-violet-100 text-violet-700' };
			default:
				return { label: '미판정', color: 'bg-muted text-muted-foreground' };
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

	// === 추가 헬퍼 ===
	function toggleExtension(ext: string) {
		if (extensions.includes(ext)) {
			extensions = extensions.filter((e) => e !== ext);
		} else {
			extensions = [...extensions, ext];
		}
	}

	function removeScanRoot(path: string) {
		scanRoots = scanRoots.filter((r) => r !== path);
		saveScanRoots();
	}

	function addScanRoot() {
		const val = newFolderInput.trim();
		if (val && !scanRoots.includes(val)) {
			scanRoots = [...scanRoots, val];
			saveScanRoots();
		}
		newFolderInput = '';
	}

	async function loadSettings() {
		try {
			const res = await fetchWithTimeout('/api/ic/settings');
			if (res.ok) {
				const data = await res.json();
				scanRoots = data.scan_root_folders || [];
			}
		} catch (e) {
			console.error('설정 로드 실패:', e);
		}
	}

	async function saveScanRoots() {
		try {
			await fetchWithTimeout('/api/ic/settings', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ scan_root_folders: scanRoots })
			});
		} catch (e) {
			console.error('스캔 루트 저장 실패:', e);
		}
	}

	async function startScan() {
		if (scanRoots.length === 0) {
			alert('스캔 대상 폴더를 추가하세요.');
			return;
		}
		scanning = true;
		scanDone = false;
		progress = 0;

		try {
			const res = await fetchWithTimeout('/api/ic/scan/start', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ root_folders: scanRoots })
			});

			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.detail || '스캔 시작 실패');
			}

			// 폴링으로 진행률 확인
			const pollInterval = setInterval(async () => {
				try {
					const statusRes = await fetchWithTimeout('/api/ic/scan/status');
					const status = await statusRes.json();

					if (status.total_files > 0) {
						progress = Math.round((status.scanned_files / status.total_files) * 100);
					}

					if (!status.is_running) {
						clearInterval(pollInterval);
						progress = 100;
						scanDone = true;
						scanning = false;
						await loadFolders();
					}
				} catch {
					clearInterval(pollInterval);
					scanning = false;
				}
			}, 1000);
		} catch (e: any) {
			alert(e.message);
			scanning = false;
		}
	}
</script>

<svelte:head>
	<title>스캐너 — 이미지 분류기</title>
</svelte:head>

<div class="space-y-6">
	<!-- 헤더 -->
	<div>
		<div class="flex items-center gap-2">
			<FolderSearch class="size-5 text-primary" />
			<h1 class="text-2xl font-bold tracking-tight">스캐너</h1>
		</div>
		<p class="mt-1 text-sm text-muted-foreground">
			폴더를 카테고리에 매핑하여 전체 파일의 ~70%를 자동 분류합니다.
		</p>
	</div>

	<!-- 상단 2열 -->
	<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
		<!-- 스캔 대상 폴더 카드 -->
		<div class="rounded-lg border bg-card p-5">
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-2">
					<FolderOpen class="h-4 w-4 text-primary" />
					<h2 class="text-sm font-semibold">스캔 대상 폴더</h2>
				</div>
				<button
					onclick={() => {
						newFolderInput = 'D:\\';
					}}
					class="inline-flex items-center gap-1.5 rounded-md border bg-background px-2.5 py-1.5 text-xs font-medium hover:bg-accent transition-colors"
				>
					<Plus class="h-3.5 w-3.5" />
					폴더 추가
				</button>
			</div>

			{#if newFolderInput !== ''}
				<div class="flex gap-2 mb-3">
					<input
						bind:value={newFolderInput}
						placeholder="D:\Photos"
						class="flex-1 rounded-md border bg-background px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/50"
						onkeydown={(e) => e.key === 'Enter' && addScanRoot()}
					/>
					<button
						onclick={addScanRoot}
						class="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
					>
						추가
					</button>
					<button
						onclick={() => (newFolderInput = '')}
						class="rounded-md border px-3 py-1.5 text-xs font-medium hover:bg-accent transition-colors"
					>
						취소
					</button>
				</div>
			{/if}

			{#if scanRoots.length === 0}
				<div
					class="rounded-lg border-2 border-dashed border-border p-8 text-center text-muted-foreground"
				>
					<Folder class="h-8 w-8 mx-auto mb-2 opacity-30" />
					<p class="text-sm">폴더가 없습니다</p>
					<p class="text-xs mt-1">"폴더 추가"를 클릭하세요</p>
				</div>
			{:else}
				<div class="space-y-1">
					{#each scanRoots as root}
						<div
							class="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 group"
						>
							<span class="font-mono text-sm text-foreground truncate flex-1">{root}</span>
							<button
								onclick={() => removeScanRoot(root)}
								class="ml-2 shrink-0 rounded p-1 text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors opacity-0 group-hover:opacity-100"
							>
								<Trash2 class="h-3.5 w-3.5" />
							</button>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- 스캔 옵션 카드 -->
		<div class="rounded-lg border bg-card p-5">
			<h2 class="text-sm font-semibold mb-4">스캔 옵션</h2>

			<div class="mb-5">
				<p class="text-xs text-muted-foreground mb-2 font-medium uppercase tracking-wide">
					파일 확장자
				</p>
				<div class="flex flex-wrap gap-1.5">
					{#each ['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'raw', 'bmp', 'tiff'] as ext}
						<button
							onclick={() => toggleExtension(ext)}
							class="px-2.5 py-1 rounded-full text-xs font-medium border transition-colors
							{extensions.includes(ext)
								? 'bg-primary text-primary-foreground border-primary'
								: 'bg-background text-muted-foreground border-border hover:border-primary/50'}"
						>
							.{ext}
						</button>
					{/each}
				</div>
			</div>

			<div>
				<div class="flex items-center justify-between mb-1.5">
					<p class="text-xs text-muted-foreground font-medium uppercase tracking-wide">
						매핑 진행률
					</p>
					<span class="text-xs font-medium">{mappedCount}/{totalCount}개 폴더</span>
				</div>
				<div class="h-2 w-full rounded-full bg-muted overflow-hidden">
					<div
						class="h-full rounded-full bg-primary transition-all duration-500"
						style="width: {mappingPct}%"
					></div>
				</div>
				<p class="text-xs text-muted-foreground mt-1">{mappingPct}% 매핑됨</p>
			</div>
		</div>
	</div>

	<!-- 스캔 실행 카드 -->
	<div class="rounded-lg border bg-card p-5">
		<div class="flex items-center justify-between mb-4">
			<h2 class="text-sm font-semibold">스캔 실행</h2>
			<div class="flex gap-2">
				{#if scanning}
					<button
						onclick={() => {
							scanning = false;
							classifyLoading = false;
						}}
						class="inline-flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors"
					>
						<Square class="h-4 w-4" />
						스캔 중지
					</button>
				{:else}
					<button
						onclick={startScan}
						disabled={classifyLoading}
						class="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
					>
						<Play class="h-4 w-4" />
						스캔 시작
					</button>
				{/if}
				<button
					onclick={loadFolders}
					disabled={loading}
					class="inline-flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50 transition-colors"
				>
					<RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
					새로고침
				</button>
				<button
					onclick={classifyAllFolders}
					disabled={classifyLoading || totalCount === 0}
					class="inline-flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50 transition-colors"
				>
					<Brain class="h-4 w-4" />
					폴더 분류
				</button>
			</div>
		</div>

		{#if scanning}
			<div class="mb-4">
				<div class="flex justify-between text-xs text-muted-foreground mb-1">
					<span>{classifyStatus || '폴더 스캔 중...'}</span>
					<span>{progress}%</span>
				</div>
				<div class="h-2 w-full rounded-full bg-muted overflow-hidden">
					<div
						class="h-full rounded-full bg-primary transition-all duration-300"
						style="width: {progress}%"
					></div>
				</div>
			</div>
		{/if}

		{#if scanDone}
			<div
				class="mb-4 rounded-md border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 flex items-center gap-2"
			>
				<CheckCircle2 class="h-4 w-4 text-emerald-600 shrink-0" />
				<p class="text-sm text-emerald-700 font-medium">스캔 완료</p>
			</div>
		{/if}

		<!-- 카운터 3열 -->
		<div class="grid grid-cols-3 gap-4">
			<div class="rounded-md bg-muted/50 p-4 text-center">
				<div class="text-2xl font-bold">{totalCount.toLocaleString()}</div>
				<div class="text-xs text-muted-foreground mt-1">전체 폴더</div>
			</div>
			<div class="rounded-md bg-emerald-500/10 p-4 text-center">
				<div class="text-2xl font-bold text-emerald-700">{mappedCount.toLocaleString()}</div>
				<div class="text-xs text-muted-foreground mt-1">매핑됨</div>
			</div>
			<div class="rounded-md bg-amber-500/10 p-4 text-center">
				<div class="text-2xl font-bold text-amber-700">{unmappedCount.toLocaleString()}</div>
				<div class="text-xs text-muted-foreground mt-1">미매핑</div>
			</div>
		</div>
	</div>

	<!-- 폴더 목록 카드 -->
	<div class="rounded-lg border bg-card">
		<div class="flex items-center justify-between p-5 border-b">
			<h2 class="text-sm font-semibold">폴더 목록</h2>
			<select
				bind:value={statusFilter}
				onchange={loadFolders}
				class="rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
			>
				<option value="all">전체 상태</option>
				<option value="unknown">미분류</option>
				<option value="clear">명확</option>
				<option value="unclear">불명확</option>
				<option value="flat">플랫</option>
				<option value="nested">중첩</option>
			</select>
		</div>

		{#if loading}
			<div class="p-8 text-center">
				<RefreshCw class="h-6 w-6 animate-spin mx-auto mb-2 text-muted-foreground" />
				<p class="text-sm text-muted-foreground">폴더 로딩 중...</p>
			</div>
		{:else if filteredFolders.length === 0}
			<div class="p-8 text-center">
				<Folder class="h-8 w-8 mx-auto mb-2 opacity-30" />
				<p class="text-sm text-muted-foreground">폴더가 없습니다</p>
				<p class="text-xs text-muted-foreground mt-1">스캔을 실행하여 폴더를 인덱싱하세요</p>
			</div>
		{:else}
			<div class="divide-y divide-border">
				{#each filteredFolders as folder}
					{@const badge = getStatusBadge(folder.folder_status)}
					<div class="flex items-center gap-4 px-5 py-3 hover:bg-muted/30 transition-colors">
						<!-- 아이콘 + 경로 -->
						<div class="flex items-center gap-2 flex-1 min-w-0">
							<Folder class="h-4 w-4 text-muted-foreground shrink-0" />
							<span class="font-mono text-xs text-foreground truncate">{folder.folder_path}</span>
						</div>

						<!-- 파일 수 -->
						<div class="flex items-center gap-1 shrink-0 text-xs text-muted-foreground w-20 justify-end">
							<FileImage class="h-3.5 w-3.5" />
							{folder.file_count.toLocaleString()}
						</div>

						<!-- 상태 뱃지 -->
						<div class="shrink-0 w-20">
							<span class="inline-block px-2 py-0.5 rounded-full text-xs font-medium {badge.color}">
								{badge.label}
							</span>
						</div>

						<!-- AI 추천 -->
						<div class="shrink-0 w-28 text-xs">
							{#if folder.ai_loading}
								<span class="text-muted-foreground flex items-center gap-1">
									<RefreshCw class="h-3 w-3 animate-spin" />
									분석 중
								</span>
							{:else if folder.suggested_category}
								<span class="text-primary font-medium truncate block" title={folder.suggested_category}>
									{folder.suggested_category}
								</span>
							{:else}
								<button
									onclick={() => requestAISuggestion(folder)}
									class="flex items-center gap-1 text-muted-foreground hover:text-primary transition-colors"
								>
									<Brain class="h-3.5 w-3.5" />
									AI 추천
								</button>
							{/if}
						</div>

						<!-- 카테고리 드롭다운 -->
						<div class="shrink-0 w-40">
							<select
								value={folder.category_id || ''}
								onchange={(e) => {
									const val = (e.currentTarget as HTMLSelectElement).value;
									if (val) saveMapping(folder, parseInt(val));
								}}
								class="w-full rounded border bg-background px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-primary/50"
							>
								<option value="">— 선택 —</option>
								{#each flattenCategories(categories) as cat}
									<option value={cat.id}>{cat.full_path}</option>
								{/each}
							</select>
						</div>

						<!-- 하위 상속 버튼 -->
						<div class="shrink-0 w-20 text-right">
							{#if folder.category_id && folder.folder_status === 'nested'}
								<button
									onclick={() => applyInheritance(folder.id)}
									class="text-xs text-violet-600 hover:text-violet-800 hover:underline transition-colors"
								>
									하위 상속
								</button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
