<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getIgnorePatterns,
		addIgnorePattern,
		toggleIgnorePattern,
		deleteIgnorePattern
	} from '$lib/api/fileSearch';
	import type { IgnorePattern } from '$lib/types/fileSearch';

	interface Props {
		onchange: (activePatterns: string[]) => void;
	}

	let { onchange }: Props = $props();

	let patterns = $state<IgnorePattern[]>([]);
	let expanded = $state(false);
	let newLabel = $state('');
	let newPattern = $state('');
	let loading = $state(false);

	function activeCount() {
		return patterns.filter((p) => p.enabled).length;
	}

	function notifyChange() {
		onchange(patterns.filter((p) => p.enabled).map((p) => p.pattern));
	}

	async function loadPatterns() {
		try {
			patterns = await getIgnorePatterns();
			notifyChange();
		} catch (e) {
			console.error('[IgnorePatterns] 로드 실패:', e);
		}
	}

	async function handleToggle(id: number, enabled: boolean) {
		// 낙관적 업데이트
		patterns = patterns.map((p) => (p.id === id ? { ...p, enabled } : p));
		notifyChange();
		try {
			await toggleIgnorePattern(id, enabled);
		} catch (e) {
			// 롤백
			patterns = patterns.map((p) => (p.id === id ? { ...p, enabled: !enabled } : p));
			notifyChange();
		}
	}

	async function handleAdd() {
		const label = newLabel.trim();
		const pattern = newPattern.trim();
		if (!label || !pattern) return;

		loading = true;
		try {
			const added = await addIgnorePattern(label, pattern);
			patterns = [...patterns, added];
			newLabel = '';
			newPattern = '';
			notifyChange();
		} catch (e) {
			console.error('[IgnorePatterns] 추가 실패:', e);
		} finally {
			loading = false;
		}
	}

	async function handleDelete(id: number) {
		const prev = patterns;
		patterns = patterns.filter((p) => p.id !== id);
		notifyChange();
		try {
			await deleteIgnorePattern(id);
		} catch (e) {
			patterns = prev;
			notifyChange();
		}
	}

	function handleAddKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			handleAdd();
		}
	}

	onMount(loadPatterns);
</script>

<div class="rounded border border-border bg-background">
	<!-- 헤더 (접기/펼치기) -->
	<button
		onclick={() => (expanded = !expanded)}
		class="flex w-full items-center justify-between px-3 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
	>
		<span>
			{expanded ? '▼' : '▶'}
			무시 폴더 패턴
			<span class="ml-1 text-xs text-primary">({activeCount()}개 활성)</span>
		</span>
		<span class="text-xs opacity-50">검색 시 자동 제외</span>
	</button>

	{#if expanded}
		<div class="border-t border-border px-3 py-2 space-y-1">
			{#if patterns.length === 0}
				<p class="text-xs text-muted-foreground">패턴 없음</p>
			{:else}
				{#each patterns as p (p.id)}
					<div class="flex items-center gap-2">
						<input
							type="checkbox"
							id={`ignore-${p.id}`}
							checked={p.enabled}
							onchange={(e) => handleToggle(p.id, (e.target as HTMLInputElement).checked)}
							class="h-3.5 w-3.5 rounded accent-primary"
						/>
						<label for={`ignore-${p.id}`} class="flex-1 cursor-pointer text-xs">
							<span class="text-foreground">{p.label}</span>
							<span class="ml-1.5 font-mono text-muted-foreground">{p.pattern}</span>
						</label>
						<button
							onclick={() => handleDelete(p.id)}
							class="rounded px-1 text-xs text-muted-foreground hover:text-destructive transition-colors"
							title="삭제"
						>
							×
						</button>
					</div>
				{/each}
			{/if}

			<!-- 패턴 추가 폼 -->
			<div class="mt-2 flex items-center gap-1 border-t border-border pt-2">
				<input
					bind:value={newLabel}
					type="text"
					placeholder="라벨"
					class="w-24 rounded border border-border bg-background px-2 py-0.5 text-xs outline-none focus:border-primary focus:ring-1 focus:ring-primary/20"
					onkeydown={handleAddKeydown}
				/>
				<input
					bind:value={newPattern}
					type="text"
					placeholder="패턴 (예: dist)"
					class="flex-1 rounded border border-border bg-background px-2 py-0.5 font-mono text-xs outline-none focus:border-primary focus:ring-1 focus:ring-primary/20"
					onkeydown={handleAddKeydown}
				/>
				<button
					onclick={handleAdd}
					disabled={loading || !newLabel.trim() || !newPattern.trim()}
					class="rounded px-2 py-0.5 text-xs text-muted-foreground hover:text-primary transition-colors disabled:opacity-40"
				>
					추가
				</button>
			</div>
		</div>
	{/if}
</div>
