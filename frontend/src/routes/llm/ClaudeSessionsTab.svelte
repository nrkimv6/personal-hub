<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { RefreshCw, List, MessageSquare, Clock, GitBranch, Folder, ChevronDown } from 'lucide-svelte';
	import { createOffsetPagination } from '$lib/utils/pagination.svelte';
	import { claudeSessionsApi, type SessionMeta, type SummaryResult, type ProjectInfo } from '$lib/api';
	import { toast } from '$lib/stores/toast';

	// 페이지네이션
	const pager = createOffsetPagination(20);

	// 상태
	let projects: ProjectInfo[] = $state([]);
	let selectedProject: string = $state('');
	let sessions: SessionMeta[] = $state([]);
	let loading: boolean = $state(false);
	let error: string | null = $state(null);

	// 필터
	let filterSourceType: '' | 'user' | 'agent' | 'llm-worker' = $state('');
	let filterLimit: number = $state(20);
	let filterSince: string = $state('');

	// 선택 (벌크 요약용)
	let selectedIds: Set<string> = $state(new Set());
	let selectAll: boolean = $state(false);

	// 요약 결과 캐시: session_id → SummaryResult
	let summaryCache: Record<string, SummaryResult> = $state({});

	// 폴링
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	onMount(async () => {
		await loadProjects();
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});

	async function loadProjects() {
		try {
			projects = await claudeSessionsApi.listProjects();
			if (projects.length > 0 && !selectedProject) {
				selectedProject = projects[0].encoded;
				await loadSessions();
			}
		} catch (e: any) {
			error = e.message ?? '프로젝트 목록 조회 실패';
		}
	}

	async function loadSessions() {
		if (!selectedProject) return;
		loading = true;
		error = null;
		pager.reset();
		try {
			const filter: Record<string, any> = { limit: filterLimit };
			if (filterSince) filter.since = filterSince;
			if (filterSourceType) filter.source_type = filterSourceType;
			sessions = await claudeSessionsApi.listSessions(selectedProject, filter);
			selectAll = false;
			selectedIds = new Set();
		} catch (e: any) {
			error = e.message ?? '세션 목록 조회 실패';
		} finally {
			loading = false;
		}
	}

	function onFilterChange() {
		pager.reset();
		loadSessions();
	}

	function toggleSelectAll() {
		if (selectAll) {
			selectedIds = new Set(sessions.map((s) => s.id));
		} else {
			selectedIds = new Set();
		}
	}

	function toggleSelect(id: string) {
		const next = new Set(selectedIds);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		selectedIds = next;
		selectAll = next.size === sessions.length;
	}

	async function summarizeSelected() {
		if (selectedIds.size === 0) {
			toast.warning('요약할 세션을 선택하세요');
			return;
		}
		let count = 0;
		for (const sid of selectedIds) {
			try {
				await claudeSessionsApi.summarizeSession(selectedProject, sid);
				summaryCache[sid] = { session_id: sid, status: 'pending', summary: null };
				count++;
			} catch (e: any) {
				toast.error(`요약 요청 실패: ${sid.slice(0, 8)} — ${e.message}`);
			}
		}
		if (count > 0) {
			toast.success(`${count}개 세션 요약 요청 완료`);
			startPolling();
		}
	}

	async function summarizeRecent() {
		if (!selectedProject) return;
		try {
			const filter: Record<string, any> = { limit: Math.min(filterLimit, 8) };
			if (filterSince) filter.since = filterSince;
			if (filterSourceType) filter.source_type = filterSourceType;
			const res = await claudeSessionsApi.summarizeRecent(selectedProject, filter);
			toast.success(`${res.count}개 세션 일괄 요약 요청`);
			// 폴링 초기화
			for (const s of sessions.slice(0, res.count)) {
				summaryCache[s.id] = { session_id: s.id, status: 'pending', summary: null };
			}
			startPolling();
		} catch (e: any) {
			toast.error(`일괄 요약 실패: ${e.message}`);
		}
	}

	function startPolling() {
		if (pollTimer) return;
		pollTimer = setInterval(pollSummaries, 2000);
	}

	async function pollSummaries() {
		const pendingIds = Object.entries(summaryCache)
			.filter(([, v]) => v.status === 'pending' || v.status === 'processing')
			.map(([k]) => k);

		if (pendingIds.length === 0) {
			if (pollTimer) {
				clearInterval(pollTimer);
				pollTimer = null;
			}
			return;
		}

		for (const sid of pendingIds) {
			try {
				const res = await claudeSessionsApi.getSummary(sid);
				summaryCache[sid] = res;
			} catch {
				// 무시
			}
		}
		// 반응형 갱신
		summaryCache = { ...summaryCache };
	}

	function sourceTypeBadge(type: string): string {
		switch (type) {
			case 'user': return 'bg-blue-100 text-blue-700';
			case 'agent': return 'bg-purple-100 text-purple-700';
			case 'llm-worker': return 'bg-orange-100 text-orange-700';
			default: return 'bg-gray-100 text-gray-600';
		}
	}

	function sourceTypeLabel(type: string): string {
		switch (type) {
			case 'user': return '사용자';
			case 'agent': return '에이전트';
			case 'llm-worker': return 'LLM워커';
			default: return '알수없음';
		}
	}

	function formatDate(iso: string): string {
		try {
			return new Date(iso).toLocaleString('ko-KR', {
				month: '2-digit', day: '2-digit',
				hour: '2-digit', minute: '2-digit'
			});
		} catch {
			return iso;
		}
	}
