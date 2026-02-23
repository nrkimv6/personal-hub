<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { toast } from '$lib/stores/toast';
	import { Copy, Wand2, Check, Trash2, SkipForward, Crown, PartyPopper, Square, ChevronLeft, ChevronRight, FolderOpen, X, ExternalLink, Eye, Clipboard, Merge, Archive } from 'lucide-svelte';

	interface DuplicateGroup {
		group_id: number;
		group_hash: string;
		member_count: number;
		status: string;
		kept_file_id: number | null;
	}

	interface DuplicateMember {
		file_id: number;
		file_path: string;
		file_size: number;
		resolution: string;
		quality_score: number;
		phash_distance: number;
		is_exact: boolean;
	}

	interface GroupDetail extends DuplicateGroup {
		members: DuplicateMember[];
	}

	let groups: DuplicateGroup[] = $state([]);
	let totalGroups = $state(0);
	let groupDetails = $state<Record<number, GroupDetail>>({});
	let loading = $state(true);
	let error = $state<string | null>(null);
	let filter = $state({ status: 'pending', skip: 0, limit: 50 });

	// 각 그룹에서 선택된 keep 파일 ID
	let selections = $state<Record<number, number | null>>({});

	interface FolderFile {
		file_id: number;
		file_path: string;
		file_size: number;
		resolution: string;
		quality_score: number;
		group_id: number;
	}

	interface FolderInfo {
		folder_path: string;
		file_count: number;
		group_ids: number[];
		files: FolderFile[];
	}

	let filterStatus = $state('unresolved');

	// 그룹 선택 (병합 + 일괄 확정 공용)
	let checkedGroups = $state(new Set<number>());

	// 카테고리 (보관 시 설정용)
	interface CategoryItem {
		id: number;
		name: string;
		full_path: string;
		children: CategoryItem[];
	}
	let flatCategoriesList = $state<CategoryItem[]>([]);
	// 그룹별 선택된 카테고리 ID
	let groupCategorySelections = $state<Record<number, number | ''>>({});

	let detectRunning = $state(false);
	let detectStatusPoller: ReturnType<typeof setInterval> | null = null;

	// 폴더 기준 일괄 해결 모달
	let showFolderModal = $state(false);
	let folderAnalysis = $state<FolderInfo[]>([]);
	let folderAnalysisLoading = $state(false);
	let selectedKeepFolder = $state<string | null>(null);
	let folderResolving = $state(false);
	let folderTotalPending = $state(0);

	const currentPage = $derived(Math.floor(filter.skip / filter.limit) + 1);
	const totalPages = $derived(Math.ceil(totalGroups / filter.limit));

	async function checkDetectStatus() {
		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/detect/status');
			if (!res.ok) return;
			const data = await res.json();
			detectRunning = data.is_running ?? false;
		} catch {
			// ignore
		}
	}

	async function stopDetect() {
		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/detect/stop', { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			detectRunning = false;
			toast.success('중복탐지가 중지되었습니다.');
			await loadGroups();
		} catch (err: any) {
			toast.error(`중지 실패: ${err.message}`);
		}
	}

	const filteredGroups = $derived(
		filterStatus === 'all'
			? groups
			: filterStatus === 'unresolved'
				? groups.filter((g) => g.status === 'pending')
				: groups.filter((g) => g.status === 'resolved')
	);

	const resolvedCount = $derived(groups.filter((g) => g.status === 'resolved').length);
	const allResolved = $derived(groups.length > 0 && resolvedCount === groups.length);

	async function loadGroups() {
		loading = true;
		error = null;
		try {
			const params = new URLSearchParams();
			params.set('skip', filter.skip.toString());
			params.set('limit', filter.limit.toString());
			if (filter.status !== 'all') {
				params.set('status', filter.status);
			}

			const res = await fetchWithTimeout(`/api/ic/duplicates?${params}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			groups = data.groups;
			totalGroups = data.total;

			// pending 그룹 자동 상세 fetch
			const pendingGroups = data.groups.filter((g: DuplicateGroup) => g.status === 'pending');
			await Promise.all(pendingGroups.map((g: DuplicateGroup) => loadGroupDetail(g.group_id)));
			autoSelectBySize();
		} catch (err: any) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	async function loadGroupDetail(groupId: number) {
		try {
			const res = await fetchWithTimeout(`/api/ic/duplicates/${groupId}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const detail = await res.json();
			groupDetails = { ...groupDetails, [groupId]: detail };
		} catch (err: any) {
			toast.error(`그룹 로드 실패: ${err.message}`);
		}
	}

	async function resolveGroup(groupId: number, keepFileId: number) {
		if (!confirm(`파일 ID ${keepFileId}를 보관하고 나머지를 휴지통으로 이동하시겠습니까?`)) {
			return;
		}

		const categoryId = groupCategorySelections[groupId] || undefined;

		try {
			const res = await fetchWithTimeout(`/api/ic/duplicates/${groupId}/resolve`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					keep_file_id: keepFileId,
					delete_others: true,
					...(categoryId ? { category_id: Number(categoryId) } : {})
				})
			});

			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const result = await res.json();

			toast.success(`해결 완료! 보관: ${result.kept_file_id}, 삭제: ${result.deleted_count}개`);

			// 로컬 상태 업데이트 (loadGroups() 전체 재호출 대신)
			groups = groups.filter((g) => g.group_id !== groupId);
			totalGroups = Math.max(0, totalGroups - 1);
			const { [groupId]: _detail, ...restDetails } = groupDetails;
			groupDetails = restDetails;
			const { [groupId]: _sel, ...restSel } = selections;
			selections = restSel;
			checkedGroups.delete(groupId);
			checkedGroups = new Set(checkedGroups);
		} catch (err: any) {
			toast.error(`해결 실패: ${err.message}`);
		}
	}

	function goToPage(page: number) {
		filter.skip = (page - 1) * filter.limit;
		selections = {};
		groupDetails = {};
		loadGroups();
	}

	function formatFileSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function getThumbnailUrl(fileId: number): string {
		return `/api/ic/files/${fileId}/thumbnail`;
	}

	function getBestMember(members: DuplicateMember[]): number {
		return members.reduce((best, m) => (m.quality_score > best.quality_score ? m : best), members[0])
			?.file_id;
	}

	function hasSameFileSize(members: DuplicateMember[]): boolean {
		if (members.length === 0) return true;
		const firstSize = members[0].file_size;
		return members.every((m) => m.file_size === firstSize);
	}

	function getLargestMember(members: DuplicateMember[]): number {
		return members.reduce((best, m) => (m.file_size > best.file_size ? m : best), members[0])
			?.file_id;
	}

	function autoSelectBySize() {
		const newSelections: Record<number, number | null> = { ...selections };
		for (const [groupIdStr, detail] of Object.entries(groupDetails)) {
			const groupId = Number(groupIdStr);
			if (detail.status !== 'pending') continue;
			if (!hasSameFileSize(detail.members)) {
				newSelections[groupId] = getLargestMember(detail.members);
			}
		}
		selections = newSelections;
	}

	function getFileName(path: string): string {
		return path.split('\\').pop() || path.split('/').pop() || path;
	}

	function getFolderPath(path: string): string {
		const lastBackslash = path.lastIndexOf('\\');
		const lastSlash = path.lastIndexOf('/');
		const idx = Math.max(lastBackslash, lastSlash);
		return idx >= 0 ? path.substring(0, idx) : path;
	}

	async function toggleGroupDetail(groupId: number) {
		if (groupDetails[groupId]) {
			const updated = { ...groupDetails };
			delete updated[groupId];
			groupDetails = updated;
		} else {
			await loadGroupDetail(groupId);
		}
	}

	async function discardAll(groupId: number) {
		const detail = groupDetails[groupId];
		const count = detail?.members?.length ?? '?';
		if (!confirm(`이 그룹의 모든 이미지(${count}개)를 휴지통으로 이동하시겠습니까?\n\n⚠️ 보관하는 파일 없이 전부 삭제됩니다.`)) return;

		try {
			const res = await fetchWithTimeout(`/api/ic/duplicates/${groupId}/discard-all`, { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const result = await res.json();
			toast.success(`모두 삭제 완료! 삭제: ${result.deleted_count}개`);
			// 로컬 상태 업데이트 (loadGroups() 전체 재호출 대신)
			groups = groups.filter((g) => g.group_id !== groupId);
			totalGroups = Math.max(0, totalGroups - 1);
			const { [groupId]: _detail, ...restDetails } = groupDetails;
			groupDetails = restDetails;
			const { [groupId]: _sel, ...restSel } = selections;
			selections = restSel;
			checkedGroups.delete(groupId);
			checkedGroups = new Set(checkedGroups);
		} catch (err: any) {
			toast.error(`삭제 실패: ${err.message}`);
		}
	}

	async function openLocal(path?: string, folder?: string, fileId?: number) {
		try {
			const body = fileId !== undefined ? { file_id: fileId } : { path, folder };
			await fetchWithTimeout('/api/ic/files/open-local', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			});
		} catch {
			// ignore
		}
	}

	async function openFolderExplorer(fileId: number) {
		try {
			const res = await fetchWithTimeout('/api/ic/files/open-folder', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_id: fileId })
			});
			if (!res.ok) {
				const err = await res.json();
				toast.error(err.detail || '탐색기 열기 실패');
			}
		} catch (err: any) {
			toast.error(`탐색기 열기 실패: ${err.message}`);
		}
	}

	async function copyPathToClipboard(path: string) {
		try {
			await navigator.clipboard.writeText(path);
			toast.success('경로 복사됨');
		} catch {
			toast.error('클립보드 복사 실패');
		}
	}

	async function keepAll(groupId: number) {
		const detail = groupDetails[groupId];
		const count = detail?.members?.length ?? '?';
		if (!confirm(`이 그룹의 모든 이미지(${count}개)를 보관하시겠습니까?\n(삭제 없이 해결됩니다)`)) return;
		try {
			const res = await fetchWithTimeout(`/api/ic/duplicates/${groupId}/keep-all`, { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const result = await res.json();
			toast.success(`모두 보관 완료! ${result.kept_count}개 파일 보관됨`);
			// 로컬 상태 업데이트 (loadGroups() 전체 재호출 대신)
			groups = groups.filter((g) => g.group_id !== groupId);
			totalGroups = Math.max(0, totalGroups - 1);
			const { [groupId]: _detail, ...restDetails } = groupDetails;
			groupDetails = restDetails;
			const { [groupId]: _sel, ...restSel } = selections;
			selections = restSel;
			checkedGroups.delete(groupId);
			checkedGroups = new Set(checkedGroups);
		} catch (err: any) {
			toast.error(`모두 보관 실패: ${err.message}`);
		}
	}

	async function mergeSelectedGroups() {
		const ids = Array.from(checkedGroups);
		if (ids.length < 2) {
			toast.warning('병합하려면 2개 이상의 그룹을 선택하세요.');
			return;
		}
		if (!confirm(`선택한 ${ids.length}개 그룹을 그룹 #${ids[0]}으로 병합하시겠습니까?`)) return;
		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/merge', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ group_ids: ids })
			});
			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.detail || '병합 실패');
			}
			const result = await res.json();
			toast.success(`병합 완료! 그룹 #${result.target_group_id}으로 ${ids.length - 1}개 그룹 병합됨`);
			// 로컬 상태 업데이트: 소스 그룹 제거, 타겟 그룹 상세 재로드
			const targetId = ids[0];
			const mergedIds = ids.slice(1);
			groups = groups.filter((g) => !mergedIds.includes(g.group_id));
			totalGroups = Math.max(0, totalGroups - mergedIds.length);
			mergedIds.forEach((id) => {
				const { [id]: _d, ...restD } = groupDetails; groupDetails = restD;
				const { [id]: _s, ...restS } = selections; selections = restS;
			});
			await loadGroupDetail(targetId);
			checkedGroups = new Set();
		} catch (err: any) {
			toast.error(`병합 실패: ${err.message}`);
		}
	}

	async function bulkResolve() {
		const ids = Array.from(checkedGroups);
		if (ids.length === 0) return;

		const resolutions = ids
			.map((gid) => {
				const detail = groupDetails[gid];
				const keepId = selections[gid] ?? (detail ? getBestMember(detail.members) : null);
				return { group_id: gid, keep_file_id: keepId };
			})
			.filter((r) => r.keep_file_id !== null);

		if (resolutions.length === 0) {
			toast.warning('확정할 그룹이 없습니다. 그룹을 펼쳐 보관 파일이 자동 선택되도록 하세요.');
			return;
		}
		if (resolutions.length < ids.length) {
			if (!confirm(`${ids.length}개 선택 중 ${resolutions.length}개만 확정 가능합니다.\n(나머지는 상세 로드 필요)\n\n계속하시겠습니까?`)) return;
		} else {
			if (!confirm(`선택한 ${resolutions.length}개 그룹을 일괄 확정하시겠습니까?`)) return;
		}

		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/bulk-resolve', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ resolutions })
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const result = await res.json();

			const msg = result.failed > 0
				? `일괄 확정 완료! 성공: ${result.resolved}개, 실패: ${result.failed}개`
				: `일괄 확정 완료! ${result.resolved}개 그룹 처리됨`;
			result.failed > 0 ? toast.warning(msg) : toast.success(msg);

			// 로컬 상태에서 resolved 그룹 제거
			const resolvedIds: number[] = result.resolved_group_ids ?? [];
			groups = groups.filter((g) => !resolvedIds.includes(g.group_id));
			totalGroups = Math.max(0, totalGroups - resolvedIds.length);
			resolvedIds.forEach((id) => {
				const { [id]: _d, ...restD } = groupDetails; groupDetails = restD;
				const { [id]: _s, ...restS } = selections; selections = restS;
			});
			checkedGroups = new Set();
		} catch (err: any) {
			toast.error(`일괄 확정 실패: ${err.message}`);
		}
	}

	async function openFolderModal() {
		showFolderModal = true;
		folderAnalysisLoading = true;
		selectedKeepFolder = null;
		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/folder-analysis');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			folderAnalysis = data.folders;
			folderTotalPending = data.total_pending_groups;
			if (data.folders.length > 0) {
				selectedKeepFolder = data.folders[0].folder_path;
			}
		} catch (err: any) {
			toast.error(`폴더 분석 실패: ${err.message}`);
			showFolderModal = false;
		} finally {
			folderAnalysisLoading = false;
		}
	}

	const selectedFolderInfo = $derived(folderAnalysis.find((f) => f.folder_path === selectedKeepFolder));
	const folderKeepFiles = $derived(selectedFolderInfo?.files ?? []);
	const folderDeleteFiles = $derived(
		selectedKeepFolder
			? folderAnalysis
					.filter((f) => f.folder_path !== selectedKeepFolder)
					.flatMap((f) => f.files.filter((file) => selectedFolderInfo?.group_ids.includes(file.group_id)))
			: []
	);
	const folderAffectedGroupIds = $derived(selectedFolderInfo?.group_ids ?? []);

	async function resolveByFolder() {
		if (!selectedKeepFolder || folderAffectedGroupIds.length === 0) return;
		if (!confirm(`${folderAffectedGroupIds.length}개 그룹을 일괄 해결하시겠습니까?\n\n보관 폴더: ${selectedKeepFolder}\n삭제 예정: ${folderDeleteFiles.length}개 파일`)) return;

		folderResolving = true;
		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/resolve-by-folder', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					keep_folder: selectedKeepFolder,
					group_ids: folderAffectedGroupIds
				})
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const result = await res.json();
			toast.success(`일괄 해결 완료! 보관: ${result.resolved_count}개 그룹, 삭제: ${result.deleted_count}개 파일`);
			showFolderModal = false;
			// 로컬 상태 업데이트: resolved 그룹 목록으로 필터링
			const resolvedIds = (result.details ?? []).map((d: { group_id: number }) => d.group_id);
			groups = groups.filter((g) => !resolvedIds.includes(g.group_id));
			totalGroups = Math.max(0, totalGroups - resolvedIds.length);
			resolvedIds.forEach((id: number) => {
				const { [id]: _d, ...restD } = groupDetails; groupDetails = restD;
				const { [id]: _s, ...restS } = selections; selections = restS;
				checkedGroups.delete(id);
			});
			checkedGroups = new Set(checkedGroups);
		} catch (err: any) {
			toast.error(`일괄 해결 실패: ${err.message}`);
		} finally {
			folderResolving = false;
		}
	}

	async function loadCategories() {
		try {
			const res = await fetchWithTimeout('/api/ic/categories?include_tree=true');
			if (res.ok) {
				const data = await res.json();
				const flat: CategoryItem[] = [];
				function flatten(cats: CategoryItem[]) {
					for (const cat of cats) {
						flat.push(cat);
						if (cat.children?.length) flatten(cat.children);
					}
				}
				flatten(data.categories || []);
				flatCategoriesList = flat;
			}
		} catch { /* ignore */ }
	}

	onMount(() => {
		loadGroups();
		loadCategories();
		checkDetectStatus();
		detectStatusPoller = setInterval(checkDetectStatus, 3000);
		return () => {
			if (detectStatusPoller) clearInterval(detectStatusPoller);
		};
	});
