<script lang="ts">
	import { Plus, Trash2 } from 'lucide-svelte';
	import { listBoardApi, type ListBoardColumn, type ColumnCreate, type ColumnType } from '$lib/api';

	interface Props {
		columns: ListBoardColumn[];
		onchange: () => void;
	}

	let { columns, onchange }: Props = $props();

	let showForm = $state(false);
	let newKey = $state('');
	let newName = $state('');
	let newType: ColumnType = $state('text');
	let newOptions = $state('');
	let saving = $state(false);
	let error = $state('');

	async function handleCreate() {
		if (!newKey.trim() || !newName.trim()) return;
		saving = true;
		error = '';
		try {
			const req: ColumnCreate = {
				key: newKey.trim(),
				display_name: newName.trim(),
				column_type: newType,
				options: newType === 'select' ? newOptions.split(',').map((s) => s.trim()).filter(Boolean) : [],
			};
			await listBoardApi.createColumn(req);
			newKey = '';
			newName = '';
			newType = 'text';
			newOptions = '';
			showForm = false;
			onchange();
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : '컬럼 추가 실패';
		} finally {
			saving = false;
		}
	}

	async function handleDelete(col: ListBoardColumn) {
		if (!confirm(`컬럼 "${col.display_name}"을 삭제할까요?`)) return;
		try {
			await listBoardApi.deleteColumn(col.id);
			onchange();
		} catch (e: unknown) {
			alert(e instanceof Error ? e.message : '삭제 실패');
		}
	}
</script>

<div class="flex flex-col gap-2">
	<div class="flex items-center justify-between">
		<span class="text-xs font-medium text-zinc-400">사용자 컬럼 관리</span>
		<button
			class="flex items-center gap-1 rounded bg-zinc-700 px-2 py-0.5 text-xs hover:bg-zinc-600"
			onclick={() => (showForm = !showForm)}
		>
			<Plus size={12} /> 컬럼 추가
		</button>
	</div>

	{#if showForm}
		<div class="flex flex-col gap-1.5 rounded border border-zinc-700 p-2">
			<div class="flex gap-2">
				<input
					class="flex-1 rounded border border-zinc-600 bg-zinc-800 px-2 py-0.5 text-xs placeholder-zinc-500"
					placeholder="key (영문 소문자_숫자)"
					bind:value={newKey}
				/>
				<input
					class="flex-1 rounded border border-zinc-600 bg-zinc-800 px-2 py-0.5 text-xs placeholder-zinc-500"
					placeholder="표시 이름"
					bind:value={newName}
				/>
				<select
					class="rounded border border-zinc-600 bg-zinc-800 px-2 py-0.5 text-xs"
					bind:value={newType}
				>
					<option value="text">text</option>
					<option value="checkbox">checkbox</option>
					<option value="select">select</option>
					<option value="priority">priority</option>
				</select>
			</div>
			{#if newType === 'select'}
				<input
					class="rounded border border-zinc-600 bg-zinc-800 px-2 py-0.5 text-xs placeholder-zinc-500"
					placeholder="선택지 (쉼표 구분, 예: 진행중, 완료, 보류)"
					bind:value={newOptions}
				/>
			{/if}
			{#if error}
				<span class="text-xs text-red-400">{error}</span>
			{/if}
			<div class="flex gap-2">
				<button
					class="rounded bg-blue-600 px-3 py-0.5 text-xs disabled:opacity-50"
					disabled={saving || !newKey.trim() || !newName.trim()}
					onclick={handleCreate}
				>{saving ? '추가 중...' : '추가'}</button>
				<button
					class="rounded bg-zinc-700 px-3 py-0.5 text-xs"
					onclick={() => (showForm = false)}
				>취소</button>
			</div>
		</div>
	{/if}

	{#if columns.length > 0}
		<div class="flex flex-wrap gap-1">
			{#each columns as col (col.id)}
				<span class="flex items-center gap-1 rounded border border-zinc-700 px-2 py-0.5 text-xs text-zinc-300">
					{col.display_name}
					<span class="text-zinc-500">{col.column_type}</span>
					<button
						class="text-zinc-600 hover:text-red-400"
						onclick={() => handleDelete(col)}
						title="삭제"
					>
						<Trash2 size={10} />
					</button>
				</span>
			{/each}
		</div>
	{/if}
</div>
