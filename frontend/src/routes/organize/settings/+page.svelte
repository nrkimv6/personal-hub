<script lang="ts">
	import { onMount } from 'svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import { isApiGateClosedError } from '$lib/api/client';

	let settings = $state<any>(null);
	let message = $state('');
	let newScanFolder = $state('');
	let newExcludeFolder = $state('');

	async function fetchSettings() {
		try {
			const res = await fetch('/api/fc/settings');
			if (res.ok) settings = await res.json();
		} catch (e) {
			message = isApiGateClosedError(e) ? 'API 서버 재시작 중' : '설정 로드 실패';
		}
	}

	async function saveSettings() {
		try {
			const res = await fetch('/api/fc/settings', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(settings)
			});
			if (res.ok) {
				message = '설정 저장됨';
			}
		} catch (e) {
			message = isApiGateClosedError(e) ? 'API 서버 재시작 중' : '설정 저장 실패';
		}
	}

	function addScanFolder() {
		if (!newScanFolder.trim()) return;
		settings.SCAN_ROOT_FOLDERS = [...(settings.SCAN_ROOT_FOLDERS || []), newScanFolder.trim()];
		newScanFolder = '';
	}

	function removeScanFolder(idx: number) {
		settings.SCAN_ROOT_FOLDERS = settings.SCAN_ROOT_FOLDERS.filter((_: any, i: number) => i !== idx);
	}

	function addExcludeFolder() {
		if (!newExcludeFolder.trim()) return;
		settings.EXCLUDE_FOLDERS = [...(settings.EXCLUDE_FOLDERS || []), newExcludeFolder.trim()];
		newExcludeFolder = '';
	}

	function removeExcludeFolder(idx: number) {
		settings.EXCLUDE_FOLDERS = settings.EXCLUDE_FOLDERS.filter((_: any, i: number) => i !== idx);
	}

	onMount(() => fetchSettings());
</script>

<div class="space-y-6">
	<PageHeader title="설정" />

	{#if message}
		<div class="rounded-md bg-green-500/10 px-3 py-2 text-sm text-green-600">{message}</div>
	{/if}

	{#if settings}
		<!-- 스캔 루트 폴더 -->
		<div class="rounded-lg border border-border bg-card p-4 space-y-3">
			<h3 class="font-medium text-foreground">스캔 대상 폴더</h3>
			<div class="space-y-1">
				{#each settings.SCAN_ROOT_FOLDERS || [] as folder, i}
					<div class="flex items-center gap-2">
						<span class="flex-1 rounded bg-muted px-2 py-1 text-sm font-mono">{folder}</span>
						<button onclick={() => removeScanFolder(i)} class="text-red-500 hover:text-red-600 text-xs">제거</button>
					</div>
				{/each}
			</div>
			<div class="flex gap-2">
				<input
					bind:value={newScanFolder}
					placeholder="C:/Users/..."
					class="flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm font-mono"
				/>
				<button
					onclick={addScanFolder}
					class="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90"
				>추가</button>
			</div>
		</div>

		<!-- 제외 폴더 -->
		<div class="rounded-lg border border-border bg-card p-4 space-y-3">
			<h3 class="font-medium text-foreground">제외 폴더</h3>
			<div class="flex flex-wrap gap-1">
				{#each settings.EXCLUDE_FOLDERS || [] as folder, i}
					<span class="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs">
						{folder}
						<button onclick={() => removeExcludeFolder(i)} class="text-red-500">x</button>
					</span>
				{/each}
			</div>
			<div class="flex gap-2">
				<input
					bind:value={newExcludeFolder}
					placeholder="node_modules"
					class="flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
				/>
				<button
					onclick={addExcludeFolder}
					class="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
				>추가</button>
			</div>
		</div>

		<!-- 대상 폴더 -->
		<div class="rounded-lg border border-border bg-card p-4 space-y-3">
			<h3 class="font-medium text-foreground">정리 대상 폴더</h3>
			<input
				bind:value={settings.TARGET_ROOT_FOLDER}
				placeholder="D:/Organized/..."
				class="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm font-mono"
			/>
		</div>

		<!-- 기타 설정 -->
		<div class="rounded-lg border border-border bg-card p-4 space-y-3">
			<h3 class="font-medium text-foreground">기타 설정</h3>
			<div class="space-y-2">
				<label class="flex items-center gap-2 text-sm">
					<input type="checkbox" bind:checked={settings.DRY_RUN_DEFAULT} class="rounded" />
					기본값: 실제 이동 없이 미리보기만 (dry-run)
				</label>
				<label class="flex items-center gap-2 text-sm">
					<input type="checkbox" bind:checked={settings.USE_TRASH} class="rounded" />
					삭제 시 휴지통 사용
				</label>
			</div>
			<div class="flex items-center gap-2">
				<span class="text-sm text-muted-foreground">LLM 모드:</span>
				<select bind:value={settings.LLM_MODE} class="rounded-md border border-border bg-background px-2 py-1 text-sm">
					<option value="cli">CLI (claude 명령어)</option>
					<option value="api">API (Anthropic API)</option>
				</select>
			</div>
		</div>

		<button
			onclick={saveSettings}
			class="rounded-md bg-primary px-6 py-2 font-medium text-primary-foreground hover:bg-primary/90"
		>
			저장
		</button>
	{/if}
</div>
