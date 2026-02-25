<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { History, RotateCcw, RefreshCw, ScanLine, ChevronDown, ChevronRight, ChevronLeft, FileImage, ArrowRight } from 'lucide-svelte';
	import { toast } from '$lib/stores/toast';
	import { createPagePagination } from '$lib/utils/pagination.svelte';
	import { loadCategoryMap, getCategoryName } from '../lib/categoryUtils';

	interface MoveHistory {
		id: number;
		file_path: string;
		file_size: number;
		status: string;
		final_category_id: number | null;
		extracted_date: string | null;
		moved_path: string | null;
		moved_at: string | null;
		category_path: string | null;
	}

	interface ScanHistory {
		id: number;
		started_at: string;
		finished_at: string | null;
		scanned_files: number;
		total_files: number;
		status: string;
	}

	let history: MoveHistory[] = $state([]);
	let loading = $state(false);
	const pager = createPagePagination(50);

	// 스캔 이력 상태
	let scanHistory: ScanHistory[] = $state([]);
	let scanHistoryLoading = $state(false);
	let scanHistoryOpen = $state(false);

	// 카테고리 맵 (fallback용)
	let categoryMap = $state(new Map<number, string>());

	async function loadCategories() {
		try {
			categoryMap = await loadCategoryMap();
		} catch { /* ignore */ }
	}

	function getCategoryDisplay(item: MoveHistory): string {
		if (item.category_path) return item.category_path;
		if (item.final_category_id) return getCategoryName(categoryMap, item.final_category_id);
		return '';
	}

	onMount(() => {
		loadHistory();
		loadCategories();
	});

	async function loadHistory() {
		loading = true;
		try {
			const params = new URLSearchParams({
				status: 'moved',
				order_by: 'id',
				order_dir: 'desc',
				...pager.toParams()
			});
			const response = await fetchWithTimeout(`/api/ic/files?${params}`);
			if (response.ok) {
				const data = await response.json();
				history = data.files || [];
				pager.total = data.total ?? history.length;
			}
		} catch (err) {
			console.error('이력 로드 실패:', err);
		} finally {
			loading = false;
		}
	}

	function goToPage(page: number) {
		pager.goTo(page);
		loadHistory();
	}

	async function rollback(id: number) {
		if (!confirm('이 파일을 원래 위치로 복원하시겠습니까?')) return;

		try {
			const res = await fetchWithTimeout(`/api/ic/files/${id}/rollback`, { method: 'POST' });
			if (!res.ok) throw new Error('복원 실패');
			await loadHistory();
		} catch (err) {
			toast.error('복원 실패');
		}
	}

	async function loadScanHistory() {
		if (scanHistory.length > 0) return; // 이미 로드됨
		scanHistoryLoading = true;
		try {
			const res = await fetchWithTimeout('/api/ic/scan/history');
			if (res.ok) {
				const data = await res.json();
				scanHistory = data.history || data || [];
			}
		} catch (err) {
			console.error('스캔 이력 로드 실패:', err);
		} finally {
			scanHistoryLoading = false;
		}
	}

	async function toggleScanHistory() {
		scanHistoryOpen = !scanHistoryOpen;
		if (scanHistoryOpen) await loadScanHistory();
	}

	function formatDateTime(dt: string | null): string {
		if (!dt) return '—';
		try {
			return new Date(dt).toLocaleString('ko-KR', {
				year: 'numeric', month: '2-digit', day: '2-digit',
				hour: '2-digit', minute: '2-digit'
			});
		} catch {
			return dt;
		}
	}

	function formatElapsed(start: string, end: string | null): string {
		if (!end) return '진행 중';
		const diff = new Date(end).getTime() - new Date(start).getTime();
		const s = Math.floor(diff / 1000);
		if (s < 60) return `${s}초`;
		const m = Math.floor(s / 60);
		return `${m}분 ${s % 60}초`;
	}
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<History class="size-5 text-primary" />
				<h2 class="text-xl font-bold tracking-tight">이동 이력</h2>
			</div>
			<p class="mt-1 text-sm text-muted-foreground">최근 이동된 파일들을 확인하고 필요시 복원할 수 있습니다.</p>
		</div>
		<button
			onclick={loadHistory}
			disabled={loading}
			class="inline-flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50 transition-colors"
		>
			<RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
			새로고침
		</button>
	</div>

	<!-- 스캔 이력 접이식 섹션 -->
	<div class="rounded-xl border bg-card overflow-hidden">
		<button
			onclick={toggleScanHistory}
			class="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-muted/30 transition-colors"
		>
			<div class="flex items-center gap-2">
				<ScanLine class="size-4 text-primary" />
				<span class="text-sm font-semibold">스캔 이력</span>
			</div>
			{#if scanHistoryOpen}
				<ChevronDown class="size-4 text-muted-foreground" />
			{:else}
				<ChevronRight class="size-4 text-muted-foreground" />
			{/if}
		</button>

		{#if scanHistoryOpen}
			{#if scanHistoryLoading}
				<div class="flex items-center justify-center py-8 text-sm text-muted-foreground border-t">
					<div class="flex items-center gap-2">
						<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
						로딩 중...
					</div>
				</div>
			{:else if scanHistory.length === 0}
				<div class="border-t py-8 text-center text-sm text-muted-foreground">
					스캔 이력이 없습니다.
				</div>
			{:else}
				<div class="border-t">
					<table class="w-full text-xs">
						<thead class="border-b bg-muted/40">
							<tr>
								<th class="px-4 py-2 text-left font-medium text-muted-foreground">시작일시</th>
								<th class="px-4 py-2 text-left font-medium text-muted-foreground">종료일시</th>
								<th class="px-4 py-2 text-right font-medium text-muted-foreground">스캔 파일</th>
								<th class="px-4 py-2 text-right font-medium text-muted-foreground">소요시간</th>
								<th class="px-4 py-2 text-center font-medium text-muted-foreground">상태</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-border">
							{#each scanHistory as scan}
								<tr class="hover:bg-muted/20 transition-colors">
									<td class="px-4 py-2 font-mono">{formatDateTime(scan.started_at)}</td>
									<td class="px-4 py-2 font-mono">{formatDateTime(scan.finished_at)}</td>
									<td class="px-4 py-2 text-right">{scan.scanned_files?.toLocaleString() ?? '—'} / {scan.total_files?.toLocaleString() ?? '—'}</td>
									<td class="px-4 py-2 text-right">{formatElapsed(scan.started_at, scan.finished_at)}</td>
									<td class="px-4 py-2 text-center">
										<span class="rounded-full px-2 py-0.5 font-medium {scan.status === 'completed' ? 'bg-emerald-100 text-emerald-700' : scan.status === 'running' ? 'bg-blue-100 text-blue-700' : 'bg-muted text-muted-foreground'}">
											{scan.status === 'completed' ? '완료' : scan.status === 'running' ? '진행 중' : scan.status ?? '중단'}
										</span>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{/if}
	</div>

	<!-- 파일 이동 이력 테이블 -->
	<div class="rounded-xl border bg-card">
		{#if loading}
			<div class="flex items-center justify-center py-16 text-sm text-muted-foreground">
				<div class="flex items-center gap-2">
					<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
					로딩 중...
				</div>
			</div>
		{:else if history.length === 0}
			<div class="py-16 text-center text-sm text-muted-foreground">
				이동 이력이 없습니다.
			</div>
		{:else}
			<div class="divide-y divide-border">
				{#each history as item}
					<div class="flex items-start gap-3 px-5 py-3 hover:bg-muted/30 transition-colors">
						<!-- 썸네일 -->
						<div class="shrink-0 size-16 rounded-md overflow-hidden bg-muted/50 flex items-center justify-center">
							<img
								src="/api/ic/files/{item.id}/thumbnail"
								alt=""
								class="size-16 object-cover"
								onerror={(e) => { (e.target as HTMLImageElement).style.display = 'none'; (e.target as HTMLImageElement).nextElementSibling?.classList.remove('hidden'); }}
							/>
							<div class="hidden flex-col items-center justify-center text-muted-foreground">
								<FileImage class="size-5" />
							</div>
						</div>

						<!-- 파일 정보 -->
						<div class="flex-1 min-w-0">
							{#if item.moved_path}
								<div class="flex items-center gap-1.5 text-xs">
									<span class="font-mono text-muted-foreground truncate max-w-[40%]" title={item.file_path}>{item.file_path.split(/[/\\]/).pop()}</span>
									<ArrowRight class="size-3 shrink-0 text-primary" />
									<span class="font-mono text-foreground truncate max-w-[55%]" title={item.moved_path}>{item.moved_path}</span>
								</div>
							{:else}
								<p class="font-mono text-xs text-foreground truncate">{item.file_path}</p>
							{/if}
							<p class="text-[10px] text-muted-foreground mt-1">
								{#if getCategoryDisplay(item)}
									<span class="rounded bg-green-500/10 px-1.5 py-0.5 text-green-600">{getCategoryDisplay(item)}</span>
								{/if}
								{#if item.moved_at}
									· 이동: {formatDateTime(item.moved_at)}
								{/if}
								{#if item.extracted_date}
									· 촬영: {item.extracted_date}
								{/if}
							</p>
						</div>

						<span class="shrink-0 rounded-full bg-violet-500/10 px-2.5 py-0.5 text-xs font-medium text-violet-700">
							{item.status}
						</span>
						<button
							onclick={() => rollback(item.id)}
							class="shrink-0 flex items-center gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors"
						>
							<RotateCcw class="size-3" />
							복원
						</button>
					</div>
				{/each}
			</div>
		{/if}

		<!-- 페이지네이션 -->
		{#if pager.totalPages > 1}
			<div class="flex items-center justify-between border-t px-5 py-3">
				<span class="text-xs text-muted-foreground">
					총 {pager.total.toLocaleString()}건
				</span>
				<div class="flex items-center gap-1">
					<button
						onclick={() => goToPage(pager.page - 1)}
						disabled={pager.page <= 1}
						class="rounded-md border p-1.5 text-xs hover:bg-accent disabled:opacity-30 transition-colors"
					>
						<ChevronLeft class="size-3.5" />
					</button>
					<span class="px-2 text-xs font-medium">{pager.page} / {pager.totalPages}</span>
					<button
						onclick={() => goToPage(pager.page + 1)}
						disabled={pager.page >= pager.totalPages}
						class="rounded-md border p-1.5 text-xs hover:bg-accent disabled:opacity-30 transition-colors"
					>
						<ChevronRight class="size-3.5" />
					</button>
				</div>
			</div>
		{/if}
	</div>
</div>
