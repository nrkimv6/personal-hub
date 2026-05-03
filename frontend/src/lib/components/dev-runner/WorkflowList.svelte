<script lang="ts">
	import { devRunnerWorkflowApi, type WorkflowResponse } from '$lib/api';
	import { toast } from '$lib/stores/toast';

	let workflows = $state<WorkflowResponse[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let resetLoading = $state(false);
	let statusFilter = $state('');
	let selectedId = $state<number | null>(null);

	const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
		planned:       { label: '예정',           cls: 'bg-muted text-muted-foreground' },
		running:       { label: '실행중',          cls: 'bg-blue-100 text-blue-700 animate-pulse' },
		merge_pending: { label: '머지 대기',       cls: 'bg-yellow-100 text-yellow-700' },
		merging:       { label: '머지중',          cls: 'bg-orange-100 text-orange-700' },
		merged:        { label: '완료',            cls: 'bg-green-100 text-green-700' },
		failed:        { label: '실패',            cls: 'bg-red-100 text-red-700' },
		cancelled:     { label: '취소',            cls: 'bg-muted text-muted-foreground line-through' },
	};

	async function load() {
		loading = true;
		error = null;
		try {
			workflows = await devRunnerWorkflowApi.list(statusFilter ? { status: statusFilter } : undefined);
		} catch (e) {
			error = String(e);
		} finally {
			loading = false;
		}
	}

	async function resetAllOrphans() {
		resetLoading = true;
		try {
			const result = await devRunnerWorkflowApi.resetAllOrphans();
			if (result.reset_count > 0) await load();
		} catch (err) {
			error = `고아 리셋 실패: ${err}`;
		} finally {
			resetLoading = false;
		}
	}

	async function cancel(id: number, e: MouseEvent) {
		e.stopPropagation();
		try {
			const updated = await devRunnerWorkflowApi.cancel(id);
			workflows = workflows.map(w => w.id === id ? updated : w);
		} catch (err) {
			const message = err instanceof Error ? err.message : String(err);
			toast.error(`취소 실패: ${message}`);
		}
	}

	function formatDt(dt: string | null): string {
		if (!dt) return '-';
		return new Date(dt).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
	}

	$effect(() => {
		statusFilter;
		void load();
	});
</script>

<div class="flex flex-col gap-3 p-4 h-full min-h-0 overflow-hidden">
	<!-- 헤더 -->
	<div class="flex items-center justify-between shrink-0">
		<h3 class="text-[11px] font-bold text-muted-foreground uppercase tracking-wider">Workflows</h3>
		<div class="flex items-center gap-1.5">
			<select
				bind:value={statusFilter}
				class="text-[10px] border border-border rounded bg-background text-foreground px-1 py-0.5 outline-none focus:border-primary"
			>
				<option value="">All</option>
				{#each Object.entries(STATUS_BADGE) as [val, { label }]}
					<option value={val}>{label}</option>
				{/each}
			</select>
			<button
				onclick={resetAllOrphans}
				class="p-1 rounded hover:bg-orange-50 text-orange-500 transition-colors disabled:opacity-50"
				disabled={resetLoading}
				title="Reset Orphans"
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
			</button>
			<button
				onclick={load}
				class="p-1 rounded hover:bg-muted text-muted-foreground transition-colors"
				title="Refresh"
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5 {loading ? 'animate-spin' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
			</button>
		</div>
	</div>

	<!-- 리스트 -->
	<div class="flex-1 min-h-0 overflow-y-auto pr-0.5 dr-scrollbar-thin">
		{#if loading && workflows.length === 0}
			<div class="flex items-center justify-center py-10">
				<div class="animate-spin rounded-full h-5 w-5 border-b-2 border-primary"></div>
			</div>
		{:else if error}
			<div class="bg-red-50 border border-red-100 text-red-600 text-[10px] p-2 rounded mb-3">{error}</div>
		{:else if workflows.length === 0}
			<div class="flex flex-col items-center justify-center py-10 text-muted-foreground">
				<svg xmlns="http://www.w3.org/2000/svg" class="w-8 h-8 mb-2 opacity-20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
				<p class="text-[11px] italic">No workflows found</p>
			</div>
		{:else}
			<div class="space-y-2 pb-2">
				{#each workflows as wf}
					{@const badge = STATUS_BADGE[wf.status] ?? { label: wf.status, cls: 'bg-muted text-muted-foreground' }}
					<div 
						class="rounded-lg border border-border bg-card text-card-foreground shadow-sm overflow-hidden flex flex-col transition-all hover:border-primary/30 {selectedId === wf.id ? 'ring-1 ring-primary/30 border-primary/30' : ''}"
					>
						<!-- 요약 정보 행 -->
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<div 
							class="px-3 py-2.5 cursor-pointer hover:bg-muted transition-colors flex flex-col gap-1.5"
							onclick={() => selectedId = selectedId === wf.id ? null : wf.id}
							role="button"
							tabindex="0"
						>
							<div class="flex items-center justify-between gap-2">
								<span class="text-[11px] font-mono font-bold text-foreground truncate flex-1">{wf.slug}</span>
								<span class="rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase shrink-0 {badge.cls}">
									{badge.label}
								</span>
							</div>
							
							<div class="flex items-center justify-between">
								<div class="flex items-center gap-2 text-[9px] text-muted-foreground">
									<span class="flex items-center gap-1"><svg class="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>{formatDt(wf.created_at)}</span>
									{#if wf.engine}
										<span class="bg-muted px-1 rounded text-muted-foreground font-mono">{wf.engine}</span>
									{/if}
								</div>
								
								<div class="flex items-center gap-1.5">
									{#if wf.status === 'planned' || wf.status === 'running'}
										<button
											onclick={(e) => cancel(wf.id, e)}
											class="p-1 rounded hover:bg-red-50 text-red-400 transition-colors"
											title="Cancel"
										>
											<svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
										</button>
									{/if}
									<svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3 text-muted-foreground transition-transform {selectedId === wf.id ? 'rotate-180' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
								</div>
							</div>
						</div>

						<!-- 상세 정보 (선택 시) -->
						{#if selectedId === wf.id}
							<div class="px-3 py-3 border-t border-border bg-muted/50 flex flex-col gap-2 text-[10px]">
								{#if wf.plan_file}
									<div class="flex flex-col gap-0.5">
										<span class="text-muted-foreground font-bold uppercase text-[8px] tracking-tighter">Plan File</span>
										<span class="font-mono text-muted-foreground break-all">{wf.plan_file}</span>
									</div>
								{/if}
								<div class="grid grid-cols-2 gap-2">
									{#if wf.branch}
										<div class="flex flex-col gap-0.5">
											<span class="text-muted-foreground font-bold uppercase text-[8px] tracking-tighter">Branch</span>
											<span class="font-mono text-blue-600 truncate">{wf.branch}</span>
										</div>
									{/if}
									{#if wf.commit_hash}
										<div class="flex flex-col gap-0.5">
											<span class="text-muted-foreground font-bold uppercase text-[8px] tracking-tighter">Commit</span>
											<span class="font-mono text-muted-foreground">{wf.commit_hash.slice(0, 8)}</span>
										</div>
									{/if}
								</div>
								{#if wf.error_message}
									<div class="mt-1 p-2 bg-red-50 border border-red-100 rounded text-red-600 break-words leading-relaxed">
										<span class="font-bold uppercase text-[8px] block mb-0.5 opacity-70">Error Message</span>
										{wf.error_message}
									</div>
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
