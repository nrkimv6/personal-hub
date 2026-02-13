<script lang="ts">
	import { onMount } from 'svelte';
  import { fetchWithTimeout } from '$lib/api/client';

	interface FileReview {
		id: number;
		file_path: string;
		ai_category: string;
		ai_confidence: number;
		ai_reasoning: string;
		similar_files: any[];
	}

	let files: FileReview[] = [];
	let selectedFiles: Set<number> = new Set();
	let loading = false;
	let sortBy = 'confidence_asc';

	onMount(() => {
		loadFiles();
	});

	async function loadFiles() {
		loading = true;
		try {
			const response = await fetchWithTimeout(`/api/ic/files?status=ai_classified&sort=${sortBy}`);
			if (response.ok) {
				files = await response.json();
			}
		} catch (err) {
			console.error('Failed to load files:', err);
		} finally {
			loading = false;
		}
	}

	function toggleFile(id: number) {
		if (selectedFiles.has(id)) {
			selectedFiles.delete(id);
		} else {
			selectedFiles.add(id);
		}
		selectedFiles = selectedFiles;
	}

	async function approveSelected() {
		const ids = Array.from(selectedFiles);
		if (ids.length === 0) return;

		try {
			await fetchWithTimeout('/api/ic/files/approve', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: ids })
			});
			alert(`${ids.length}개 파일이 승인되었습니다.`);
			selectedFiles.clear();
			await loadFiles();
		} catch (err) {
			alert('승인 실패');
		}
	}

	function getThumbnailUrl(fileId: number): string {
		return `/api/ic/files/${fileId}/thumbnail`;
	}
</script>

<div class="review-page">
	<div class="header">
		<h1>이미지 검토 및 승인</h1>
		<div class="controls">
			<select bind:value={sortBy} on:change={loadFiles}>
				<option value="confidence_asc">신뢰도 낮은 순</option>
				<option value="confidence_desc">신뢰도 높은 순</option>
				<option value="date_desc">최신 순</option>
			</select>
			<button on:click={approveSelected} disabled={selectedFiles.size === 0}>
				선택 항목 승인 ({selectedFiles.size})
			</button>
		</div>
	</div>

	{#if loading}
		<div class="loading">로딩 중...</div>
	{:else if files.length === 0}
		<div class="empty">검토할 파일이 없습니다.</div>
	{:else}
		<div class="file-grid">
			{#each files as file}
				<div class="file-card" class:selected={selectedFiles.has(file.id)}>
					<input type="checkbox" checked={selectedFiles.has(file.id)} on:change={() => toggleFile(file.id)} />
					<img src={getThumbnailUrl(file.id)} alt={file.file_path} loading="lazy" decoding="async" />
					<div class="file-info">
						<div class="category">{file.ai_category}</div>
						<div class="confidence">{(file.ai_confidence * 100).toFixed(0)}% 신뢰도</div>
						{#if file.ai_reasoning}
							<div class="reasoning">{file.ai_reasoning}</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.review-page { padding: 2rem; max-width: 1400px; margin: 0 auto; }
	.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; }
	.controls { display: flex; gap: 1rem; }
	select, button { padding: 0.5rem 1rem; border-radius: 4px; }
	button { background: #007bff; color: white; border: none; cursor: pointer; }
	button:disabled { background: #ccc; }
	.loading, .empty { text-align: center; padding: 3rem; color: #666; }
	.file-grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
	.file-card { border: 2px solid transparent; border-radius: 8px; overflow: hidden; position: relative; }
	.file-card.selected { border-color: #007bff; background: #e7f3ff; }
	.file-card input[type='checkbox'] { position: absolute; top: 0.5rem; left: 0.5rem; width: 20px; height: 20px; }
	.file-card img { width: 100%; height: 180px; object-fit: cover; }
	.file-info { padding: 0.75rem; }
	.category { font-weight: 600; margin-bottom: 0.25rem; }
	.confidence { font-size: 0.9rem; color: #666; }
	.reasoning { font-size: 0.8rem; color: #999; margin-top: 0.5rem; }
</style>
