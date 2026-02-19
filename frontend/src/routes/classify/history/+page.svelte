<svelte:head><title>이동 이력 — 이미지 분류기</title></svelte:head>

<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { History, RotateCcw, RefreshCw } from 'lucide-svelte';

	interface MoveHistory {
		id: number;
		file_path: string;
		file_size: number;
		status: string;
		final_category_id: number | null;
		extracted_date: string | null;
	}

	let history: MoveHistory[] = $state([]);
	let loading = $state(false);

	onMount(() => {
		loadHistory();
	});

	async function loadHistory() {
		loading = true;
		try {
			const response = await fetchWithTimeout('/api/ic/files?status=moved&limit=100');
			if (response.ok) {
				const data = await response.json();
				history = data.files || [];
			}
		} catch (err) {
			console.error('이력 로드 실패:', err);
		} finally {
			loading = false;
		}
	}

	async function rollback(id: number) {
		if (!confirm('이 파일을 원래 위치로 복원하시겠습니까?')) return;

		try {
			const res = await fetchWithTimeout(`/api/ic/files/${id}/rollback`, { method: 'POST' });
			if (!res.ok) throw new Error('복원 실패');
			await loadHistory();
		} catch (err) {
			alert('복원 실패');
		}
	}
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<History class="size-5 text-primary" />
				<h1 class="text-2xl font-bold tracking-tight">이동 이력</h1>
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

	<!-- 테이블 -->
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
					<div class="flex items-center gap-4 px-5 py-3 hover:bg-muted/30 transition-colors">
						<div class="flex-1 min-w-0">
							<p class="font-mono text-xs text-foreground truncate">{item.file_path}</p>
							<p class="text-[10px] text-muted-foreground mt-0.5">
								ID: {item.id} · 카테고리: {item.final_category_id ?? '—'}
								{#if item.extracted_date}
									· {item.extracted_date}
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
	</div>
</div>
