<script lang="ts">
	import { onMount } from 'svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';

	let files = $state<any[]>([]);
	let categories = $state<any[]>([]);
	let isLoading = $state(false);
	let selectedIds = $state<Set<number>>(new Set());
	let bulkCategoryId = $state<number | null>(null);
	let message = $state('');

	async function fetchFiles() {
		isLoading = true;
		try {
			const res = await fetch('/api/fc/files?status=rule_classified&page_size=100');
			if (res.ok) {
				const data = await res.json();
				files = data.items || [];
			}
		} finally {
			isLoading = false;
		}
	}

	async function fetchCategories() {
		const res = await fetch('/api/fc/categories');
		if (res.ok) {
			const tree = await res.json();
			// 트리를 평탄화
			const flat: any[] = [];
			function flatten(nodes: any[], depth = 0) {
				for (const node of nodes) {
					flat.push({ ...node, depth });
					if (node.children?.length) flatten(node.children, depth + 1);
				}
			}
			flatten(tree);
			categories = flat;
		}
	}

	function toggleSelect(id: number) {
		const next = new Set(selectedIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selectedIds = next;
	}

	function selectAll() {
		selectedIds = new Set(files.map((f) => f.id));
	}

	function clearSelection() {
		selectedIds = new Set();
	}

	async function approveSelected() {
		if (selectedIds.size === 0) return;
		if (!bulkCategoryId) {
			message = '카테고리를 선택하세요';
			return;
		}
		const res = await fetch('/api/fc/classify/approve', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ file_ids: [...selectedIds], category_id: bulkCategoryId })
		});
		if (res.ok) {
			message = `${selectedIds.size}개 파일 승인 완료`;
			clearSelection();
			await fetchFiles();
		}
	}

	async function startRuleClassify() {
		await fetch('/api/fc/classify/rule/start', { method: 'POST' });
		message = '규칙 분류 시작됨';
		setTimeout(fetchFiles, 2000);
	}

	onMount(() => {
		fetchFiles();
		fetchCategories();
	});
</script>

<div class="space-y-4">
	<PageHeader title="분류 결과 리뷰" subtitle="파일 분류 결과를 검토하고 승인합니다">
		<button
			onclick={startRuleClassify}
			class="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
		>
			규칙 분류 실행
		</button>
	</PageHeader>

	{#if message}
		<div class="rounded-md bg-blue-500/10 px-3 py-2 text-sm text-blue-600">{message}</div>
	{/if}

	<!-- 벌크 액션 -->
	<div class="flex items-center gap-2">
		<button onclick={selectAll} class="text-sm text-primary hover:underline">전체 선택</button>
		<span class="text-muted-foreground">|</span>
		<button onclick={clearSelection} class="text-sm text-muted-foreground hover:underline">선택 해제</button>
		<span class="text-sm text-muted-foreground">({selectedIds.size}개 선택)</span>

		<select
			bind:value={bulkCategoryId}
			class="ml-auto rounded-md border border-border bg-background px-2 py-1 text-sm"
		>
			<option value={null}>카테고리 선택...</option>
			{#each categories as cat}
				<option value={cat.id}>{'  '.repeat(cat.depth)}{cat.full_path}</option>
			{/each}
		</select>
		<button
			onclick={approveSelected}
			disabled={selectedIds.size === 0 || !bulkCategoryId}
			class="rounded-md bg-green-600 px-3 py-1 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-40"
		>
			일괄 승인
		</button>
	</div>

	<!-- 파일 목록 -->
	{#if isLoading}
		<div class="py-8 text-center text-sm text-muted-foreground">로딩 중...</div>
	{:else if files.length === 0}
		<div class="py-8 text-center text-sm text-muted-foreground">분류된 파일이 없습니다</div>
	{:else}
		<div class="overflow-x-auto rounded-lg border border-border">
			<table class="w-full text-sm">
				<thead class="bg-muted/50">
					<tr>
						<th class="w-8 px-3 py-2"></th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">파일명</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">그룹</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">분류 카테고리</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">상태</th>
					</tr>
				</thead>
				<tbody>
					{#each files as file}
						<tr
							class="border-t border-border hover:bg-muted/30 {selectedIds.has(file.id) ? 'bg-primary/5' : ''}"
							onclick={() => toggleSelect(file.id)}
						>
							<td class="px-3 py-2">
								<input
									type="checkbox"
									checked={selectedIds.has(file.id)}
									onclick={(e) => e.stopPropagation()}
									onchange={() => toggleSelect(file.id)}
									class="rounded"
								/>
							</td>
							<td class="max-w-[280px] truncate px-3 py-2 text-foreground" title={file.file_path}>
								{file.file_name}
							</td>
							<td class="px-3 py-2 text-muted-foreground">{file.file_group}</td>
							<td class="px-3 py-2 text-muted-foreground">
								{file.rule_category_path ?? file.rule_category_id ?? '-'}
							</td>
							<td class="px-3 py-2">
								<span class="rounded-full bg-blue-500/10 px-2 py-0.5 text-xs text-blue-600">
									{file.status}
								</span>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
