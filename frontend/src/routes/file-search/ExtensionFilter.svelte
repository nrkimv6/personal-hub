<script lang="ts">
	import type { ExtensionSuggestionSection } from '$lib/types/fileSearch';

	interface Props {
		extensions: string[];
		suggestionGroups?: ExtensionSuggestionSection[];
		onchange: (exts: string[]) => void;
	}

	let { extensions = $bindable([]), suggestionGroups = [], onchange }: Props = $props();

	let customInput = $state('');

	const visibleSuggestionGroups = $derived(
		extensions.length >= 2 ? suggestionGroups.slice(0, 2) : suggestionGroups
	);

	function normalize(ext: string): string {
		return ext.trim().replace(/^\./, '').toLowerCase();
	}

	function toggle(ext: string) {
		const normalized = normalize(ext);
		const next = extensions.includes(normalized)
			? extensions.filter((item) => item !== normalized)
			: [...extensions, normalized];
		onchange(next);
	}

	function addCustom() {
		const ext = normalize(customInput);
		if (ext && !extensions.includes(ext)) {
			onchange([...extensions, ext]);
		}
		customInput = '';
	}

	function handleCustomKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			addCustom();
		}
	}
</script>

<div class="space-y-3">
	<div class="flex flex-wrap items-center gap-2">
		{#if extensions.length === 0}
			<span class="text-xs text-muted-foreground">확장자 제한 없음 (전체)</span>
		{:else}
			{#each extensions as ext}
				<button
					type="button"
					onclick={() => toggle(ext)}
					class="flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 font-mono text-xs text-primary transition-colors hover:border-destructive/30 hover:bg-destructive/10 hover:text-destructive"
				>
					.{ext}
					<span class="text-xs opacity-60">×</span>
				</button>
			{/each}
		{/if}

		<div class="flex items-center gap-1 rounded-full border border-border bg-background px-2 py-1">
			<input
				bind:value={customInput}
				type="text"
				placeholder="+ 확장자"
				class="w-20 bg-transparent font-mono text-xs outline-none placeholder:text-muted-foreground/70"
				onkeydown={handleCustomKeydown}
			/>
			<button
				type="button"
				onclick={addCustom}
				class="rounded px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:text-primary"
			>
				추가
			</button>
		</div>
	</div>

	{#if visibleSuggestionGroups.length > 0}
		<div class="space-y-2">
			{#each visibleSuggestionGroups as group (group.id)}
				{#if group.items.length > 0}
					<div class="space-y-1">
						<div class="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
							{group.label}
						</div>
						<div class="flex flex-wrap gap-1.5">
							{#each group.items as item (`${group.id}-${item.ext}`)}
								<button
									type="button"
									onclick={() => toggle(item.ext)}
									disabled={extensions.includes(item.ext)}
									class="rounded-full border px-2.5 py-1 font-mono text-[11px] transition-colors {extensions.includes(item.ext)
										? 'cursor-default border-border bg-muted text-muted-foreground/70'
										: 'border-border bg-background text-foreground hover:border-primary/40 hover:bg-primary/5'}"
								>
									.{item.ext}
									{#if item.count}
										<span class="ml-1 font-sans text-[10px] text-muted-foreground">{item.count}</span>
									{/if}
								</button>
							{/each}
						</div>
					</div>
				{/if}
			{/each}
		</div>
	{/if}
</div>