</script>

<!-- 헤더 -->
<div class="mb-4">
	<div class="flex items-center gap-2">
		<Copy class="size-5 text-primary" />
		<h2 class="text-xl font-bold tracking-tight">중복 이미지</h2>
	</div>
	<p class="mt-1 text-sm text-muted-foreground">pHash 기반 중복 이미지 탐지 및 정리</p>
</div>

<!-- 컨트롤 바 -->
<div class="rounded-xl border bg-card p-4 mb-6">
	<div class="flex items-center gap-4 flex-wrap">
		<!-- 통계 -->
		<div class="flex items-center gap-2 text-sm">
			{#if totalGroups > 0}
				<span class="font-medium">전체 {totalGroups}개 그룹</span>
				<span class="text-muted-foreground">|</span>
				<span class="text-muted-foreground">
					{filter.skip + 1}-{Math.min(filter.skip + filter.limit, totalGroups)} 표시 중
				</span>
				<span class="text-muted-foreground">|</span>
				<span class="text-muted-foreground">{resolvedCount}개 해결됨</span>
			{:else}
				<span class="font-medium">{groups.length}개 그룹</span>
				<span class="text-muted-foreground">|</span>
				<span class="text-muted-foreground">{resolvedCount}개 해결됨</span>
			{/if}
		</div>

		<!-- 필터 버튼 그룹 -->
		<div class="flex items-center rounded-lg border bg-muted/40 p-0.5 gap-0.5">
			{#each [['all', '전체'], ['unresolved', '미해결'], ['resolved', '해결됨']] as [val, label]}
				<button
					class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors {filterStatus === val
						? 'bg-background text-foreground shadow-sm'
						: 'text-muted-foreground hover:text-foreground'}"
					onclick={() => (filterStatus = val)}
				>
					{label}
				</button>
			{/each}
		</div>

		<!-- 중지 버튼 (탐지 실행 중일 때만 표시) -->
		{#if detectRunning}
			<button
				class="flex items-center gap-1.5 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors"
				onclick={stopDetect}
			>
				<Square class="size-3.5" />
				탐지 중지
			</button>
		{/if}

		<!-- 폴더 기준 일괄 해결 -->
		<button
			class="flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 transition-colors"
			onclick={openFolderModal}
		>
			<FolderOpen class="size-3.5" />
			폴더 기준 일괄 해결
		</button>

		<!-- 전체 선택 -->
		{#if filteredGroups.length > 0}
			<label class="flex items-center gap-1.5 cursor-pointer text-sm text-muted-foreground hover:text-foreground transition-colors">
				<input
					type="checkbox"
					checked={filteredGroups.every((g) => checkedGroups.has(g.group_id))}
					indeterminate={filteredGroups.some((g) => checkedGroups.has(g.group_id)) && !filteredGroups.every((g) => checkedGroups.has(g.group_id))}
					onchange={(e) => {
						if ((e.currentTarget as HTMLInputElement).checked) {
							checkedGroups = new Set(filteredGroups.map((g) => g.group_id));
						} else {
							checkedGroups = new Set();
						}
					}}
					class="h-4 w-4 rounded border-border cursor-pointer"
				/>
				전체 선택
			</label>
		{/if}

		<!-- 새로고침 -->
		<button
			class="ml-auto flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:bg-accent transition-colors"
			onclick={loadGroups}
		>
			<Wand2 class="size-3.5" />
			새로고침
		</button>
	</div>

	<!-- 그룹 선택 액션 바 (1개 이상 선택 시) -->
	{#if checkedGroups.size >= 1}
		<div class="mt-3 flex items-center gap-3 rounded-lg bg-primary/5 border border-primary/20 px-4 py-2 flex-wrap">
			<span class="text-sm font-medium text-primary">{checkedGroups.size}개 그룹 선택됨</span>
			<button
				class="flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-xs font-medium hover:bg-primary/90 transition-colors"
				onclick={bulkResolve}
			>
				<Check class="size-3.5" />
				{checkedGroups.size}개 일괄 확정
			</button>
			{#if checkedGroups.size >= 2}
				<button
					class="flex items-center gap-1.5 rounded-md bg-sky-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-sky-700 transition-colors"
					onclick={mergeSelectedGroups}
				>
					<Merge class="size-3.5" />
					선택 그룹 병합
				</button>
			{/if}
			<button
				class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent transition-colors"
				onclick={() => (checkedGroups = new Set())}
			>
				선택 해제
			</button>
		</div>
	{/if}
</div>

<!-- 로딩/에러 -->
{#if loading}
	<div class="rounded-xl border bg-card p-12 text-center">
		<div class="text-muted-foreground text-sm animate-pulse">중복 그룹 로딩 중...</div>
	</div>
{:else if error}
	<div class="rounded-xl border border-destructive/50 bg-destructive/5 p-6">
		<p class="text-destructive text-sm font-medium">오류: {error}</p>
	</div>
{:else if allResolved}
	<div class="rounded-xl border bg-card p-12 text-center">
		<PartyPopper class="size-12 text-primary mx-auto mb-3" />
		<p class="font-semibold text-lg">모든 중복 이미지 처리 완료!</p>
		<p class="text-muted-foreground text-sm mt-1">모든 중복 그룹이 처리되었습니다.</p>
	</div>
{:else if filteredGroups.length === 0}
	<div class="rounded-xl border bg-card p-12 text-center">
		<p class="text-muted-foreground text-sm">표시할 그룹이 없습니다.</p>
	</div>
{:else}
	<!-- 카드 리스트 내 액션 바는 컨트롤 바에 통합되어 제거 -->

	<!-- 그룹 카드 리스트 -->
	<div class="space-y-4">
		{#each filteredGroups as group (group.group_id)}
			{@const detail = groupDetails[group.group_id]}
			<div class="rounded-xl border bg-card overflow-hidden">
				<!-- 카드 헤더 -->
				<div class="flex items-center justify-between px-4 py-3 border-b bg-muted/20">
					<div class="flex items-center gap-3">
						<!-- 그룹 선택 체크박스 (일괄 확정 + 병합 공용) -->
						{#if group.status === 'pending'}
							<input
								type="checkbox"
								checked={checkedGroups.has(group.group_id)}
								onchange={() => {
									if (checkedGroups.has(group.group_id)) {
										checkedGroups.delete(group.group_id);
									} else {
										checkedGroups.add(group.group_id);
									}
									checkedGroups = new Set(checkedGroups);
								}}
								class="h-4 w-4 rounded border-border cursor-pointer"
								title="그룹 선택 (일괄 확정/병합)"
							/>
						{/if}
						<span class="font-mono text-sm font-semibold">Group #{group.group_id}</span>
						<span
							class="text-[11px] px-2 py-0.5 rounded-full font-medium {group.status === 'pending'
								? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
								: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'}"
						>
							{group.status === 'pending' ? '대기 중' : '해결됨'}
						</span>
						<span class="text-xs text-muted-foreground">{group.member_count}이미지</span>
						{#if detail && group.status === 'pending' && !hasSameFileSize(detail.members)}
							<span class="text-[11px] px-2 py-0.5 rounded-full font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
								큰 파일 자동 선택됨
							</span>
						{/if}
					</div>
					<div class="flex items-center gap-2">
						<button
							class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent transition-colors"
							onclick={() => toggleGroupDetail(group.group_id)}
						>
							<SkipForward class="size-3.5" />
							{detail ? '접기' : '펼치기'}
						</button>
						{#if group.status === 'pending' && detail}
							<button
								class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-destructive bg-destructive/10 hover:bg-destructive/20 transition-colors"
								onclick={() => discardAll(group.group_id)}
							>
								<Trash2 class="size-3.5" />
								모두 버리기
							</button>
							<button
								class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-emerald-700 bg-emerald-500/10 hover:bg-emerald-500/20 transition-colors"
								onclick={() => keepAll(group.group_id)}
							>
								<Check class="size-3.5" />
								모두 보관
							</button>
							{@const keepId = selections[group.group_id] ?? getBestMember(detail.members)}
							<!-- 카테고리 선택 드롭다운 -->
							{#if flatCategoriesList.length > 0}
								<select
									bind:value={groupCategorySelections[group.group_id]}
									class="rounded-md border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50"
								>
									<option value="">— 카테고리 —</option>
									{#each flatCategoriesList as cat}
										<option value={cat.id}>{cat.full_path}</option>
									{/each}
								</select>
							{/if}
							<button
								class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
								onclick={() => resolveGroup(group.group_id, keepId)}
							>
								<Check class="size-3.5" />
								보관 확정
							</button>
						{/if}
					</div>
				</div>

				<!-- 카드 바디 (확장 시) -->
				{#if detail}
					<div class="p-4">
						{#if !hasSameFileSize(detail.members)}
							<!-- 크기 다를 때: 선택된 이미지 크게 + 나머지 작게 -->
							{@const keepId = selections[group.group_id] ?? getLargestMember(detail.members)}
							{@const selectedMember = detail.members.find((m) => m.file_id === keepId)}
							{@const otherMembers = detail.members.filter((m) => m.file_id !== keepId)}
							<div class="flex gap-4">
								<!-- 선택된 이미지 (크게) -->
								{#if selectedMember}
									<div class="flex-shrink-0 w-64">
										<div class="relative aspect-[3/2] bg-muted rounded-lg overflow-hidden border-2 border-green-400 ring-2 ring-green-400/30">
											<img
												src={getThumbnailUrl(selectedMember.file_id)}
												alt="file {selectedMember.file_id}"
												class="w-full h-full object-cover"
												loading="lazy"
												decoding="async"
												onerror={(e) => {
													(e.currentTarget as HTMLImageElement).src =
														'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200"><rect width="300" height="200" fill="%23f3f4f6"/><text x="50%25" y="50%25" text-anchor="middle" dy=".3em" fill="%239ca3af" font-family="sans-serif">No Image</text></svg>';
												}}
											/>
											<div class="absolute top-1.5 left-1.5 rounded-full bg-green-500 text-white p-1 shadow">
												<Check class="size-3" />
											</div>
										</div>
										<div class="mt-2 space-y-0.5">
											<p class="text-xs font-semibold text-green-700 dark:text-green-400">보관 예정</p>
											<p class="text-[11px] font-mono truncate text-muted-foreground" title={selectedMember.file_path}>
												{getFileName(selectedMember.file_path)}
											</p>
											<p class="text-[11px] text-muted-foreground">{formatFileSize(selectedMember.file_size)} · {selectedMember.resolution}</p>
										</div>
									</div>
								{/if}
								<!-- 나머지 (작게) -->
								<div class="flex-1">
									<p class="text-xs text-muted-foreground mb-2">삭제 예정 ({otherMembers.length}개)</p>
									<div class="flex flex-wrap gap-2">
										{#each otherMembers as member (member.file_id)}
											<div class="w-24 rounded-lg border border-destructive/40 overflow-hidden opacity-60">
												<div class="relative aspect-square bg-muted">
													<img
														src={getThumbnailUrl(member.file_id)}
														alt="file {member.file_id}"
														class="w-full h-full object-cover"
														loading="lazy"
														decoding="async"
														onerror={(e) => {
															(e.currentTarget as HTMLImageElement).src =
																'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="%23f3f4f6"/><text x="50%25" y="50%25" text-anchor="middle" dy=".3em" fill="%239ca3af" font-family="sans-serif" font-size="10">No Image</text></svg>';
														}}
													/>
												</div>
												<div class="p-1">
													<p class="text-[10px] text-muted-foreground">{formatFileSize(member.file_size)}</p>
												</div>
											</div>
										{/each}
									</div>
								</div>
							</div>
						{:else}
							<!-- 크기 같을 때: 기존 그리드 + 폴더 경로 강조 -->
							<div class="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
								{#each detail.members as member (member.file_id)}
									{@const isBest = member.file_id === getBestMember(detail.members)}
									{@const isSelected = selections[group.group_id] === member.file_id}
									{@const isTrashed =
										selections[group.group_id] !== undefined &&
										selections[group.group_id] !== member.file_id}

									<div
										class="rounded-lg border overflow-hidden transition-all {isSelected
											? 'border-green-400 ring-2 ring-green-400/30'
											: isTrashed
												? 'border-destructive/40 opacity-60'
												: 'border-border hover:border-primary/40'}"
									>
										<!-- 썸네일 -->
										<div class="relative aspect-square bg-muted">
											<img
												src={getThumbnailUrl(member.file_id)}
												alt="file {member.file_id}"
												class="w-full h-full object-cover"
												loading="lazy"
												decoding="async"
												onerror={(e) => {
													(e.currentTarget as HTMLImageElement).src =
														'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300"><rect width="300" height="300" fill="%23f3f4f6"/><text x="50%25" y="50%25" text-anchor="middle" dy=".3em" fill="%239ca3af" font-family="sans-serif">No Image</text></svg>';
												}}
											/>
											{#if isBest}
												<div
													class="absolute top-1.5 left-1.5 rounded-full bg-yellow-400 text-yellow-900 p-1 shadow"
												>
													<Crown class="size-3" />
												</div>
											{/if}
											{#if member.is_exact}
												<div
													class="absolute top-1.5 right-1.5 rounded-full bg-destructive/90 text-destructive-foreground px-1.5 py-0.5 text-[10px] font-bold"
												>
													SHA256
												</div>
											{/if}
										</div>

										<!-- 정보 -->
										<div class="p-2 space-y-1.5 bg-card">
											<!-- 폴더 경로 (굵게) -->
											<p class="text-[11px] font-semibold truncate" title={getFolderPath(member.file_path)}>
												{getFolderPath(member.file_path)}
											</p>
											<!-- 파일명 (서브텍스트) -->
											<p class="text-[10px] font-mono truncate text-muted-foreground" title={member.file_path}>
												{getFileName(member.file_path)}
											</p>

											<!-- 품질 바 -->
											<div class="h-1 bg-muted rounded-full overflow-hidden">
												<div
													class="h-full bg-primary rounded-full"
													style="width: {Math.min(member.quality_score, 100)}%"
												></div>
											</div>

											<div class="flex items-center justify-between text-[10px] text-muted-foreground">
												<span>{formatFileSize(member.file_size)}</span>
												<span>{member.resolution}</span>
											</div>

											<!-- Keep/Trash 토글 -->
											{#if group.status === 'pending'}
												<div class="flex gap-1 pt-0.5">
													<button
														class="flex-1 flex items-center justify-center gap-1 rounded py-1 text-[11px] font-medium transition-colors {isSelected
															? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
															: 'text-muted-foreground hover:bg-muted'}"
														onclick={() => {
															selections = { ...selections, [group.group_id]: member.file_id };
														}}
													>
														<Check class="size-3" />
														보관
													</button>
													<button
														class="flex-1 flex items-center justify-center gap-1 rounded py-1 text-[11px] font-medium transition-colors {isTrashed
															? 'bg-destructive/10 text-destructive'
															: 'text-muted-foreground hover:bg-muted'}"
														onclick={() => {
															// 이 멤버를 trash로 표시 = 다른 멤버를 자동 keep
															const others = detail.members.filter(
																(m) => m.file_id !== member.file_id
															);
															if (others.length === 1) {
																selections = { ...selections, [group.group_id]: others[0].file_id };
															}
														}}
													>
														<Trash2 class="size-3" />
														버리기
													</button>
												</div>
											{/if}
											<!-- 경로/뷰어 액션 버튼 -->
											<div class="flex gap-1 pt-0.5">
												<button
													onclick={() => openLocal(undefined, undefined, member.file_id)}
													class="flex-1 flex items-center justify-center gap-0.5 rounded py-1 text-[10px] text-muted-foreground hover:bg-muted transition-colors"
													title="뷰어로 열기"
												>
													<Eye class="size-3" />
													뷰어
												</button>
												<button
													onclick={() => openFolderExplorer(member.file_id)}
													class="flex-1 flex items-center justify-center gap-0.5 rounded py-1 text-[10px] text-muted-foreground hover:bg-muted transition-colors"
													title="탐색기로 열기"
												>
													<FolderOpen class="size-3" />
													탐색기
												</button>
												<button
													onclick={() => copyPathToClipboard(member.file_path)}
													class="flex items-center justify-center rounded p-1 text-muted-foreground hover:bg-muted transition-colors"
													title="경로 복사"
												>
													<Clipboard class="size-3" />
												</button>
											</div>
										</div>
									</div>
								{/each}
							</div>
						{/if}
					</div>

					<!-- 카드 푸터 (resolved) -->
					{#if group.status === 'resolved'}
						<div class="px-4 py-3 border-t bg-emerald-500/5 dark:bg-emerald-900/10">
							<p class="text-xs text-green-700 dark:text-green-400 flex items-center gap-1.5">
								<Check class="size-3.5" />
								해결 완료: 파일 ID {group.kept_file_id} 보관
							</p>
						</div>
					{/if}
				{/if}
			</div>
		{/each}
	</div>

	<!-- 페이지네이션 바 -->
	{#if totalPages > 1}
		<div class="flex items-center justify-center gap-3 mt-6">
			<button
				class="flex items-center gap-1 rounded-lg border px-3 py-1.5 text-sm transition-colors {currentPage <= 1
					? 'opacity-40 cursor-not-allowed'
					: 'hover:bg-accent'}"
				onclick={() => currentPage > 1 && goToPage(currentPage - 1)}
				disabled={currentPage <= 1}
			>
				<ChevronLeft class="size-4" />
				이전
			</button>
			<span class="text-sm text-muted-foreground">
				{currentPage} / {totalPages}
			</span>
			<button
				class="flex items-center gap-1 rounded-lg border px-3 py-1.5 text-sm transition-colors {currentPage >= totalPages
					? 'opacity-40 cursor-not-allowed'
					: 'hover:bg-accent'}"
				onclick={() => currentPage < totalPages && goToPage(currentPage + 1)}
				disabled={currentPage >= totalPages}
			>
				다음
				<ChevronRight class="size-4" />
			</button>
		</div>
	{/if}
{/if}

<!-- 폴더 기준 일괄 해결 모달 -->
{#if showFolderModal}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onclick={() => (showFolderModal = false)}>
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="bg-card border rounded-2xl shadow-2xl w-[900px] max-h-[85vh] flex flex-col" onclick={(e) => e.stopPropagation()}>
			<!-- 모달 헤더 -->
			<div class="flex items-center justify-between px-6 py-4 border-b">
				<div>
					<h3 class="text-lg font-bold">폴더 기준 일괄 해결</h3>
					<p class="text-sm text-muted-foreground mt-0.5">보관할 폴더를 선택하면 나머지 폴더의 중복 파일이 삭제됩니다</p>
				</div>
				<button class="rounded-md p-1.5 hover:bg-muted transition-colors" onclick={() => (showFolderModal = false)}>
					<X class="size-5" />
				</button>
			</div>

			{#if folderAnalysisLoading}
				<div class="p-12 text-center">
					<div class="text-muted-foreground text-sm animate-pulse">폴더 분석 중...</div>
				</div>
			{:else if folderAnalysis.length === 0}
				<div class="p-12 text-center">
					<p class="text-muted-foreground text-sm">분석할 pending 그룹이 없습니다.</p>
				</div>
			{:else}
				<div class="flex-1 overflow-y-auto p-6 space-y-6">
					<!-- 폴더 선택 -->
					<div>
						<p class="text-sm font-semibold mb-3">보관할 폴더 선택</p>
						<div class="space-y-2">
							{#each folderAnalysis as folder}
								<label class="flex items-center gap-3 rounded-lg border p-3 cursor-pointer transition-colors hover:bg-muted/50 {selectedKeepFolder === folder.folder_path ? 'border-primary bg-primary/5' : ''}">
									<input
										type="radio"
										name="keep-folder"
										value={folder.folder_path}
										checked={selectedKeepFolder === folder.folder_path}
										onchange={() => (selectedKeepFolder = folder.folder_path)}
										class="accent-primary"
									/>
									<div class="flex-1 min-w-0">
										<p class="text-sm font-mono truncate" title={folder.folder_path}>{folder.folder_path}</p>
										<p class="text-xs text-muted-foreground mt-0.5">{folder.file_count}개 파일 · {folder.group_ids.length}개 그룹</p>
									</div>
									<button
										class="flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-accent transition-colors"
										onclick={(e) => { e.preventDefault(); openLocal(undefined, folder.folder_path); }}
									>
										<ExternalLink class="size-3" />
										폴더 열기
									</button>
								</label>
							{/each}
						</div>
					</div>

					<!-- 미리보기 -->
					{#if selectedKeepFolder}
						<div class="grid grid-cols-2 gap-4">
							<!-- 보관될 이미지 -->
							<div>
								<p class="text-sm font-semibold text-green-700 dark:text-green-400 mb-2">
									보관 ({folderKeepFiles.length}개)
								</p>
								<div class="grid grid-cols-3 gap-2 max-h-[300px] overflow-y-auto">
									{#each folderKeepFiles as file (file.file_id)}
										<button
											class="rounded-lg border-2 border-green-400/50 overflow-hidden text-left hover:border-green-400 transition-colors"
											onclick={() => openLocal(file.file_path)}
										>
											<div class="aspect-square bg-muted relative">
												<img
													src={getThumbnailUrl(file.file_id)}
													alt="file {file.file_id}"
													class="w-full h-full object-cover"
													loading="lazy"
												/>
												<div class="absolute top-1 left-1 rounded-full bg-green-500 text-white p-0.5">
													<Check class="size-2.5" />
												</div>
											</div>
											<div class="p-1">
												<p class="text-[9px] font-mono truncate text-muted-foreground" title={file.file_path}>
													{getFileName(file.file_path)}
												</p>
												<p class="text-[9px] text-muted-foreground">{formatFileSize(file.file_size)}</p>
											</div>
										</button>
									{/each}
								</div>
							</div>

							<!-- 삭제될 이미지 -->
							<div>
								<p class="text-sm font-semibold text-destructive mb-2">
									삭제 ({folderDeleteFiles.length}개)
								</p>
								<div class="grid grid-cols-3 gap-2 max-h-[300px] overflow-y-auto">
									{#each folderDeleteFiles as file (file.file_id)}
										<button
											class="rounded-lg border-2 border-destructive/30 overflow-hidden opacity-60 text-left hover:opacity-80 transition-opacity"
											onclick={() => openLocal(file.file_path)}
										>
											<div class="aspect-square bg-muted relative">
												<img
													src={getThumbnailUrl(file.file_id)}
													alt="file {file.file_id}"
													class="w-full h-full object-cover"
													loading="lazy"
												/>
												<div class="absolute top-1 left-1 rounded-full bg-destructive text-destructive-foreground p-0.5">
													<Trash2 class="size-2.5" />
												</div>
											</div>
											<div class="p-1">
												<p class="text-[9px] font-mono truncate text-muted-foreground" title={file.file_path}>
													{getFileName(file.file_path)}
												</p>
												<p class="text-[9px] text-muted-foreground">{formatFileSize(file.file_size)}</p>
											</div>
										</button>
									{/each}
								</div>
							</div>
						</div>
					{/if}
				</div>

				<!-- 모달 푸터 -->
				<div class="flex items-center justify-end gap-3 px-6 py-4 border-t">
					<button
						class="rounded-lg border px-4 py-2 text-sm hover:bg-accent transition-colors"
						onclick={() => (showFolderModal = false)}
					>
						취소
					</button>
					<button
						class="rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
						onclick={resolveByFolder}
						disabled={!selectedKeepFolder || folderAffectedGroupIds.length === 0 || folderResolving}
					>
						{folderResolving ? '처리 중...' : `일괄 해결 (${folderAffectedGroupIds.length}그룹)`}
					</button>
				</div>
			{/if}
		</div>
	</div>
{/if}
