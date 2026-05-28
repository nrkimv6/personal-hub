<script lang="ts">
	import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-svelte';
	import type { DevRunnerReadinessResponse } from '$lib/api';

	interface Props {
		readiness: DevRunnerReadinessResponse | null;
		loading?: boolean;
		error?: string | null;
		onRefresh: () => void | Promise<void>;
	}

	let {
		readiness,
		loading = false,
		error = null,
		onRefresh
	}: Props = $props();

	let toneClass = $derived(
		readiness?.severity === 'blocker'
			? 'border-red-200 bg-red-50 text-red-800'
			: readiness?.severity === 'warning'
				? 'border-amber-200 bg-amber-50 text-amber-800'
				: 'border-emerald-200 bg-emerald-50 text-emerald-800'
	);

	let statusText = $derived(
		loading
			? '점검 중'
			: error
				? '점검 실패'
				: readiness?.severity === 'blocker'
					? `차단 ${readiness.blockers}개`
					: readiness?.severity === 'warning'
						? `주의 ${readiness.warnings}개`
						: '시작 가능'
	);

	function itemClass(severity: string): string {
		if (severity === 'blocker') return 'text-red-700';
		if (severity === 'warning') return 'text-amber-700';
		return 'text-emerald-700';
	}
</script>

<div class={`border-b px-5 py-3 ${toneClass}`}>
	<div class="flex items-start justify-between gap-3">
		<div class="min-w-0 space-y-2">
			<div class="flex items-center gap-2">
				{#if loading}
					<Loader2 class="h-4 w-4 animate-spin shrink-0" />
				{:else if readiness?.severity === 'ok'}
					<CheckCircle2 class="h-4 w-4 shrink-0" />
				{:else}
					<AlertTriangle class="h-4 w-4 shrink-0" />
				{/if}
				<span class="text-xs font-semibold uppercase tracking-wide">Readiness</span>
				<span class="rounded border border-current/20 px-1.5 py-0.5 text-[10px] font-mono">{statusText}</span>
			</div>

			{#if error}
				<p class="text-xs">{error}</p>
			{:else if readiness}
				<div class="grid gap-1.5 text-xs sm:grid-cols-3">
					{#each readiness.items as item}
						<div class="min-w-0">
							<div class={`font-medium ${itemClass(item.severity)}`}>{item.label}</div>
							<div class="truncate opacity-85" title={item.action ?? item.message}>{item.message}</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<button
			type="button"
			class="shrink-0 rounded border border-current/25 px-2 py-1 text-[11px] font-medium transition-colors hover:bg-white/40 disabled:opacity-50"
			onclick={onRefresh}
			disabled={loading}
			title="readiness 다시 점검"
		>
			새로고침
		</button>
	</div>
</div>
