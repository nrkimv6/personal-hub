<script lang="ts">
	import { onMount } from 'svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';

	let previews = $state<any[]>([]);
	let moveStatus = $state<any>(null);
	let isLoading = $state(false);
	let selectedIds = $state<Set<number>>(new Set());
	let message = $state('');

	async function fetchStatus() {
		const res = await fetch('/api/fc/move/status');
		if (res.ok) moveStatus = await res.json();
	}

	async function loadPreview() {
		isLoading = true;
		try {
			const res = await fetch('/api/fc/move/preview', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: null })
			});
			if (res.ok) {
				const data = await res.json();
				previews = data.items || [];
			}
		} finally {
			isLoading = false;
		}
	}

	function toggleSelect(id: number) {
		const next = new Set(selectedIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selectedIds = next;
	}

	function selectAll() {
		selectedIds = new Set(previews.map((p) => p.file_id));
	}

	async function executeMove(ids?: number[]) {
		const res = await fetch('/api/fc/move/execute', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ file_ids: ids || null })
		});
		if (res.ok) {
			const data = await res.json();
			message = `${data.moved}개 이동 완료, 오류: ${data.errors}개`;
			await loadPreview();
			await fetchStatus();
		}
	}

	async function undoMove(file_id: number) {
		const res = await fetch(`/api/fc/move/undo/${file_id}`, { method: 'POST' });
		if (res.ok) {
			message = '되돌리기 완료';
			await loadPreview();
			await fetchStatus();
		}
	}

	onMount(() => {
		fetchStatus();
		loadPreview();
	});
</script>

<div class="space-y-4">
	<PageHeader title="파일 이동" subtitle="분류된 파일을 지정 경로로 이동합니다">
		{#if moveStatus}
			<span class="text-sm text-muted-foreground">
				이동됨: {moveStatus.moved}개 | 대기: {moveStatus.pending_move}개
			</span>
		{/if}
	</PageHeader>

	{#if message}
		<div class="rounded-md bg-blue-500/10 px-3 py-2 text-sm text-blue-600">{message}</div>
	{/if}

	<!-- 액션 버튼 -->
	<div class="flex gap-2">
		<button
			onclick={loadPreview}
			class="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
		>
			미리보기 새로고침
		</button>
		<button
			onclick={selectAll}
			class="text-sm text-primary hover:underline"
		>
			전체 선택
		</button>
		<button
			onclick={() => executeMove(selectedIds.size > 0 ? [...selectedIds] : undefined)}
			disabled={previews.length === 0}
			class="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
		>
			{selectedIds.size > 0 ? `선택 ${selectedIds.size}개 이동` : '전체 이동'}
		</button>
	</div>

	<!-- 미리보기 테이블 -->
	{#if isLoading}
		<div class="py-8 text-center text-sm text-muted-foreground">로딩 중...</div>
	{:else if previews.length === 0}
		<div class="py-8 text-center text-sm text-muted-foreground">이동할 파일이 없습니다 (승인된 파일 필요)</div>
	{:else}
		<div class="overflow-x-auto rounded-lg border border-border">
			<table class="w-full text-sm">
				<thead class="bg-muted/50">
					<tr>
						<th class="w-8 px-3 py-2"></th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">파일명</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">카테고리</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">목적지</th>
						<th class="px-3 py-2"></th>
					</tr>
				</thead>
				<tbody>
					{#each previews as item}
						<tr
							class="border-t border-border hover:bg-muted/30 {selectedIds.has(item.file_id) ? 'bg-primary/5' : ''}"
							onclick={() => toggleSelect(item.file_id)}
						>
							<td class="px-3 py-2">
								<input
									type="checkbox"
									checked={selectedIds.has(item.file_id)}
									onclick={(e) => e.stopPropagation()}
									onchange={() => toggleSelect(item.file_id)}
								/>
							</td>
							<td class="max-w-[200px] truncate px-3 py-2 text-foreground" title={item.source}>
								{item.source?.split(/[/\\]/).pop() ?? '-'}
							</td>
							<td class="px-3 py-2 text-muted-foreground">{item.category}</td>
							<td class="max-w-[300px] truncate px-3 py-2 text-xs text-muted-foreground" title={item.destination}>
								{item.destination}
							</td>
							<td class="px-3 py-2">
								<button
									onclick={(e) => { e.stopPropagation(); executeMove([item.file_id]); }}
									class="text-xs text-primary hover:underline"
								>이동</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
