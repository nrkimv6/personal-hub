<script lang="ts">
	import { RefreshCw, ChevronLeft, ChevronRight } from 'lucide-svelte';
	import { createPagePagination } from '$lib/utils/pagination.svelte';
	import { archiveScheduleApi, type ArchiveLLMRequestRow, type ArchiveLLMRequestDetail } from '$lib/api/plan-records';

	interface Props {
		onSelectRequest?: (req: ArchiveLLMRequestDetail) => void;
	}

	let { onSelectRequest }: Props = $props();

	const pager = createPagePagination(50);

	let items = $state<ArchiveLLMRequestRow[]>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);

	let statusFilter = $state('pending,processing,failed');
	let categoryFilter = $state('');

	async function load() {
		loading = true;
		error = null;
		try {
			const res = await archiveScheduleApi.listLLMRequests({
				status: statusFilter || undefined,
				category: categoryFilter || undefined,
				page: pager.page,
				page_size: 50,
			});
			items = res.items;
			pager.total = res.total;
		} catch (e) {
			error = e instanceof Error ? e.message : '로드 실패';
		} finally {
			loading = false;
		}
	}

	async function openDetail(id: number) {
		try {
			const detail = await archiveScheduleApi.getLLMRequestDetail(id);
			onSelectRequest?.(detail);
		} catch (e) {
			// silently ignore
		}
	}

	$effect(() => {
		pager.reset();
		load();
	});

	const statusOptions = ['pending', 'processing', 'failed', 'completed'];
</script>

<div class="space-y-3">
	<div class="flex flex-wrap items-center gap-2">
		<span class="text-xs text-muted-foreground">상태 필터:</span>
		{#each statusOptions as s}
			{@const active = statusFilter.split(',').includes(s)}
			<button
				class="rounded border border-border px-2 py-0.5 text-xs {active ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}"
				onclick={() => {
					const parts = statusFilter ? statusFilter.split(',') : [];
					const idx = parts.indexOf(s);
					if (idx >= 0) parts.splice(idx, 1); else parts.push(s);
					statusFilter = parts.join(',');
					pager.reset(); load();
				}}
			>{s}</button>
		{/each}
		<select
			class="ml-auto rounded border border-border bg-background px-2 py-0.5 text-xs"
			bind:value={categoryFilter}
			onchange={() => { pager.reset(); load(); }}
		>
			<option value="">전체 카테고리</option>
			{#each ['timeout', 'quota', 'parse', 'network', 'other'] as c}
				<option value={c}>{c}</option>
			{/each}
		</select>
		<button
			class="rounded p-1 text-muted-foreground hover:bg-muted"
			onclick={load}
			title="새로고침"
		>
			<RefreshCw class="h-3 w-3 {loading ? 'animate-spin' : ''}" />
		</button>
	</div>

	{#if error}
		<div class="rounded bg-destructive/10 px-3 py-2 text-xs text-destructive">
			{error} — <button class="underline" onclick={load}>재시도</button>
		</div>
	{:else if loading && items.length === 0}
		<div class="space-y-1">
			{#each Array(5) as _}
				<div class="h-8 w-full animate-pulse rounded bg-muted"></div>
			{/each}
		</div>
	{:else if items.length === 0}
		<div class="rounded bg-muted/30 py-6 text-center text-xs text-muted-foreground">큐 없음</div>
	{:else}
		<div class="overflow-auto">
			<table class="w-full text-xs">
				<thead>
					<tr class="border-b border-border text-left text-muted-foreground">
						<th class="px-2 py-1.5">ID</th>
						<th class="px-2 py-1.5">상태</th>
						<th class="px-2 py-1.5">provider/model</th>
						<th class="px-2 py-1.5">category</th>
						<th class="px-2 py-1.5">record</th>
						<th class="px-2 py-1.5">요청시각</th>
						<th class="px-2 py-1.5">DB반영</th>
						<th class="px-2 py-1.5">액션</th>
					</tr>
				</thead>
				<tbody>
					{#each items as r}
						<tr class="border-b border-border/50 hover:bg-muted/30">
							<td class="px-2 py-1">{r.id}</td>
							<td class="px-2 py-1">
								<span class="rounded-full px-1.5 py-0.5 {
									r.status === 'completed' ? 'bg-green-100 text-green-700' :
									r.status === 'failed' ? 'bg-red-100 text-red-700' :
									r.status === 'processing' ? 'bg-blue-100 text-blue-700' :
									'bg-muted text-muted-foreground'
								}">{r.status}</span>
							</td>
							<td class="px-2 py-1">{r.provider}/{r.model}</td>
							<td class="px-2 py-1">
								{#if r.failure_category}
									<span class="rounded bg-red-100 px-1 text-red-700">{r.failure_category}</span>
								{:else}—{/if}
							</td>
							<td class="px-2 py-1">{r.record_id ?? '—'}</td>
							<td class="px-2 py-1 whitespace-nowrap">{r.requested_at?.slice(0, 16) ?? '—'}</td>
							<td class="px-2 py-1">
								{#if r.is_applied_to_record}
									<span class="rounded-full bg-green-100 px-1.5 text-xs text-green-700">DB반영 #{r.applied_request_id}</span>
								{:else}—{/if}
							</td>
							<td class="px-2 py-1 flex gap-1 flex-wrap">
								<button
									class="rounded border border-border px-1.5 py-0.5 text-xs hover:bg-muted"
									onclick={() => openDetail(r.id)}
								>상세</button>
								{#if r.record_id}
									<a
										class="rounded border border-border px-1.5 py-0.5 text-xs hover:bg-muted"
										href="/plans?id={r.record_id}"
										target="_blank"
										rel="noopener"
									>record</a>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<!-- Pagination -->
		<div class="flex items-center justify-between text-xs text-muted-foreground">
			<span>총 {pager.total}건</span>
			<div class="flex items-center gap-1">
				<button
					class="rounded p-0.5 hover:bg-muted disabled:opacity-40"
					disabled={pager.page <= 1}
					onclick={() => { pager.page -= 1; load(); }}
				>
					<ChevronLeft class="h-4 w-4" />
				</button>
				<span>{pager.page} / {pager.totalPages}</span>
				<button
					class="rounded p-0.5 hover:bg-muted disabled:opacity-40"
					disabled={pager.page >= pager.totalPages}
					onclick={() => { pager.page += 1; load(); }}
				>
					<ChevronRight class="h-4 w-4" />
				</button>
			</div>
		</div>
	{/if}
</div>
