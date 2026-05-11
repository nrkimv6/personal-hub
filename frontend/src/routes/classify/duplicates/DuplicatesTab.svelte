<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { toast } from '$lib/stores/toast';
	import { confirm } from '$lib/stores/confirm';
	import { getErrorMessage } from '$lib/utils/error';
	import { createSelection } from '$lib/utils/selection.svelte';
	import { Copy, Wand2, Check, Trash2, SkipForward, Crown, PartyPopper, Square, ChevronLeft, ChevronRight, FolderOpen, X, ExternalLink, Eye, Clipboard, Merge, Archive, LayoutGrid, LayoutList, HelpCircle } from 'lucide-svelte';

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

	// 뷰 모드: 카드뷰 | 갤러리뷰
	let viewMode = $state<'card' | 'gallery'>('card');

	// 갤러리 뷰 관련 state
	interface GalleryMember {
		file_id: number;
		file_path: string;
		file_size: number;
		resolution: string;
		quality_score: number;
		phash_distance: number;
		is_exact: boolean;
	}
	interface GalleryGroup {
		group_id: number;
		group_hash: string;
		member_count: number;
		status: string;
		members: GalleryMember[];
		auto_keep_file_id: number | null;
		confidence: 'high' | 'medium' | 'low';
	}
	interface GalleryStats {
		total: number;
		auto_resolvable: number;
		needs_review: number;
	}
	interface DuplicateTaskStatus {
		task_id: string;
		kind: string;
		status: 'queued' | 'running' | 'completed' | 'failed';
		result?: any;
		error_message?: string | null;
	}

	let galleryGroups = $state<GalleryGroup[]>([]);
	let galleryStats = $state<GalleryStats>({ total: 0, auto_resolvable: 0, needs_review: 0 });
	let galleryLoading = $state(false);
	let galleryFilter = $state<'all' | 'exact' | 'near'>('all');
	let gallerySkip = $state(0);
	const galleryLimit = 100;
	let expandedGroups = $state(new Set<number>());
	let galleryCurentSkip = $state(0); // 보충용 skip 추적

	// 진행률 표시
	let bulkProcessing = $state(false);
	let bulkResolved = $state(0);
	let bulkTotal = $state(0);

	// 그룹 선택 (병합 + 일괄 확정 공용) — Selection 유틸리티 사용
	const groupSelection = createSelection();

	// 스크롤 위치 유지
	let savedScrollY = $state(0);

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
	let detectPollFailCount = $state(0);

	// 폴더 기준 일괄 해결 모달
	let showFolderModal = $state(false);

	// 폴더 쌍 기준 해결 모달
	interface FolderPair {
		folder_a: string;
		folder_b: string;
		group_count: number;
		file_count: number;
		group_ids: number[];
	}
	let showFolderPairModal = $state(false);
	let folderPairs = $state<FolderPair[]>([]);
	let folderPairsLoading = $state(false);
	let selectedPair = $state<FolderPair | null>(null);
	let pairFilesA = $state<FolderFile[]>([]);
	let pairFilesB = $state<FolderFile[]>([]);
	let pairGroupIds = $state<number[]>([]);
	let loadingPairFiles = $state(false);
	let pairKeepFolder = $state<'a' | 'b' | null>(null);
	let pairResolving = $state(false);
	let folderAnalysis = $state<FolderInfo[]>([]);
	let folderAnalysisLoading = $state(false);
	let selectedKeepFolder = $state<string | null>(null);
	let folderResolving = $state(false);
	let folderTotalPending = $state(0);
	// 폴더 선택 시 로드되는 파일 상세 (on-demand)
	let folderFilesLoading = $state(false);
	let folderKeepFilesData = $state<FolderFile[]>([]);
	let folderDeleteFilesData = $state<FolderFile[]>([]);
	let folderFileGroupIds = $state<number[]>([]);

	const currentPage = $derived(Math.floor(filter.skip / filter.limit) + 1);
	const totalPages = $derived(Math.ceil(totalGroups / filter.limit));

	function wait(ms: number): Promise<void> {
		return new Promise((resolve) => setTimeout(resolve, ms));
	}

	async function runDuplicateTask<T>(endpoint: string, payload?: unknown, timeoutMs = 30000): Promise<T> {
		const init: RequestInit = { method: 'POST' };
		if (payload !== undefined) {
			init.headers = { 'Content-Type': 'application/json' };
			init.body = JSON.stringify(payload);
		}
		const res = await fetchWithTimeout(endpoint, init, timeoutMs);
		if (!res.ok) throw new Error(`HTTP ${res.status}`);
		const accepted = await res.json();
		const taskId = accepted.task_id;
		for (let attempt = 0; attempt < 120; attempt += 1) {
			const statusRes = await fetchWithTimeout(`/api/ic/duplicates/tasks/${taskId}`, {}, 10000);
			if (!statusRes.ok) throw new Error(`HTTP ${statusRes.status}`);
			const task = (await statusRes.json()) as DuplicateTaskStatus;
			if (task.status === 'completed') return task.result as T;
			if (task.status === 'failed') throw new Error(task.error_message ?? '작업이 실패했습니다.');
			await wait(1000);
		}
		throw new Error('작업 상태 확인 시간이 초과되었습니다.');
	}

	async function checkDetectStatus() {
		try {
			const res = await fetchWithTimeout('/api/ic/duplicates/detect/status');
			if (!res.ok) return;
			const data = await res.json();
			detectRunning = data.is_running ?? false;
			detectPollFailCount = 0;
		} catch {
			detectPollFailCount += 1;
			if (detectPollFailCount >= 3 && detectStatusPoller) {
				clearInterval(detectStatusPoller);
				detectStatusPoller = setInterval(checkDetectStatus, 15000);
			}
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
			toast.error(`중지 실패: ${getErrorMessage(err)}`);
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
			error = getErrorMessage(err);
		} finally {
			loading = false;
		}
	}

	async function loadGalleryGroups() {
		galleryLoading = true;
		try {
			const params = new URLSearchParams();
			params.set('skip', gallerySkip.toString());
			params.set('limit', galleryLimit.toString());
			params.set('filter', galleryFilter);
			params.set('auto_strategy', 'quality_best');

			const res = await fetchWithTimeout(`/api/ic/duplicates/review?${params}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			galleryGroups = data.groups ?? [];
			galleryStats = { total: data.total ?? 0, auto_resolvable: data.auto_resolvable ?? 0, needs_review: data.needs_review ?? 0 };
			galleryCurentSkip = gallerySkip + galleryGroups.length;
		} catch (err: any) {
			toast.error(`갤러리 로드 실패: ${getErrorMessage(err)}`);
		} finally {
			galleryLoading = false;
		}
	}

	async function fetchMoreGalleryGroups(skip: number, needed: number): Promise<GalleryGroup[]> {
		try {
			const params = new URLSearchParams();
			params.set('skip', skip.toString());
			params.set('limit', needed.toString());
			params.set('filter', galleryFilter);
			params.set('auto_strategy', 'quality_best');
			const res = await fetchWithTimeout(`/api/ic/duplicates/review?${params}`);
			if (!res.ok) return [];
			const data = await res.json();
			return data.groups ?? [];
		} catch {
			return [];
		}
	}

	async function loadGroupDetail(groupId: number) {
		try {
			const res = await fetchWithTimeout(`/api/ic/duplicates/${groupId}`);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const detail = await res.json();
			groupDetails = { ...groupDetails, [groupId]: detail };
		} catch (err: any) {
			toast.error(`그룹 로드 실패: ${getErrorMessage(err)}`);
		}
	}

	// 카드뷰: resolvedIds를 로컬에서 제거하고 부족분을 서버에서 보충
	async function removeAndFill(resolvedIds: number[]) {
		savedScrollY = window.scrollY;

		// 로컬 state에서 제거
		groups = groups.filter((g) => !resolvedIds.includes(g.group_id));
		totalGroups = Math.max(0, totalGroups - resolvedIds.length);
		resolvedIds.forEach((id) => {
			const { [id]: _d, ...restD } = groupDetails; groupDetails = restD;
			const { [id]: _s, ...restS } = selections; selections = restS;
			groupSelection.ids.delete(id);
		});
		groupSelection.ids = new Set(groupSelection.ids);

		// 현재 표시 수가 limit 미만이면 서버에서 추가 fetch
		if (groups.length < filter.limit && totalGroups > groups.length) {
			try {
				const needed = filter.limit - groups.length;
				const params = new URLSearchParams();
				params.set('skip', (filter.skip + groups.length).toString());
				params.set('limit', needed.toString());
				if (filter.status !== 'all') params.set('status', filter.status);

				const res = await fetchWithTimeout(`/api/ic/duplicates?${params}`);
				if (res.ok) {
					const data = await res.json();
					const moreGroups: DuplicateGroup[] = data.groups ?? [];
					groups = [...groups, ...moreGroups];

					// 추가된 그룹의 상세 fetch
					const morePending = moreGroups.filter((g) => g.status === 'pending');
					await Promise.all(morePending.map((g) => loadGroupDetail(g.group_id)));
					autoSelectBySize();
				}
			} catch { /* 보충 실패 무시 */ }
		}

		window.scrollTo(0, savedScrollY);
	}

	// 갤러리뷰: resolvedIds를 제거하고 보충
	async function galleryRemoveAndFill(resolvedIds: number[]) {
		savedScrollY = window.scrollY;

		const prevCount = galleryGroups.length;
		galleryGroups = galleryGroups.filter((g) => !resolvedIds.includes(g.group_id));
		galleryStats.total = Math.max(0, galleryStats.total - resolvedIds.length);

		if (galleryGroups.length < galleryLimit && galleryGroups.length < galleryStats.total) {
			const needed = galleryLimit - galleryGroups.length;
			const more = await fetchMoreGalleryGroups(galleryCurentSkip, needed);
			galleryGroups = [...galleryGroups, ...more];
			galleryCurentSkip += more.length;
		}

		window.scrollTo(0, savedScrollY);
	}

	async function resolveGroup(groupId: number, keepFileId: number) {
		if (!await confirm({
			title: '중복 그룹 해결',
			message: `파일 ID ${keepFileId}를 보관하고 나머지를 휴지통으로 이동하시겠습니까?`,
			confirmText: '이동',
			variant: 'danger'
		})) {
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
			await removeAndFill([groupId]);
		} catch (err: any) {
			toast.error(`해결 실패: ${getErrorMessage(err)}`);
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
		if (!await confirm({
			title: '전체 삭제',
			message: `이 그룹의 모든 이미지(${count}개)를 휴지통으로 이동하시겠습니까?\n\n보관하는 파일 없이 전부 삭제됩니다.`,
			confirmText: '삭제',
			variant: 'danger'
		})) return;

		try {
			const res = await fetchWithTimeout(`/api/ic/duplicates/${groupId}/discard-all`, { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const result = await res.json();
			toast.success(`모두 삭제 완료! 삭제: ${result.deleted_count}개`);
			await removeAndFill([groupId]);
		} catch (err: any) {
			toast.error(`삭제 실패: ${getErrorMessage(err)}`);
		}
	}

	async function openLocal(path?: string, folder?: string, fileId?: number) {
		try {
			const body = fileId !== undefined ? { file_id: fileId } : { path, folder };
			const res = await fetchWithTimeout('/api/ic/files/open-local', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body)
			});
			if (!res.ok) {
				toast.error('폴더 열기 실패');
			}
		} catch {
			toast.error('폴더 열기 실패');
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
			toast.error(`탐색기 열기 실패: ${getErrorMessage(err)}`);
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
		if (!await confirm({
			title: '전체 보관',
			message: `이 그룹의 모든 이미지(${count}개)를 보관하시겠습니까?\n(삭제 없이 해결됩니다)`,
			confirmText: '보관'
		})) return;
		try {
			const res = await fetchWithTimeout(`/api/ic/duplicates/${groupId}/keep-all`, { method: 'POST' });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const result = await res.json();
			toast.success(`모두 보관 완료! ${result.kept_count}개 파일 보관됨`);
			await removeAndFill([groupId]);
		} catch (err: any) {
			toast.error(`모두 보관 실패: ${getErrorMessage(err)}`);
		}
	}

	async function mergeSelectedGroups() {
		const ids = groupSelection.toArray();
		if (ids.length < 2) {
			toast.warning('병합하려면 2개 이상의 그룹을 선택하세요.');
			return;
		}
		if (!await confirm({
			title: '그룹 병합',
			message: `선택한 ${ids.length}개 그룹을 그룹 #${ids[0]}으로 병합하시겠습니까?`,
			confirmText: '병합'
		})) return;
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
			groupSelection.clear();
		} catch (err: any) {
			toast.error(`병합 실패: ${getErrorMessage(err)}`);
		}
	}

	async function bulkResolve() {
		const ids = groupSelection.toArray();
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
			if (!await confirm({
				title: '일괄 확정',
				message: `${ids.length}개 선택 중 ${resolutions.length}개만 확정 가능합니다.\n(나머지는 상세 로드 필요)\n\n계속하시겠습니까?`,
				confirmText: '계속'
			})) return;
		} else {
			if (!await confirm({
				title: '일괄 확정',
				message: `선택한 ${resolutions.length}개 그룹을 일괄 확정하시겠습니까?`,
				confirmText: '확정'
			})) return;
		}

		try {
			const result = await runDuplicateTask<any>('/api/ic/duplicates/bulk-resolve/tasks', { resolutions });

			const msg = result.failed > 0
				? `일괄 확정 완료! 성공: ${result.resolved}개, 실패: ${result.failed}개`
				: `일괄 확정 완료! ${result.resolved}개 그룹 처리됨`;
			result.failed > 0 ? toast.warning(msg) : toast.success(msg);

			const resolvedIds: number[] = result.resolved_group_ids ?? [];
			await removeAndFill(resolvedIds);
		} catch (err: any) {
			toast.error(`일괄 확정 실패: ${getErrorMessage(err)}`);
		}
	}

	// 갤러리: 자동선택 전체 확정 (confidence=high 그룹)
	async function galleryAutoResolveAll() {
		const highIds = galleryGroups.filter((g) => g.confidence === 'high').map((g) => g.group_id);
		if (highIds.length === 0) {
			toast.warning('자동 확정 가능한 그룹이 없습니다.');
			return;
		}
		bulkProcessing = true;
		bulkTotal = highIds.length;
		bulkResolved = 0;
		try {
			const result = await runDuplicateTask<any>('/api/ic/duplicates/auto-resolve/tasks', { filter: galleryFilter, strategy: 'quality_best', group_ids: highIds });
			bulkResolved = result.resolved ?? 0;
			toast.success(`자동 확정 완료! ${result.resolved}개 그룹 처리됨`);
			await galleryRemoveAndFill(highIds);
		} catch (err: any) {
			toast.error(`자동 확정 실패: ${getErrorMessage(err)}`);
		} finally {
			bulkProcessing = false;
		}
	}

	// 갤러리: 선택된 그룹 확정
	async function galleryResolveSelected() {
		const ids = groupSelection.toArray();
		if (ids.length === 0) {
			toast.warning('선택된 그룹이 없습니다.');
			return;
		}
		bulkProcessing = true;
		bulkTotal = ids.length;
		bulkResolved = 0;
		try {
			const result = await runDuplicateTask<any>('/api/ic/duplicates/auto-resolve/tasks', { filter: galleryFilter, strategy: 'quality_best', group_ids: ids });
			bulkResolved = result.resolved ?? 0;
			toast.success(`선택 확정 완료! ${result.resolved}개 그룹 처리됨`);
			groupSelection.clear();
			await galleryRemoveAndFill(ids);
		} catch (err: any) {
			toast.error(`선택 확정 실패: ${getErrorMessage(err)}`);
		} finally {
			bulkProcessing = false;
		}
	}

	async function openFolderPairModal() {
		showFolderPairModal = true;
		folderPairsLoading = true;
		folderPairs = [];
		selectedPair = null;
		pairFilesA = [];
		pairFilesB = [];
		pairGroupIds = [];
		pairKeepFolder = null;
		try {
			const data = await runDuplicateTask<any>('/api/ic/duplicates/folder-pair-analysis/tasks');
			folderPairs = data.pairs;
		} catch (err: any) {
			toast.error(`폴더 쌍 분석 실패: ${getErrorMessage(err)}`);
			showFolderPairModal = false;
		} finally {
			folderPairsLoading = false;
		}
	}

	async function loadFolderPairFiles(pair: FolderPair) {
		selectedPair = pair;
		pairFilesA = [];
		pairFilesB = [];
		pairGroupIds = [];
		pairKeepFolder = null;
		loadingPairFiles = true;
		try {
			const params = new URLSearchParams({
				folder_a: pair.folder_a,
				folder_b: pair.folder_b,
			});
			const res = await fetchWithTimeout(`/api/ic/duplicates/folder-pair-analysis/files?${params}`, {}, 60000);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			pairFilesA = data.files_a;
			pairFilesB = data.files_b;
			pairGroupIds = data.group_ids;
		} catch (err: any) {
			toast.error(`파일 목록 로드 실패: ${getErrorMessage(err)}`);
		} finally {
			loadingPairFiles = false;
		}
	}

	async function resolveByFolderPair() {
		if (!selectedPair || !pairKeepFolder || pairGroupIds.length === 0) return;
		const keepFolder = pairKeepFolder === 'a' ? selectedPair.folder_a : selectedPair.folder_b;
		const otherFolder = pairKeepFolder === 'a' ? selectedPair.folder_b : selectedPair.folder_a;
		if (!await confirm({
			title: '폴더 쌍 해결',
			message: `${pairGroupIds.length}개 그룹을 일괄 해결하시겠습니까?\n\n보관 폴더: ${keepFolder}\n삭제 대상 폴더: ${otherFolder}`,
			confirmText: '해결',
			variant: 'danger'
		})) return;

		pairResolving = true;
		try {
			const result = await runDuplicateTask<any>('/api/ic/duplicates/resolve-by-folder-pair/tasks', {
				keep_folder: keepFolder,
				other_folder: otherFolder,
				group_ids: pairGroupIds,
			});
			toast.success(`폴더 쌍 해결 완료! 보관: ${result.resolved_count}개 그룹, 삭제: ${result.deleted_count}개 파일`);
			showFolderPairModal = false;
			const resolvedIds = (result.details ?? []).map((d: { group_id: number }) => d.group_id);
			await removeAndFill(resolvedIds);
		} catch (err: any) {
			toast.error(`폴더 쌍 해결 실패: ${getErrorMessage(err)}`);
		} finally {
			pairResolving = false;
		}
	}

	async function openFolderModal() {
		showFolderModal = true;
		folderAnalysisLoading = true;
		selectedKeepFolder = null;
		folderKeepFilesData = [];
		folderDeleteFilesData = [];
		folderFileGroupIds = [];
		try {
			// 요약만 로드 (파일 상세 없이 폴더 목록 + 카운트만)
			const data = await runDuplicateTask<any>('/api/ic/duplicates/folder-analysis/tasks');
			folderAnalysis = data.folders;
			folderTotalPending = data.total_pending_groups;
		} catch (err: any) {
			toast.error(`폴더 분석 실패: ${getErrorMessage(err)}`);
			showFolderModal = false;
		} finally {
			folderAnalysisLoading = false;
		}
	}

	async function loadFolderFiles(folderPath: string) {
		selectedKeepFolder = folderPath;
		folderFilesLoading = true;
		folderKeepFilesData = [];
		folderDeleteFilesData = [];
		folderFileGroupIds = [];
		try {
			const res = await fetchWithTimeout(
				`/api/ic/duplicates/folder-analysis/files?folder=${encodeURIComponent(folderPath)}`,
				{},
				60000
			);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data = await res.json();
			folderKeepFilesData = data.keep_files;
			folderDeleteFilesData = data.delete_files;
			folderFileGroupIds = data.group_ids;
		} catch (err: any) {
			toast.error(`파일 목록 로드 실패: ${getErrorMessage(err)}`);
		} finally {
			folderFilesLoading = false;
		}
	}

	const selectedFolderInfo = $derived(folderAnalysis.find((f) => f.folder_path === selectedKeepFolder));
	const folderKeepFiles = $derived(folderKeepFilesData);
	const folderDeleteFiles = $derived(folderDeleteFilesData);
	const folderAffectedGroupIds = $derived(folderFileGroupIds);

	async function resolveByFolder() {
		if (!selectedKeepFolder || folderAffectedGroupIds.length === 0) return;
		if (!await confirm({
			title: '폴더 기준 해결',
			message: `${folderAffectedGroupIds.length}개 그룹을 일괄 해결하시겠습니까?\n\n보관 폴더: ${selectedKeepFolder}\n삭제 예정: ${folderDeleteFiles.length}개 파일`,
			confirmText: '해결',
			variant: 'danger'
		})) return;

		folderResolving = true;
		try {
			const result = await runDuplicateTask<any>('/api/ic/duplicates/resolve-by-folder/tasks', {
				keep_folder: selectedKeepFolder,
				group_ids: folderAffectedGroupIds
			});
			toast.success(`일괄 해결 완료! 보관: ${result.resolved_count}개 그룹, 삭제: ${result.deleted_count}개 파일`);
			showFolderModal = false;
			const resolvedIds = (result.details ?? []).map((d: { group_id: number }) => d.group_id);
			await removeAndFill(resolvedIds);
		} catch (err: any) {
			toast.error(`일괄 해결 실패: ${getErrorMessage(err)}`);
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
	<div class="flex items-center justify-between gap-2">
		<div class="flex items-center gap-2">
			<Copy class="size-5 text-primary" />
			<h2 class="text-xl font-bold tracking-tight">중복 이미지</h2>
		</div>
		<!-- 뷰 모드 토글 -->
		<div class="flex items-center rounded-lg border bg-muted/40 p-0.5 gap-0.5">
			<button
				class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors {viewMode === 'card' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
				onclick={() => { viewMode = 'card'; }}
			>
				<LayoutList class="size-3.5" />
				카드뷰
			</button>
			<button
				class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors {viewMode === 'gallery' ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
				onclick={() => { viewMode = 'gallery'; gallerySkip = 0; loadGalleryGroups(); }}
			>
				<LayoutGrid class="size-3.5" />
				갤러리뷰
			</button>
		</div>
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

		<!-- 폴더 쌍 기준 해결 -->
		<button
			class="flex items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/5 px-3 py-1.5 text-sm font-medium text-sky-600 hover:bg-sky-500/10 transition-colors"
			onclick={openFolderPairModal}
		>
			<FolderOpen class="size-3.5" />
			폴더 쌍 기준 해결
		</button>

		<!-- 전체 선택 (카드뷰만) -->
		{#if viewMode === 'card' && filteredGroups.length > 0}
			<label class="flex items-center gap-1.5 cursor-pointer text-sm text-muted-foreground hover:text-foreground transition-colors">
				<input
					type="checkbox"
					checked={groupSelection.isAllSelected(filteredGroups.map((g) => g.group_id))}
					indeterminate={filteredGroups.some((g) => groupSelection.has(g.group_id)) && !groupSelection.isAllSelected(filteredGroups.map((g) => g.group_id))}
					onchange={() => groupSelection.selectAll(filteredGroups.map((g) => g.group_id))}
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

	<!-- 그룹 선택 액션 바 (1개 이상 선택 시, 카드뷰) -->
	{#if viewMode === 'card' && groupSelection.count >= 1}
		<div class="mt-3 flex items-center gap-3 rounded-lg bg-primary/5 border border-primary/20 px-4 py-2 flex-wrap">
			<span class="text-sm font-medium text-primary">{groupSelection.count}개 그룹 선택됨</span>
			<button
				class="flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-xs font-medium hover:bg-primary/90 transition-colors"
				onclick={bulkResolve}
			>
				<Check class="size-3.5" />
				{groupSelection.count}개 일괄 확정
			</button>
			{#if groupSelection.count >= 2}
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
				onclick={() => groupSelection.clear()}
			>
				선택 해제
			</button>
		</div>
	{/if}
</div>

<!-- 갤러리 뷰 -->
{#if viewMode === 'gallery'}
	<!-- 갤러리 컨트롤 바 -->
	<div class="rounded-xl border bg-card p-4 mb-4">
		<div class="flex items-center gap-4 flex-wrap">
			<!-- 통계 -->
			<div class="text-sm text-muted-foreground">
				전체 <span class="font-medium text-foreground">{galleryStats.total}</span>개 |
				자동확정가능 <span class="font-medium text-green-600">{galleryStats.auto_resolvable}</span>개 |
				수동검토필요 <span class="font-medium text-red-500">{galleryStats.needs_review}</span>개
			</div>

			<!-- 필터 버튼 그룹 -->
			<div class="flex items-center rounded-lg border bg-muted/40 p-0.5 gap-0.5">
				{#each [['all', '전체'], ['exact', 'Exact'], ['near', 'Near']] as [val, label]}
					<button
						class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors {galleryFilter === val ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}"
						onclick={() => { galleryFilter = val as 'all' | 'exact' | 'near'; gallerySkip = 0; loadGalleryGroups(); }}
					>{label}</button>
				{/each}
			</div>

			<!-- 일괄 액션 -->
			{#if bulkProcessing}
				<span class="text-sm text-muted-foreground animate-pulse">처리 중... {bulkResolved}/{bulkTotal} 그룹</span>
			{:else}
				<button
					class="flex items-center gap-1.5 rounded-lg bg-green-600 text-white px-3 py-1.5 text-sm font-medium hover:bg-green-700 transition-colors"
					onclick={galleryAutoResolveAll}
				>
					<Check class="size-3.5" />
					자동선택 전체 확정
				</button>
				{#if groupSelection.count > 0}
					<button
						class="flex items-center gap-1.5 rounded-lg bg-primary text-primary-foreground px-3 py-1.5 text-sm font-medium hover:bg-primary/90 transition-colors"
						onclick={galleryResolveSelected}
					>
						<Check class="size-3.5" />
						선택 확정 ({groupSelection.count}개)
					</button>
					<button
						class="rounded-lg border px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent transition-colors"
						onclick={() => groupSelection.clear()}
					>선택 해제</button>
				{/if}
			{/if}

			<button
				class="ml-auto flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:bg-accent transition-colors"
				onclick={() => { gallerySkip = 0; loadGalleryGroups(); }}
			>
				<Wand2 class="size-3.5" />
				새로고침
			</button>
		</div>
	</div>

	<!-- 갤러리 그룹 목록 -->
	{#if galleryLoading}
		<div class="rounded-xl border bg-card p-12 text-center">
			<div class="text-muted-foreground text-sm animate-pulse">갤러리 로딩 중...</div>
		</div>
	{:else if galleryGroups.length === 0}
		<div class="rounded-xl border bg-card p-12 text-center">
			<p class="text-muted-foreground text-sm">표시할 그룹이 없습니다.</p>
		</div>
	{:else}
		<div class="space-y-2">
			{#each galleryGroups as gGroup (gGroup.group_id)}
				{@const isExpanded = expandedGroups.has(gGroup.group_id)}
				{@const keepMember = gGroup.members.find((m) => m.file_id === gGroup.auto_keep_file_id)}
				{@const deleteMembers = gGroup.members.filter((m) => m.file_id !== gGroup.auto_keep_file_id)}

				<!-- 갤러리 행 -->
				<div class="rounded-xl border bg-card overflow-hidden">
					<!-- 컴팩트 행 -->
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						class="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-muted/30 transition-colors"
						onclick={() => {
							const next = new Set(expandedGroups);
							if (next.has(gGroup.group_id)) { next.delete(gGroup.group_id); } else { next.add(gGroup.group_id); }
							expandedGroups = next;
						}}
					>
						<!-- 선택 체크박스 -->
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<div onclick={(e) => e.stopPropagation()}>
							<input
								type="checkbox"
								checked={groupSelection.has(gGroup.group_id)}
								onchange={() => groupSelection.toggle(gGroup.group_id)}
								class="h-4 w-4 rounded border-border cursor-pointer"
							/>
						</div>

						<!-- confidence 뱃지 -->
						{#if gGroup.confidence === 'high'}
							<div class="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" title="자동 선택 가능">
								<Check class="size-3.5" />
							</div>
						{:else if gGroup.confidence === 'medium'}
							<div class="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400" title="추천 선택">
								<Check class="size-3.5" />
							</div>
						{:else}
							<div class="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400" title="수동 선택 필요">
								<HelpCircle class="size-3.5" />
							</div>
						{/if}

						<!-- 보관 파일 (좌측) -->
						{#if keepMember}
							<div class="flex items-center gap-2 flex-shrink-0 w-52">
								<div class="relative w-12 h-12 rounded-md overflow-hidden border-2 border-green-400 flex-shrink-0">
									<img src={getThumbnailUrl(keepMember.file_id)} alt="keep" class="w-full h-full object-cover" loading="lazy" />
								</div>
								<div class="min-w-0">
									<p class="text-xs font-mono truncate text-green-700 dark:text-green-400" title={keepMember.file_path}>{getFileName(keepMember.file_path)}</p>
									<p class="text-[10px] text-muted-foreground">{formatFileSize(keepMember.file_size)}</p>
								</div>
							</div>
						{/if}

						<!-- 구분선 -->
						<div class="text-muted-foreground text-xs">→</div>

						<!-- 삭제 파일들 (우측) -->
						<div class="flex items-center gap-1.5 flex-1 overflow-x-auto">
							{#each deleteMembers.slice(0, 6) as dm (dm.file_id)}
								<div class="relative flex-shrink-0 w-10 h-10 rounded overflow-hidden border border-muted opacity-50">
									<img src={getThumbnailUrl(dm.file_id)} alt="delete" class="w-full h-full object-cover" loading="lazy" />
								</div>
							{/each}
							{#if deleteMembers.length > 6}
								<span class="text-xs text-muted-foreground flex-shrink-0">+{deleteMembers.length - 6}</span>
							{/if}
						</div>

						<!-- 정보 -->
						<div class="flex-shrink-0 text-right">
							<p class="text-xs text-muted-foreground">#{gGroup.group_id}</p>
							<p class="text-[10px] text-muted-foreground">{gGroup.member_count}이미지</p>
						</div>

						<!-- 액션 버튼 (개별) -->
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<div class="flex items-center gap-1.5 flex-shrink-0" onclick={(e) => e.stopPropagation()}>
							{#if gGroup.auto_keep_file_id}
								<button
									class="flex items-center gap-1 rounded-md bg-primary text-primary-foreground px-2 py-1 text-xs font-medium hover:bg-primary/90 transition-colors"
									onclick={async () => {
										try {
											const res = await fetchWithTimeout(`/api/ic/duplicates/${gGroup.group_id}/resolve`, {
												method: 'POST',
												headers: { 'Content-Type': 'application/json' },
												body: JSON.stringify({ keep_file_id: gGroup.auto_keep_file_id, delete_others: true })
											});
											if (!res.ok) throw new Error(`HTTP ${res.status}`);
											toast.success('확정 완료');
											await galleryRemoveAndFill([gGroup.group_id]);
										} catch (err: any) {
											toast.error(`확정 실패: ${getErrorMessage(err)}`);
										}
									}}
								>
									<Check class="size-3" />
									확정
								</button>
							{/if}
							<button
								class="flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-accent transition-colors"
								onclick={() => {
									const next = new Set(expandedGroups);
									if (next.has(gGroup.group_id)) { next.delete(gGroup.group_id); } else { next.add(gGroup.group_id); }
									expandedGroups = next;
								}}
							>
								{isExpanded ? '접기' : '상세'}
							</button>
						</div>
					</div>

					<!-- 인라인 확장: 기존 카드뷰 상세 -->
					{#if isExpanded}
						<div class="border-t p-4">
							<p class="text-xs text-muted-foreground mb-3">그룹 #{gGroup.group_id} 상세 — 보관 파일을 선택하고 확정하세요</p>
							<div class="flex gap-3 flex-wrap">
								{#each gGroup.members as member (member.file_id)}
									{@const isKeep = member.file_id === gGroup.auto_keep_file_id}
									<div class="w-32 rounded-lg border {isKeep ? 'border-green-400 ring-2 ring-green-400/30' : 'border-border opacity-70'} overflow-hidden">
										<div class="relative aspect-square bg-muted">
											<img src={getThumbnailUrl(member.file_id)} alt="file {member.file_id}" class="w-full h-full object-cover" loading="lazy" />
											{#if isKeep}
												<div class="absolute top-1 left-1 rounded-full bg-green-500 text-white p-0.5"><Check class="size-2.5" /></div>
											{/if}
										</div>
										<div class="p-1.5 space-y-0.5">
											<p class="text-[10px] font-mono truncate text-muted-foreground" title={member.file_path}>{getFileName(member.file_path)}</p>
											<p class="text-[10px] text-muted-foreground">{formatFileSize(member.file_size)}</p>
											{#if member.resolution}
												<p class="text-[10px] text-muted-foreground">{member.resolution}</p>
											{/if}
										</div>
									</div>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

<!-- 카드 뷰 -->
{:else}

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
								checked={groupSelection.has(group.group_id)}
								onchange={() => groupSelection.toggle(group.group_id)}
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
										onchange={() => loadFolderFiles(folder.folder_path)}
										class="accent-primary"
									/>
									<div class="flex-1 min-w-0">
										<p class="text-sm font-mono truncate" title={folder.folder_path}>{folder.folder_path}</p>
										<p class="text-xs text-muted-foreground mt-0.5">{folder.file_count}개 파일 · {folder.group_ids.length}개 그룹</p>
									</div>
									<button
										class="flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-accent transition-colors"
										onclick={(e) => { e.preventDefault(); e.stopPropagation(); openLocal(undefined, folder.folder_path); }}
									>
										<ExternalLink class="size-3" />
										폴더 열기
									</button>
								</label>
							{/each}
						</div>
					</div>

					<!-- 미리보기 -->
					{#if selectedKeepFolder && folderFilesLoading}
						<div class="p-8 text-center">
							<div class="text-muted-foreground text-sm animate-pulse">파일 목록 로드 중...</div>
						</div>
					{:else if selectedKeepFolder && (folderKeepFiles.length > 0 || folderDeleteFiles.length > 0)}
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
						disabled={!selectedKeepFolder || folderAffectedGroupIds.length === 0 || folderResolving || folderFilesLoading}
					>
						{folderResolving ? '처리 중...' : folderFilesLoading ? '파일 로드 중...' : `일괄 해결 (${folderAffectedGroupIds.length}그룹)`}
					</button>
				</div>
			{/if}
		</div>
	</div>
{/if}

<!-- 폴더 쌍 기준 해결 모달 -->
{#if showFolderPairModal}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onclick={() => (showFolderPairModal = false)}>
		<div class="relative bg-background rounded-xl shadow-2xl border w-[900px] max-h-[85vh] flex flex-col" onclick={(e) => e.stopPropagation()}>
			<!-- 모달 헤더 -->
			<div class="flex items-center justify-between px-6 py-4 border-b">
				<div>
					<h3 class="text-lg font-bold">폴더 쌍 기준 해결</h3>
					<p class="text-xs text-muted-foreground mt-0.5">두 폴더 간 중복 이미지를 쌍 단위로 확인하고 해결합니다</p>
				</div>
				<button class="rounded-md p-1.5 hover:bg-muted transition-colors" onclick={() => (showFolderPairModal = false)}>
					<X class="size-4" />
				</button>
			</div>

			<!-- 모달 본문 -->
			<div class="flex-1 overflow-y-auto p-6">
				{#if folderPairsLoading}
					<div class="flex items-center justify-center py-12 text-muted-foreground">
						<span class="animate-pulse">폴더 쌍 분석 중...</span>
					</div>
				{:else if folderPairs.length === 0}
					<div class="flex items-center justify-center py-12 text-muted-foreground">
						해결 가능한 폴더 쌍이 없습니다.
					</div>
				{:else if !selectedPair}
					<!-- 쌍 목록 -->
					<div class="space-y-2">
						<p class="text-sm font-medium text-muted-foreground mb-3">폴더 쌍을 선택하면 이미지 목록이 표시됩니다</p>
						{#each folderPairs as pair}
							<button
								class="w-full text-left rounded-lg border p-4 hover:bg-accent transition-colors"
								onclick={() => loadFolderPairFiles(pair)}
							>
								<div class="flex items-center justify-between gap-4">
									<div class="flex-1 min-w-0">
										<div class="flex items-center gap-2 text-sm">
											<span class="font-medium truncate text-sky-600">{pair.folder_a.split('\\').slice(-2).join('\\')}</span>
											<span class="text-muted-foreground shrink-0">↔</span>
											<span class="font-medium truncate text-sky-600">{pair.folder_b.split('\\').slice(-2).join('\\')}</span>
										</div>
										<div class="text-xs text-muted-foreground mt-1 truncate">{pair.folder_a}</div>
										<div class="text-xs text-muted-foreground truncate">{pair.folder_b}</div>
									</div>
									<div class="text-right shrink-0">
										<div class="text-sm font-semibold">{pair.group_count}그룹</div>
										<div class="text-xs text-muted-foreground">{pair.file_count}파일</div>
									</div>
								</div>
							</button>
						{/each}
					</div>
				{:else}
					<!-- 쌍 상세 + 이미지 목록 -->
					<div>
						<button
							class="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-4 transition-colors"
							onclick={() => { selectedPair = null; pairFilesA = []; pairFilesB = []; pairGroupIds = []; pairKeepFolder = null; }}
						>
							<ChevronLeft class="size-4" />
							목록으로 돌아가기
						</button>

						<div class="text-sm mb-4">
							<span class="font-medium text-sky-600">{selectedPair.folder_a.split('\\').slice(-2).join('\\')}</span>
							<span class="text-muted-foreground mx-2">↔</span>
							<span class="font-medium text-sky-600">{selectedPair.folder_b.split('\\').slice(-2).join('\\')}</span>
							<span class="text-muted-foreground ml-3">{selectedPair.group_count}그룹 · {selectedPair.file_count}파일</span>
						</div>

						{#if loadingPairFiles}
							<div class="text-center py-8 text-muted-foreground animate-pulse">파일 목록 로드 중...</div>
						{:else}
							<!-- 보관 폴더 선택 -->
							<div class="flex gap-3 mb-4">
								<label class="flex-1 flex items-center gap-2 rounded-lg border p-3 cursor-pointer hover:bg-accent transition-colors {pairKeepFolder === 'a' ? 'border-primary bg-primary/5' : ''}">
									<input type="radio" name="pairKeep" value="a" bind:group={pairKeepFolder} class="sr-only" />
									<div class="size-4 rounded-full border-2 {pairKeepFolder === 'a' ? 'border-primary bg-primary' : 'border-muted-foreground'} shrink-0"></div>
									<div class="min-w-0">
										<div class="text-sm font-medium">A 폴더 보관</div>
										<div class="text-xs text-muted-foreground truncate">{selectedPair.folder_a}</div>
										<div class="text-xs text-muted-foreground">{pairFilesA.length}개 파일</div>
									</div>
								</label>
								<label class="flex-1 flex items-center gap-2 rounded-lg border p-3 cursor-pointer hover:bg-accent transition-colors {pairKeepFolder === 'b' ? 'border-primary bg-primary/5' : ''}">
									<input type="radio" name="pairKeep" value="b" bind:group={pairKeepFolder} class="sr-only" />
									<div class="size-4 rounded-full border-2 {pairKeepFolder === 'b' ? 'border-primary bg-primary' : 'border-muted-foreground'} shrink-0"></div>
									<div class="min-w-0">
										<div class="text-sm font-medium">B 폴더 보관</div>
										<div class="text-xs text-muted-foreground truncate">{selectedPair.folder_b}</div>
										<div class="text-xs text-muted-foreground">{pairFilesB.length}개 파일</div>
									</div>
								</label>
							</div>

							<!-- 이미지 2열 비교 -->
							<div class="grid grid-cols-2 gap-4">
								<div>
									<p class="text-sm font-semibold mb-2">
										A 폴더 <span class="text-muted-foreground font-normal">({pairFilesA.length}개)</span>
										{#if pairKeepFolder === 'a'}<span class="ml-1 text-xs text-green-600 font-medium">보관</span>{/if}
										{#if pairKeepFolder === 'b'}<span class="ml-1 text-xs text-destructive font-medium">삭제</span>{/if}
									</p>
									<div class="grid grid-cols-3 gap-2 max-h-[300px] overflow-y-auto">
										{#each pairFilesA as f}
											<div class="rounded border bg-muted/30 p-1">
												<img
													src="/api/ic/files/{f.file_id}/thumbnail"
													alt=""
													class="w-full aspect-square object-cover rounded"
													loading="lazy"
													onerror={(e) => { (e.target as HTMLImageElement).style.display='none'; }}
												/>
												<p class="text-[10px] text-muted-foreground mt-1 truncate">{f.file_path.split('\\').pop()}</p>
											</div>
										{/each}
									</div>
								</div>
								<div>
									<p class="text-sm font-semibold mb-2">
										B 폴더 <span class="text-muted-foreground font-normal">({pairFilesB.length}개)</span>
										{#if pairKeepFolder === 'b'}<span class="ml-1 text-xs text-green-600 font-medium">보관</span>{/if}
										{#if pairKeepFolder === 'a'}<span class="ml-1 text-xs text-destructive font-medium">삭제</span>{/if}
									</p>
									<div class="grid grid-cols-3 gap-2 max-h-[300px] overflow-y-auto">
										{#each pairFilesB as f}
											<div class="rounded border bg-muted/30 p-1">
												<img
													src="/api/ic/files/{f.file_id}/thumbnail"
													alt=""
													class="w-full aspect-square object-cover rounded"
													loading="lazy"
													onerror={(e) => { (e.target as HTMLImageElement).style.display='none'; }}
												/>
												<p class="text-[10px] text-muted-foreground mt-1 truncate">{f.file_path.split('\\').pop()}</p>
											</div>
										{/each}
									</div>
								</div>
							</div>
						{/if}
					</div>
				{/if}
			</div>

			<!-- 모달 푸터 -->
			{#if selectedPair && !loadingPairFiles}
				<div class="flex items-center justify-end gap-3 px-6 py-4 border-t">
					<button
						class="rounded-lg border px-4 py-2 text-sm hover:bg-accent transition-colors"
						onclick={() => (showFolderPairModal = false)}
					>
						취소
					</button>
					<button
						class="rounded-lg bg-sky-600 text-white px-4 py-2 text-sm font-medium hover:bg-sky-700 transition-colors disabled:opacity-50"
						onclick={resolveByFolderPair}
						disabled={!pairKeepFolder || pairGroupIds.length === 0 || pairResolving}
					>
						{pairResolving ? '처리 중...' : `폴더 쌍 해결 (${pairGroupIds.length}그룹)`}
					</button>
				</div>
			{/if}
		</div>
	</div>
{/if}
