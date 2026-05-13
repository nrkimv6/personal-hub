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
		low: 'text-zinc-400',
		medium: 'text-yellow-400',
		high: 'text-orange-400',
		critical: 'text-red-400',
	};
</script>

<td class="py-0.5 pr-2" class:opacity-50={saving}>
	{#if column.column_type === 'checkbox'}
		<input
			type="checkbox"
			checked={value === true}
			class="cursor-pointer accent-blue-500"
			onchange={handleCheckbox}
		/>
	{:else if column.column_type === 'text'}
		<input
			type="text"
			value={textDraft}
			class="w-full rounded border border-transparent bg-transparent px-1 text-xs text-zinc-300 focus:border-zinc-500 focus:bg-zinc-800 focus:outline-none"
			placeholder="—"
			oninput={handleTextInput}
			onblur={handleTextBlur}
		/>
	{:else if column.column_type === 'select'}
		<select
			class="rounded border border-transparent bg-transparent text-xs text-zinc-300 focus:border-zinc-500 focus:bg-zinc-800 focus:outline-none"
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
			class="rounded border border-transparent bg-transparent text-xs focus:border-zinc-500 focus:bg-zinc-800 focus:outline-none {value ? PRIORITY_COLORS[value as string] ?? '' : 'text-zinc-500'}"
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
