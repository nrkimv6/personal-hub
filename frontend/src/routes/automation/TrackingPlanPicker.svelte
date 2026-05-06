<script lang="ts">
	import { planRecordsApi, type PlanRecord } from '$lib/api/plan-records';
	import type { LinkedPlan } from '$lib/api/tracking';

	interface Props {
		value: number[];
		alreadyLinked: LinkedPlan[];
		onChange: (ids: number[]) => void;
	}

	let { value, alreadyLinked, onChange }: Props = $props();

	let query = $state('');
	let results = $state<PlanRecord[]>([]);
	let searching = $state(false);
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	const linkedIds = $derived(new Set(alreadyLinked.map((l) => l.plan_record_id)));

	function handleInput(e: Event) {
		const q = (e.target as HTMLInputElement).value;
		query = q;
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => search(q), 300);
	}

	async function search(q: string) {
		searching = true;
		try {
			results = await planRecordsApi.list({ q: q || undefined, limit: 20 });
		} catch {
			results = [];
		} finally {
			searching = false;
		}
	}

	function toggle(id: number) {
		if (linkedIds.has(id)) return;
		const next = value.includes(id) ? value.filter((v) => v !== id) : [...value, id];
		onChange(next);
	}

	function isSelected(id: number) {
		return value.includes(id) || linkedIds.has(id);
	}
</script>

<div class="space-y-2">
	<div class="relative">
		<input
			type="text"
			placeholder="계획서 검색..."
			value={query}
			oninput={handleInput}
			class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
		/>
		{#if searching}
			<span class="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">검색 중...</span>
		{/if}
	</div>

	{#if value.length > 0}
		<div class="flex flex-wrap gap-1">
			{#each value as id}
				{@const linked = alreadyLinked.find((l) => l.plan_record_id === id)}
				{@const result = results.find((r) => r.id === id)}
				{@const label = linked?.title ?? result?.title ?? `plan #${id}`}
				{#if !linkedIds.has(id)}
					<span class="flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">
						{label}
						<button
							type="button"
							class="hover:text-destructive"
							onclick={() => onChange(value.filter((v) => v !== id))}
							aria-label="연결 해제"
						>×</button>
					</span>
				{/if}
			{/each}
		</div>
	{/if}

	{#if query && !searching}
		<div class="max-h-48 overflow-auto rounded-lg border border-border bg-card">
			{#if results.length === 0}
				<div class="p-3 text-center text-xs text-muted-foreground">검색 결과 없음</div>
			{:else}
				{#each results as record}
					{@const alreadyIn = linkedIds.has(record.id)}
					{@const selected = value.includes(record.id)}
					<label
						class="flex cursor-pointer items-start gap-2 p-2 text-sm hover:bg-muted/40 {alreadyIn ? 'opacity-50 cursor-not-allowed' : ''}"
					>
						<input
							type="checkbox"
							class="mt-0.5 shrink-0"
							checked={isSelected(record.id)}
							disabled={alreadyIn}
							onchange={() => toggle(record.id)}
						/>
						<div class="min-w-0">
							<div class="truncate font-medium">{record.title ?? record.file_path}</div>
							<div class="flex flex-wrap gap-1 text-xs text-muted-foreground">
								{#if record.status}
									<span class="rounded bg-muted px-1">{record.status}</span>
								{/if}
								{#if record.archived_at}
									<span class="rounded bg-amber-100 px-1 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">archived</span>
								{/if}
								{#if alreadyIn}
									<span class="rounded bg-primary/10 px-1 text-primary">연결됨</span>
								{/if}
								<span class="truncate">{record.file_path.split('/').pop()}</span>
							</div>
						</div>
					</label>
				{/each}
			{/if}
		</div>
	{/if}
</div>
