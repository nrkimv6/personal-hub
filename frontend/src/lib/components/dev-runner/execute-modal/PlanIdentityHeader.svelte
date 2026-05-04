<script lang="ts">
	import { Play, X } from 'lucide-svelte';

	interface Props {
		filename: string;
		status?: string | null;
		runningEngine?: string | null;
		titleId: string;
		onClose: () => void;
	}

	let { filename, status = null, runningEngine = null, titleId, onClose }: Props = $props();

	function truncateFilename(value: string): string {
		if (value.length <= 40) return value;
		return `${value.slice(0, 18)}...${value.slice(-18)}`;
	}

	function getStatusClass(value: string | null): string {
		switch (value) {
			case '구현완료':
			case '완료':
				return 'bg-green-100 text-green-700';
			case '구현중':
				return 'bg-blue-100 text-blue-700';
			case '검토대기':
				return 'bg-yellow-100 text-yellow-700';
			case '검토완료':
				return 'bg-orange-100 text-orange-700';
			case '수정필요':
				return 'bg-red-100 text-red-700';
			case '머지대기':
				return 'bg-teal-100 text-teal-700';
			case '보류':
				return 'bg-muted text-muted-foreground';
			default:
				return 'bg-muted text-muted-foreground';
		}
	}
</script>

<div class="flex items-center justify-between border-b border-border px-5 py-3.5 shrink-0">
	<div class="flex items-center gap-3 min-w-0">
		<h2 id={titleId} class="truncate font-mono text-sm font-medium text-foreground" title={filename}>
			{truncateFilename(filename)}
		</h2>

		{#if status}
			<span class={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${getStatusClass(status)}`}>
				{status}
			</span>
		{/if}

		{#if runningEngine}
			<span class="inline-flex items-center gap-1.5 rounded-md bg-info-light text-info border border-info px-2 py-0.5 text-xs font-medium">
				<Play class="h-3 w-3" />
				Run · {runningEngine}
			</span>
		{/if}
	</div>

	<button
		type="button"
		onclick={onClose}
		class="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
		aria-label="닫기"
	>
		<X class="h-3.5 w-3.5" />
	</button>
</div>