</script>

<div class="space-y-4">
	<!-- 필터 바 -->
	<div class="card p-4 space-y-3">
		<div class="flex flex-wrap gap-3 items-end">
			<!-- 프로젝트 선택 -->
			<div class="flex flex-col gap-1">
				<label class="text-xs text-muted-foreground">프로젝트</label>
				<select
					bind:value={selectedProject}
					onchange={onFilterChange}
					class="input text-sm"
				>
					{#each projects as p}
						<option value={p.encoded}>{p.encoded}</option>
					{/each}
				</select>
			</div>

			<!-- 소스 타입 -->
			<div class="flex flex-col gap-1">
				<label class="text-xs text-muted-foreground">소스 타입</label>
				<select bind:value={filterSourceType} onchange={onFilterChange} class="input text-sm">
					<option value="">전체</option>
					<option value="user">사용자</option>
					<option value="agent">에이전트</option>
					<option value="llm-worker">LLM워커</option>
				</select>
			</div>

			<!-- 최대 개수 -->
			<div class="flex flex-col gap-1">
				<label class="text-xs text-muted-foreground">최대 개수</label>
				<input
					type="number"
					bind:value={filterLimit}
					onchange={onFilterChange}
					min="1" max="200"
					class="input text-sm w-20"
				/>
			</div>

			<!-- 시작일시 -->
			<div class="flex flex-col gap-1">
				<label class="text-xs text-muted-foreground">시작일시 (이후)</label>
				<input
					type="datetime-local"
					bind:value={filterSince}
					onchange={onFilterChange}
					class="input text-sm"
				/>
			</div>

			<!-- 새로고침 -->
			<button
				onclick={loadSessions}
				class="btn btn-outline flex items-center gap-1 text-sm"
				disabled={loading}
			>
				<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
				새로고침
			</button>
		</div>

		<!-- 벌크 액션 -->
		<div class="flex gap-2 items-center flex-wrap">
			<label class="flex items-center gap-1 text-sm cursor-pointer">
				<input
					type="checkbox"
					bind:checked={selectAll}
					onchange={toggleSelectAll}
				/>
				전체 선택
			</label>
			<span class="text-xs text-muted-foreground">{selectedIds.size}개 선택됨</span>
			<button
				onclick={summarizeSelected}
				disabled={selectedIds.size === 0}
				class="btn btn-primary text-sm"
			>
				선택 세션 요약
			</button>
			<button
				onclick={summarizeRecent}
				class="btn btn-outline text-sm"
			>
				최근 {Math.min(filterLimit, 8)}개 요약
			</button>
		</div>
	</div>

	<!-- 에러 -->
	{#if error}
		<div class="card p-3 text-error text-sm">{error}</div>
	{/if}

	<!-- 세션 목록 -->
	{#if loading}
		<div class="text-center py-8 text-muted-foreground text-sm">로딩 중...</div>
	{:else if sessions.length === 0}
		<div class="text-center py-8 text-muted-foreground text-sm">세션이 없습니다</div>
	{:else}
		<div class="space-y-2">
			{#each sessions as session}
				{@const summary = summaryCache[session.id]}
				<div class="card p-3 space-y-2">
					<div class="flex items-start gap-3">
						<!-- 체크박스 -->
						<input
							type="checkbox"
							checked={selectedIds.has(session.id)}
							onchange={() => toggleSelect(session.id)}
							class="mt-1"
						/>

						<div class="flex-1 min-w-0">
							<!-- 상단: ID + 배지들 -->
							<div class="flex flex-wrap items-center gap-2">
								<span class="font-mono text-sm font-medium">{session.id.slice(0, 8)}…</span>
								<span class="px-1.5 py-0.5 rounded text-xs font-medium {sourceTypeBadge(session.source_type)}">
									{sourceTypeLabel(session.source_type)}
								</span>
								{#if session.agent_name}
									<span class="px-1.5 py-0.5 rounded text-xs bg-purple-50 text-purple-600">
										{session.agent_name}
									</span>
								{/if}
								{#if summary}
									{#if summary.status === 'pending' || summary.status === 'processing'}
										<span class="px-1.5 py-0.5 rounded text-xs bg-yellow-100 text-yellow-700">요약 중...</span>
									{:else if summary.status === 'completed'}
										<span class="px-1.5 py-0.5 rounded text-xs bg-green-100 text-green-700">요약 완료</span>
									{:else if summary.status === 'failed'}
										<span class="px-1.5 py-0.5 rounded text-xs bg-red-100 text-red-700">요약 실패</span>
									{/if}
								{/if}
							</div>

							<!-- 메타 정보 -->
							<div class="flex flex-wrap gap-3 mt-1 text-xs text-muted-foreground">
								<span class="flex items-center gap-1">
									<Clock size={11} />
									{formatDate(session.mtime)}
								</span>
								<span class="flex items-center gap-1">
									<List size={11} />
									{session.line_count}줄
								</span>
								{#if session.git_branch}
									<span class="flex items-center gap-1">
										<GitBranch size={11} />
										{session.git_branch}
									</span>
								{/if}
								{#if session.cwd}
									<span class="flex items-center gap-1 truncate max-w-[200px]" title={session.cwd}>
										<Folder size={11} />
										{session.cwd.split(/[/\\]/).slice(-2).join('/')}
									</span>
								{/if}
							</div>

							<!-- 첫 메시지 미리보기 -->
							{#if session.first_message}
								<p class="text-xs text-muted-foreground mt-1 line-clamp-1 italic">
									"{session.first_message}"
								</p>
							{/if}

							<!-- 요약 결과 -->
							{#if summary?.status === 'completed' && summary.summary}
								<div class="mt-2 p-2 bg-success-light/30 rounded text-xs text-foreground leading-relaxed">
									{summary.summary}
								</div>
							{/if}
						</div>

						<!-- 단건 요약 버튼 -->
						<button
							onclick={() => {
								claudeSessionsApi.summarizeSession(selectedProject, session.id).then(() => {
									summaryCache[session.id] = { session_id: session.id, status: 'pending', summary: null };
									summaryCache = { ...summaryCache };
									startPolling();
								}).catch((e: any) => toast.error(`요약 실패: ${e.message}`));
							}}
							class="btn btn-outline text-xs shrink-0"
							disabled={summary?.status === 'pending' || summary?.status === 'processing'}
						>
							<MessageSquare size={12} />
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
