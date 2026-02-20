<script lang="ts">
	interface Props {
		extensions: string[];
		onchange: (exts: string[]) => void;
	}

	let { extensions = $bindable([]), onchange }: Props = $props();

	let customInput = $state('');

	function toggle(ext: string) {
		const next = extensions.includes(ext)
			? extensions.filter((e) => e !== ext)
			: [...extensions, ext];
		onchange(next);
	}

	function addCustom() {
		const ext = customInput.trim().replace(/^\./, '');
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

<div class="flex flex-wrap items-center gap-2">
	{#if extensions.length === 0}
		<span class="text-xs text-muted-foreground">확장자 제한 없음 (전체)</span>
	{:else}
		{#each extensions as ext}
			<button
				onclick={() => toggle(ext)}
				class="flex items-center gap-1 rounded border border-primary/30 bg-primary/10
					   px-2 py-0.5 font-mono text-xs text-primary
					   transition-colors hover:bg-destructive/10 hover:text-destructive hover:border-destructive/30"
			>
				.{ext}
				<span class="text-xs opacity-60">×</span>
			</button>
		{/each}
	{/if}

	<!-- 커스텀 확장자 추가 -->
	<div class="flex items-center gap-1">
		<input
			bind:value={customInput}
			type="text"
			placeholder="+ 확장자"
			class="w-20 rounded border border-border bg-background px-2 py-0.5
				   font-mono text-xs outline-none
				   focus:border-primary focus:ring-1 focus:ring-primary/20"
			onkeydown={handleCustomKeydown}
		/>
		<button
			onclick={addCustom}
			class="rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:text-primary transition-colors"
		>
			추가
		</button>
	</div>
</div>
