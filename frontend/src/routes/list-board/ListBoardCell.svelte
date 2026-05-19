<script lang="ts">
	import type { ListBoardColumn } from '$lib/api';

	interface Props {
		column: ListBoardColumn;
		value: unknown;
		saving?: boolean;
		onchange: (newValue: unknown) => void;
	}

	let { column, value, saving = false, onchange }: Props = $props();

	let textDraft = $state(typeof value === 'string' ? value : '');
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;

	function handleCheckbox(e: Event) {
		onchange((e.target as HTMLInputElement).checked);
	}

	function handleTextInput(e: Event) {
		textDraft = (e.target as HTMLInputElement).value;
		if (debounceTimer !== null) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			onchange(textDraft || null);
		}, 800);
	}

	function handleTextBlur() {
		if (debounceTimer !== null) {
			clearTimeout(debounceTimer);
			debounceTimer = null;
		}
		onchange(textDraft || null);
	}

	function handleSelect(e: Event) {
		const v = (e.target as HTMLSelectElement).value;
		onchange(v || null);
	}

	const PRIORITY_OPTIONS = ['low', 'medium', 'high', 'critical'];
	const PRIORITY_LABELS: Record<string, string> = {
		low: 'Low', medium: 'Med', high: 'High', critical: '!!'
	};
	const PRIORITY_COLORS: Record<string, string> = {
		low: 'text-muted-foreground',
		medium: 'text-warning',
		high: 'text-warning-foreground',
		critical: 'text-destructive',
	};
</script>

<td class="px-2 py-2 whitespace-nowrap" class:opacity-50={saving}>
	{#if column.column_type === 'checkbox'}
		<input
			type="checkbox"
			checked={value === true}
			class="cursor-pointer accent-primary"
			onchange={handleCheckbox}
		/>
	{:else if column.column_type === 'text'}
		<input
			type="text"
			value={textDraft}
			class="w-full min-w-32 rounded-md border border-transparent bg-transparent px-1 text-xs text-foreground placeholder:text-muted-foreground focus:border-ring focus:bg-muted/40 focus:outline-none focus:ring-1 focus:ring-ring"
			placeholder="—"
			oninput={handleTextInput}
			onblur={handleTextBlur}
		/>
	{:else if column.column_type === 'select'}
		<select
			class="rounded-md border border-transparent bg-transparent text-xs text-foreground focus:border-ring focus:bg-muted/40 focus:outline-none focus:ring-1 focus:ring-ring"
			value={typeof value === 'string' ? value : ''}
			onchange={handleSelect}
		>
			<option value="">—</option>
			{#each column.options as opt}
				<option value={opt}>{opt}</option>
			{/each}
		</select>
	{:else if column.column_type === 'priority'}
		<select
			class="rounded-md border border-transparent bg-transparent text-xs focus:border-ring focus:bg-muted/40 focus:outline-none focus:ring-1 focus:ring-ring {value ? PRIORITY_COLORS[value as string] ?? '' : 'text-muted-foreground'}"
			value={typeof value === 'string' ? value : ''}
			onchange={handleSelect}
		>
			<option value="">—</option>
			{#each PRIORITY_OPTIONS as p}
				<option value={p}>{PRIORITY_LABELS[p]}</option>
			{/each}
		</select>
	{/if}
</td>
