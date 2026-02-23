<script lang="ts">
	import { onMount } from 'svelte';
	import { Search, ChevronLeft, ChevronRight } from 'lucide-svelte';

	// 필터 상태
	let fileGroup = $state('');
	let extension = $state('');
	let status = $state('');
	let search = $state('');
	let page = $state(1);
	const pageSize = 50;

	// 데이터
	let result = $state<any>(null);
	let isLoading = $state(false);

	const FILE_GROUP_OPTIONS = [
		{ value: '', label: '전체' },
		{ value: 'music', label: '음악' },
		{ value: 'archive', label: '압축파일' },
		{ value: 'document', label: '문서' },
		{ value: 'installer', label: '설치파일' },
		{ value: 'game', label: '게임' },
		{ value: 'misc', label: '기타' }
	];

	const STATUS_OPTIONS = [
		{ value: '', label: '전체 상태' },
		{ value: 'pending', label: '대기' },
		{ value: 'metadata_extracted', label: '메타데이터 추출' },
		{ value: 'rule_classified', label: '규칙 분류' },
		{ value: 'llm_classified', label: 'LLM 분류' },
		{ value: 'approved', label: '승인됨' },
		{ value: 'moved', label: '이동됨' },
		{ value: 'error', label: '오류' }
	];

	async function fetchFiles() {
		isLoading = true;
		try {
			const params = new URLSearchParams();
			if (fileGroup) params.set('file_group', fileGroup);
			if (extension) params.set('extension', extension);
			if (status) params.set('status', status);
			if (search) params.set('search', search);
			params.set('page', String(page));
			params.set('page_size', String(pageSize));

			const res = await fetch(`/api/fc/files?${params}`);
			if (res.ok) result = await res.json();
		} finally {
			isLoading = false;
		}
	}

	function formatSize(bytes: number | null): string {
		if (!bytes) return '-';
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
		return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
	}

	function onSearch() {
		page = 1;
		fetchFiles();
	}

	onMount(() => fetchFiles());
</script>

<div class="space-y-4">
	<h2 class="text-xl font-bold text-foreground">파일 목록</h2>

	<!-- 필터 -->
	<div class="flex flex-wrap gap-2">
		<!-- 파일 그룹 탭 -->
		<div class="flex gap-1 rounded-lg border border-border bg-muted p-1">
			{#each FILE_GROUP_OPTIONS as opt}
				<button
					onclick={() => { fileGroup = opt.value; page = 1; fetchFiles(); }}
					class="rounded px-3 py-1 text-xs font-medium transition-all {fileGroup === opt.value
						? 'bg-card text-foreground shadow-sm'
						: 'text-muted-foreground hover:text-foreground'}"
				>
					{opt.label}
				</button>
			{/each}
		</div>

		<!-- 상태 필터 -->
		<select
			bind:value={status}
			onchange={() => { page = 1; fetchFiles(); }}
			class="rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground"
		>
			{#each STATUS_OPTIONS as opt}
				<option value={opt.value}>{opt.label}</option>
			{/each}
		</select>

		<!-- 검색 -->
		<div class="flex gap-1">
			<div class="relative">
				<Search class="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
				<input
					bind:value={search}
					onkeydown={(e) => e.key === 'Enter' && onSearch()}
					type="text"
					placeholder="파일명 검색..."
					class="rounded-md border border-border bg-background py-1 pl-7 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 w-48"
				/>
			</div>
			<button
				onclick={onSearch}
				class="rounded-md bg-primary px-3 py-1 text-sm font-medium text-primary-foreground hover:bg-primary/90"
			>
				검색
			</button>
		</div>
	</div>

	<!-- 테이블 -->
	{#if isLoading}
		<div class="text-center text-sm text-muted-foreground py-8">로딩 중...</div>
	{:else if result}
		<div class="overflow-x-auto rounded-lg border border-border">
			<table class="w-full text-sm">
				<thead class="bg-muted/50">
					<tr>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">파일명</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">그룹</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">확장자</th>
						<th class="px-3 py-2 text-right font-medium text-muted-foreground">크기</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">상태</th>
					</tr>
				</thead>
				<tbody>
					{#each result.items as item}
						<tr class="border-t border-border hover:bg-muted/30">
							<td class="max-w-[300px] truncate px-3 py-2 text-foreground" title={item.file_path}>
								{item.file_name}
							</td>
							<td class="px-3 py-2 text-muted-foreground">{item.file_group}</td>
							<td class="px-3 py-2 text-muted-foreground">{item.extension ?? '-'}</td>
							<td class="px-3 py-2 text-right text-muted-foreground">{formatSize(item.file_size)}</td>
							<td class="px-3 py-2">
								<span class="rounded-full px-2 py-0.5 text-xs font-medium
									{item.status === 'moved' ? 'bg-green-500/15 text-green-600' :
									item.status === 'approved' ? 'bg-blue-500/15 text-blue-600' :
									item.status === 'error' ? 'bg-red-500/15 text-red-600' :
									'bg-muted text-muted-foreground'}">
									{item.status}
								</span>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- 페이지네이션 -->
		<div class="flex items-center justify-between text-sm text-muted-foreground">
			<span>총 {result.total.toLocaleString()}개</span>
			<div class="flex items-center gap-2">
				<button
					onclick={() => { page--; fetchFiles(); }}
					disabled={page <= 1}
					class="flex items-center rounded-md border border-border px-2 py-1 hover:bg-accent disabled:opacity-40"
				>
					<ChevronLeft class="size-4" />
				</button>
				<span>{page} / {result.total_pages}</span>
				<button
					onclick={() => { page++; fetchFiles(); }}
					disabled={page >= result.total_pages}
					class="flex items-center rounded-md border border-border px-2 py-1 hover:bg-accent disabled:opacity-40"
				>
					<ChevronRight class="size-4" />
				</button>
			</div>
		</div>
	{/if}
</div>
