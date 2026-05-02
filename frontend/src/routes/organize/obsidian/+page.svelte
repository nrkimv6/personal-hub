<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import TabNav from '$lib/components/layout/TabNav.svelte';
	import { isApiGateClosedError } from '$lib/api/client';

	// 탭
	type TabId = 'explore' | 'classify' | 'extract';
	let activeTab = $state<TabId>('explore');
	const obsidianTabs = [
		{ id: 'explore', label: '탐색' },
		{ id: 'classify', label: '분류' },
		{ id: 'extract', label: '추출' }
	];

	// === 탐색 탭 ===
	let vaultPath = $state('');
	let scanState = $state({ status: 'idle', total: 0, processed: 0, current: '' });
	let stats = $state<{
		total: number;
		avg_content_length: number;
		frontmatter_ratio: number;
		daily_notes_count: number;
		top_tags: { tag: string; count: number }[];
		top_links: { link: string; count: number }[];
	} | null>(null);
	let notes = $state<{
		total: number;
		items: {
			id: number;
			file_name: string;
			file_path: string;
			content_length: number;
			note_type: string | null;
			is_daily_note: boolean;
			has_frontmatter: boolean;
			status: string;
		}[];
	}>({ total: 0, items: [] });
	let notesPage = $state(0);
	const PAGE_SIZE = 50;
	let notesSearch = $state('');
	let noteTypeFilter = $state('');

	// === 분류 탭 ===
	let classifyState = $state({ status: 'idle', total: 0, processed: 0 });
	let useLlm = $state(true);
	let selectedNoteIds = $state<number[]>([]);
	let approveType = $state('memo');
	let classifyNotes = $state<{
		total: number;
		items: {
			id: number;
			file_name: string;
			note_type: string | null;
			is_daily_note: boolean;
			has_frontmatter: boolean;
			status: string;
		}[];
	}>({ total: 0, items: [] });

	// === 추출 탭 ===
	let extractState = $state({ status: 'idle', total: 0, processed: 0 });
	let extractResults = $state<{
		total: number;
		items: {
			id: number;
			file_name: string;
			note_type: string;
			extracted: { todos?: string[]; urls?: string[]; code_snippets?: string[] };
		}[];
	}>({ total: 0, items: [] });
	let extractTab = $state<'todos' | 'urls' | 'code'>('todos');
	const extractTabs = [
		{ id: 'todos', label: 'TODO' },
		{ id: 'urls', label: 'URL' },
		{ id: 'code', label: '코드' }
	];

	let pollInterval: ReturnType<typeof setInterval> | null = null;
	let apiMessage = $state<string | null>(null);

	onMount(() => {
		loadStats();
		loadNotes();
	});

	onDestroy(() => {
		if (pollInterval) clearInterval(pollInterval);
	});

	async function loadStats() {
		const res = await apiFetch('/api/fc/obsidian/stats');
		if (res.ok) stats = await res.json();
	}

	async function loadNotes() {
		const params = new URLSearchParams({
			skip: String(notesPage * PAGE_SIZE),
			limit: String(PAGE_SIZE)
		});
		if (notesSearch) params.set('search', notesSearch);
		if (noteTypeFilter) params.set('note_type', noteTypeFilter);
		const res = await apiFetch(`/api/fc/obsidian/notes?${params}`);
		if (res.ok) notes = await res.json();
	}

	async function startScan() {
		const body = vaultPath ? `?vault_path=${encodeURIComponent(vaultPath)}` : '';
		await apiFetch(`/api/fc/obsidian/scan/start${body}`, { method: 'POST' });
		scanState = { status: 'running', total: 0, processed: 0, current: '' };
		startPoll();
	}

	function startPoll() {
		if (pollInterval) clearInterval(pollInterval);
		pollInterval = setInterval(async () => {
			const res = await apiFetch('/api/fc/obsidian/scan/status');
			if (res.ok) {
				scanState = await res.json();
				if (scanState.status !== 'running') {
					clearInterval(pollInterval!);
					pollInterval = null;
					loadStats();
					loadNotes();
				}
			}
		}, 1000);
	}

	async function loadClassifyNotes() {
		const res = await apiFetch('/api/fc/obsidian/notes?limit=200');
		if (res.ok) classifyNotes = await res.json();
	}

	async function startClassify() {
		await apiFetch(`/api/fc/obsidian/classify/start?use_llm=${useLlm}`, { method: 'POST' });
		classifyState = { status: 'running', total: 0, processed: 0 };
		if (pollInterval) clearInterval(pollInterval);
		pollInterval = setInterval(async () => {
			const res = await apiFetch('/api/fc/obsidian/classify/status');
			if (res.ok) {
				classifyState = await res.json();
				if (classifyState.status !== 'running') {
					clearInterval(pollInterval!);
					pollInterval = null;
					loadClassifyNotes();
				}
			}
		}, 1000);
	}

	async function approveSelected() {
		if (!selectedNoteIds.length) return;
		await apiFetch('/api/fc/obsidian/classify/approve', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ note_ids: selectedNoteIds, note_type: approveType })
		});
		selectedNoteIds = [];
		loadClassifyNotes();
	}

	function toggleSelect(id: number) {
		if (selectedNoteIds.includes(id)) {
			selectedNoteIds = selectedNoteIds.filter((x) => x !== id);
		} else {
			selectedNoteIds = [...selectedNoteIds, id];
		}
	}

	function selectAll() {
		selectedNoteIds = classifyNotes.items.map((n) => n.id);
	}

	function deselectAll() {
		selectedNoteIds = [];
	}

	async function startExtract() {
		await apiFetch('/api/fc/obsidian/extract/start', { method: 'POST' });
		extractState = { status: 'running', total: 0, processed: 0 };
		if (pollInterval) clearInterval(pollInterval);
		pollInterval = setInterval(async () => {
			const res = await apiFetch('/api/fc/obsidian/extract/status');
			if (res.ok) {
				extractState = await res.json();
				if (extractState.status !== 'running') {
					clearInterval(pollInterval!);
					pollInterval = null;
					loadExtractResults();
				}
			}
		}, 1000);
	}

	async function loadExtractResults() {
		const res = await apiFetch('/api/fc/obsidian/extract/results?limit=100');
		if (res.ok) extractResults = await res.json();
	}

	async function exportJson() {
		const res = await apiFetch('/api/fc/obsidian/extract/export');
		if (res.ok) {
			const data = await res.json();
			const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = 'obsidian_extract.json';
			a.click();
			URL.revokeObjectURL(url);
		}
	}

	function onTabChange(tab: TabId) {
		activeTab = tab;
		if (tab === 'classify') loadClassifyNotes();
		if (tab === 'extract') loadExtractResults();
	}

	async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
		try {
			const response = await fetch(input, init);
			apiMessage = null;
			return response;
		} catch (e) {
			apiMessage = isApiGateClosedError(e) ? 'API 서버 재시작 중' : '요청 실패';
			throw e;
		}
	}
