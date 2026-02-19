<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { Activity, ChevronUp, ChevronDown, CheckCircle2, Loader2, AlertCircle } from 'lucide-svelte';

	interface Task {
		id: number;
		name: string;
		status: 'running' | 'done' | 'error';
		progress: number;
	}

	let tasks = $state<Task[]>([]);
	let expanded = $state(false);
	let pollingId: ReturnType<typeof setInterval> | null = null;

	let runningCount = $derived(tasks.filter((t) => t.status === 'running').length);

	async function loadTasks() {
		try {
			const res = await fetchWithTimeout('/api/ic/stats/tasks');
			if (!res.ok) return;
			const data = await res.json();
			tasks = data.tasks ?? [];
		} catch {
			// 폴링 중 실패 무시
		}
	}

	onMount(() => {
		loadTasks();
		// 5초 간격 폴링
		pollingId = setInterval(loadTasks, 5000);
	});

	onDestroy(() => {
		if (pollingId) clearInterval(pollingId);
	});
</script>

{#if tasks.length > 0}
<div class="sticky bottom-0 z-40 border-t border-border bg-card/95 backdrop-blur-sm">
	<button
		onclick={() => (expanded = !expanded)}
		class="flex w-full items-center justify-between px-4 py-1.5 text-xs"
	>
		<div class="flex items-center gap-2">
			<Activity class="size-3 text-primary" />
			<span class="text-muted-foreground">
				{#if runningCount > 0}
					<span class="font-medium text-primary">{runningCount}</span> background
					{runningCount === 1 ? 'task' : 'tasks'} running
				{:else}
					All systems idle
				{/if}
			</span>
		</div>
		<div class="flex items-center gap-2 text-muted-foreground">
			<span class="font-mono">v0.1.0</span>
			{#if expanded}
				<ChevronDown class="size-3" />
			{:else}
				<ChevronUp class="size-3" />
			{/if}
		</div>
	</button>

	{#if expanded}
		<div class="border-t border-border px-4 py-2">
			<div class="flex flex-col gap-2">
				{#each tasks as task (task.id)}
					<div class="flex items-center gap-3 text-xs">
						{#if task.status === 'running'}
							<Loader2 class="size-3 animate-spin text-primary" />
						{:else if task.status === 'done'}
							<CheckCircle2 class="size-3 text-success" />
						{:else}
							<AlertCircle class="size-3 text-destructive" />
						{/if}
						<span class="flex-1 text-foreground">{task.name}</span>
						<div class="h-1 w-24 overflow-hidden rounded-full bg-secondary">
							<div
								class="h-full rounded-full transition-all {task.status === 'done'
									? 'bg-success'
									: 'bg-primary'}"
								style="width: {task.progress}%"
							></div>
						</div>
						<span class="w-8 text-right font-mono text-muted-foreground">
							{task.progress}%
						</span>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>
{/if}
