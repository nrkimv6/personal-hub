<script lang="ts">
	import { Calendar } from 'lucide-svelte';

	let { onpick } = $props<{ onpick: (date: string) => void }>();
	const today = new Date();
	const fmt = (date: Date) => date.toISOString().slice(0, 10);
	const offset = (days: number) => {
		const date = new Date(today);
		date.setDate(date.getDate() + days);
		return fmt(date);
	};
	const presets = [
		{ label: '오늘', date: fmt(today) },
		{ label: '1개월 후', date: offset(30) },
		{ label: '3개월 후', date: offset(90) },
		{ label: '6개월 후', date: offset(180) },
		{ label: '1년 후', date: offset(365) }
	];
</script>

<div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
	{#each presets as preset}
		<button type="button" onclick={() => onpick(preset.date)} class="rounded-md border border-border bg-card px-3 py-3 text-sm font-medium hover:bg-accent">
			{preset.label}
		</button>
	{/each}
	<label class="relative flex cursor-pointer items-center justify-center gap-1.5 rounded-md border border-border bg-card px-3 py-3 text-sm font-medium hover:bg-accent">
		<Calendar class="h-4 w-4" />
		직접 선택
		<input class="absolute h-0 w-0 opacity-0" type="date" min={fmt(today)} onchange={(event) => {
			const value = (event.currentTarget as HTMLInputElement).value;
			if (value) onpick(value);
		}} />
	</label>
</div>