</script>

<div class="space-y-4">
	<PageHeader title="옵시디언 분석기" />

	<TabNav tabs={obsidianTabs} bind:activeTab variant="secondary" onTabChange={(tabId) => onTabChange(tabId as TabId)} />

	<!-- 탐색 탭 -->
	{#if activeTab === 'explore'}
		<div class="space-y-4">
			<!-- 스캔 영역 -->
			<div class="rounded-lg border border-border bg-card p-4">
				<h3 class="mb-3 text-sm font-semibold text-foreground">Vault 스캔</h3>
				<div class="flex gap-2">
					<input
						type="text"
						bind:value={vaultPath}
						placeholder="Vault 경로 (미입력 시 설정값 사용)"
						class="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
					/>
					<button
						class="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
						onclick={startScan}
						disabled={scanState.status === 'running'}
					>
						{scanState.status === 'running' ? '스캔 중...' : '스캔 시작'}
					</button>
				</div>
				{#if scanState.status === 'running'}
					<p class="mt-2 text-xs text-muted-foreground">
						{scanState.processed}/{scanState.total} 처리 중... {scanState.current?.split(/[/\\]/).at(-1) ?? ''}
					</p>
				{:else if scanState.status === 'completed'}
					<p class="mt-2 text-xs text-green-500">스캔 완료 ({scanState.total}개)</p>
				{/if}
			</div>

			<!-- 통계 카드 -->
			{#if stats}
				<div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
					<div class="rounded-lg border border-border bg-card p-3 text-center">
						<div class="text-2xl font-bold text-primary">{stats.total.toLocaleString()}</div>
						<div class="text-xs text-muted-foreground">전체 노트</div>
					</div>
					<div class="rounded-lg border border-border bg-card p-3 text-center">
						<div class="text-2xl font-bold text-blue-500">{stats.daily_notes_count.toLocaleString()}</div>
						<div class="text-xs text-muted-foreground">일일 노트</div>
					</div>
					<div class="rounded-lg border border-border bg-card p-3 text-center">
						<div class="text-2xl font-bold text-green-500">{stats.frontmatter_ratio}%</div>
						<div class="text-xs text-muted-foreground">Frontmatter 비율</div>
					</div>
					<div class="rounded-lg border border-border bg-card p-3 text-center">
						<div class="text-2xl font-bold text-orange-500">{stats.avg_content_length.toLocaleString()}</div>
						<div class="text-xs text-muted-foreground">평균 글자수</div>
					</div>
				</div>

				<!-- 태그 TOP 10 -->
				{#if stats.top_tags.length > 0}
					<div class="rounded-lg border border-border bg-card p-4">
						<h3 class="mb-3 text-sm font-semibold text-foreground">태그 TOP 10</h3>
						<div class="flex flex-wrap gap-2">
							{#each stats.top_tags.slice(0, 10) as { tag, count }}
								<span class="rounded-full border border-border bg-accent px-2.5 py-0.5 text-xs text-foreground">
									#{tag} <span class="text-muted-foreground">({count})</span>
								</span>
							{/each}
						</div>
					</div>
				{/if}
			{/if}

			<!-- 노트 목록 -->
			<div class="rounded-lg border border-border bg-card p-4">
				<div class="mb-3 flex flex-wrap items-center gap-2">
					<h3 class="text-sm font-semibold text-foreground">노트 목록</h3>
					<input
						type="text"
						bind:value={notesSearch}
						placeholder="검색..."
						class="rounded-md border border-border bg-background px-3 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
						oninput={() => { notesPage = 0; loadNotes(); }}
					/>
					<select
						bind:value={noteTypeFilter}
						class="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none"
						onchange={() => { notesPage = 0; loadNotes(); }}
					>
						<option value="">전체 유형</option>
						<option value="memo">memo</option>
						<option value="record">record</option>
						<option value="daily">daily</option>
						<option value="other">other</option>
					</select>
					<span class="ml-auto text-xs text-muted-foreground">총 {notes.total}개</span>
				</div>

				<div class="overflow-x-auto">
					<table class="w-full text-xs">
						<thead>
							<tr class="border-b border-border text-muted-foreground">
								<th class="pb-2 text-left font-medium">파일명</th>
								<th class="pb-2 text-right font-medium">글자수</th>
								<th class="pb-2 text-center font-medium">유형</th>
								<th class="pb-2 text-center font-medium">일일</th>
								<th class="pb-2 text-center font-medium">상태</th>
							</tr>
						</thead>
						<tbody>
							{#each notes.items as note}
								<tr class="border-b border-border/50 hover:bg-accent/30">
									<td class="py-1.5 text-foreground" title={note.file_path}>{note.file_name}</td>
									<td class="py-1.5 text-right text-muted-foreground">{note.content_length?.toLocaleString() ?? '-'}</td>
									<td class="py-1.5 text-center">
										{#if note.note_type}
											<span class="rounded-full bg-primary/15 px-1.5 py-0.5 text-primary">{note.note_type}</span>
										{:else}
											<span class="text-muted-foreground">-</span>
										{/if}
									</td>
									<td class="py-1.5 text-center">{note.is_daily_note ? 'Y' : ''}</td>
									<td class="py-1.5 text-center text-muted-foreground">{note.status}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>

				<!-- 페이지네이션 -->
				<div class="mt-3 flex items-center justify-center gap-2">
					<button
						class="rounded-md border border-border px-3 py-1 text-xs disabled:opacity-40"
						disabled={notesPage === 0}
						onclick={() => { notesPage--; loadNotes(); }}
					>이전</button>
					<span class="text-xs text-muted-foreground">{notesPage + 1} / {Math.max(1, Math.ceil(notes.total / PAGE_SIZE))}</span>
					<button
						class="rounded-md border border-border px-3 py-1 text-xs disabled:opacity-40"
						disabled={(notesPage + 1) * PAGE_SIZE >= notes.total}
						onclick={() => { notesPage++; loadNotes(); }}
					>다음</button>
				</div>
			</div>
		</div>

	<!-- 분류 탭 -->
	{:else if activeTab === 'classify'}
		<div class="space-y-4">
			<div class="rounded-lg border border-border bg-card p-4">
				<div class="mb-3 flex flex-wrap items-center gap-3">
					<h3 class="text-sm font-semibold text-foreground">노트 분류</h3>
					<label class="flex items-center gap-1.5 text-xs text-muted-foreground">
						<input type="checkbox" bind:checked={useLlm} class="size-3.5" />
						LLM 사용
					</label>
					<button
						class="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
						onclick={startClassify}
						disabled={classifyState.status === 'running'}
					>
						{classifyState.status === 'running' ? '분류 중...' : '분류 시작'}
					</button>
				</div>
				{#if classifyState.status === 'running'}
					<p class="text-xs text-muted-foreground">{classifyState.processed}/{classifyState.total} 처리 중...</p>
				{:else if classifyState.status === 'completed'}
					<p class="text-xs text-green-500">분류 완료</p>
				{/if}
			</div>

			<!-- 일괄 승인 -->
			<div class="rounded-lg border border-border bg-card p-4">
				<div class="mb-3 flex flex-wrap items-center gap-2">
					<h3 class="text-sm font-semibold text-foreground">분류 리뷰</h3>
					<span class="text-xs text-muted-foreground">총 {classifyNotes.total}개</span>
					<button class="rounded-md border border-border px-2 py-1 text-xs hover:bg-accent" onclick={selectAll}>전체 선택</button>
					<button class="rounded-md border border-border px-2 py-1 text-xs hover:bg-accent" onclick={deselectAll}>해제</button>
					{#if selectedNoteIds.length > 0}
						<select bind:value={approveType} class="rounded-md border border-border bg-background px-2 py-1 text-xs">
							<option value="memo">memo</option>
							<option value="record">record</option>
							<option value="daily">daily</option>
							<option value="other">other</option>
						</select>
						<button
							class="rounded-md bg-green-600 px-3 py-1 text-xs text-white hover:bg-green-700"
							onclick={approveSelected}
						>
							{selectedNoteIds.length}개 승인
						</button>
					{/if}
				</div>

				<div class="overflow-x-auto">
					<table class="w-full text-xs">
						<thead>
							<tr class="border-b border-border text-muted-foreground">
								<th class="pb-2 text-left">선택</th>
								<th class="pb-2 text-left font-medium">파일명</th>
								<th class="pb-2 text-center font-medium">유형</th>
								<th class="pb-2 text-center font-medium">일일</th>
								<th class="pb-2 text-center font-medium">Frontmatter</th>
								<th class="pb-2 text-center font-medium">상태</th>
							</tr>
						</thead>
						<tbody>
							{#each classifyNotes.items as note}
								<tr class="border-b border-border/50 hover:bg-accent/30">
									<td class="py-1.5">
										<input
											type="checkbox"
											checked={selectedNoteIds.includes(note.id)}
											onchange={() => toggleSelect(note.id)}
											class="size-3.5"
										/>
									</td>
									<td class="py-1.5 text-foreground">{note.file_name}</td>
									<td class="py-1.5 text-center">
										{#if note.note_type}
											<span class="rounded-full bg-primary/15 px-1.5 py-0.5 text-primary">{note.note_type}</span>
										{:else}
											<span class="text-muted-foreground">미분류</span>
										{/if}
									</td>
									<td class="py-1.5 text-center">{note.is_daily_note ? 'Y' : ''}</td>
									<td class="py-1.5 text-center">{note.has_frontmatter ? 'Y' : ''}</td>
									<td class="py-1.5 text-center text-muted-foreground">{note.status}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
		</div>

	<!-- 추출 탭 -->
	{:else if activeTab === 'extract'}
		<div class="space-y-4">
			<div class="rounded-lg border border-border bg-card p-4">
				<div class="mb-3 flex flex-wrap items-center gap-3">
					<h3 class="text-sm font-semibold text-foreground">정보 추출 (memo 노트 대상)</h3>
					<button
						class="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
						onclick={startExtract}
						disabled={extractState.status === 'running'}
					>
						{extractState.status === 'running' ? '추출 중...' : '추출 시작'}
					</button>
					{#if extractResults.total > 0}
						<button
							class="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
							onclick={exportJson}
						>
							JSON 내보내기
						</button>
					{/if}
				</div>
				{#if extractState.status === 'running'}
					<p class="text-xs text-muted-foreground">{extractState.processed}/{extractState.total} 처리 중...</p>
				{:else if extractState.status === 'completed'}
					<p class="text-xs text-green-500">추출 완료 ({extractResults.total}개)</p>
				{/if}
			</div>

			{#if extractResults.total > 0}
				<TabNav tabs={extractTabs} bind:activeTab={extractTab} variant="secondary" />

				<div class="space-y-3">
					{#each extractResults.items as item}
						{@const data = item.extracted}
						{@const list =
							extractTab === 'todos'
								? data.todos ?? []
								: extractTab === 'urls'
									? data.urls ?? []
									: data.code_snippets ?? []}
						{#if list.length > 0}
							<div class="rounded-lg border border-border bg-card p-3">
								<div class="mb-2 text-xs font-medium text-foreground">{item.file_name}</div>
								<ul class="space-y-1">
									{#each list as entry}
										<li class="text-xs text-muted-foreground">
											{#if extractTab === 'urls'}
												<a href={entry} target="_blank" rel="noreferrer" class="text-primary hover:underline">{entry}</a>
											{:else if extractTab === 'code'}
												<pre class="overflow-x-auto rounded bg-accent/50 p-1 text-xs">{entry}</pre>
											{:else}
												• {entry}
											{/if}
										</li>
									{/each}
								</ul>
							</div>
						{/if}
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
