<script lang="ts">
	import { onMount } from 'svelte';

	interface MoveHistory {
		id: number;
		file_path: string;
		moved_path: string;
		category: string;
		moved_at: string;
	}

	let history: MoveHistory[] = [];
	let loading = false;

	onMount(() => {
		loadHistory();
	});

	async function loadHistory() {
		loading = true;
		try {
			const response = await fetch('/api/ic/files?status=moved&limit=100');
			if (response.ok) {
				history = await response.json();
			}
		} catch (err) {
			console.error('Failed to load history:', err);
		} finally {
			loading = false;
		}
	}

	async function rollback(id: number) {
		if (!confirm('이 파일을 원래 위치로 복원하시겠습니까?')) return;

		try {
			await fetch(`/api/ic/files/${id}/rollback`, { method: 'POST' });
			alert('복원되었습니다.');
			await loadHistory();
		} catch (err) {
			alert('복원 실패');
		}
	}
</script>

<div class="history-page">
	<h1>파일 이동 이력</h1>
	<p>최근 이동된 파일들을 확인하고 필요시 복원할 수 있습니다.</p>

	{#if loading}
		<div class="loading">로딩 중...</div>
	{:else if history.length === 0}
		<div class="empty">이동 이력이 없습니다.</div>
	{:else}
		<table>
			<thead>
				<tr>
					<th>원래 경로</th>
					<th>이동된 경로</th>
					<th>카테고리</th>
					<th>이동 일시</th>
					<th>작업</th>
				</tr>
			</thead>
			<tbody>
				{#each history as item}
					<tr>
						<td><code>{item.file_path}</code></td>
						<td><code>{item.moved_path}</code></td>
						<td>{item.category}</td>
						<td>{new Date(item.moved_at).toLocaleString()}</td>
						<td><button on:click={() => rollback(item.id)}>복원</button></td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.history-page { padding: 2rem; max-width: 1400px; margin: 0 auto; }
	h1 { font-size: 1.8rem; margin-bottom: 0.5rem; }
	.loading, .empty { text-align: center; padding: 3rem; color: #666; }
	table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
	th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #ddd; }
	th { background: #f5f5f5; font-weight: 600; }
	code { background: #f0f0f0; padding: 0.2rem 0.4rem; border-radius: 3px; font-size: 0.85rem; }
	button { padding: 0.4rem 0.8rem; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer; }
	button:hover { background: #c82333; }
</style>
