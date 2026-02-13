<script lang="ts">
	import { onMount } from 'svelte';

	interface SimilarFile {
		file_id: number;
		file_path: string;
		similarity: number;
		current_category: string | null;
		suggested_category: string;
	}

	interface SimilarGroup {
		category: string;
		category_name: string;
		file_count: number;
		similar_count: number;
		similar_files: SimilarFile[];
	}

	let groups: SimilarGroup[] = [];
	let selectedFiles: Set<number> = new Set();
	let threshold = 0.85;
	let loading = false;
	let error = '';

	onMount(() => {
		loadSimilarSuggestions();
	});

	async function loadSimilarSuggestions() {
		loading = true;
		error = '';

		try {
			const response = await fetch(`/api/ic/similar/bulk-suggest?threshold=${threshold}`);

			if (!response.ok) {
				throw new Error('Failed to load similar suggestions');
			}

			const data = await response.json();
			groups = data.groups || [];
		} catch (err: any) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	function toggleFile(fileId: number) {
		if (selectedFiles.has(fileId)) {
			selectedFiles.delete(fileId);
		} else {
			selectedFiles.add(fileId);
		}
		selectedFiles = selectedFiles;
	}

	function toggleGroup(group: SimilarGroup) {
		const allSelected = group.similar_files.every((f) => selectedFiles.has(f.file_id));

		if (allSelected) {
			group.similar_files.forEach((f) => selectedFiles.delete(f.file_id));
		} else {
			group.similar_files.forEach((f) => selectedFiles.add(f.file_id));
		}
		selectedFiles = selectedFiles;
	}

	async function applyClassification(category: string) {
		const fileIds = Array.from(selectedFiles);

		if (fileIds.length === 0) {
			alert('파일을 선택해주세요.');
			return;
		}

		if (!confirm(`선택한 ${fileIds.length}개 파일을 "${category}"로 분류하시겠습니까?`)) {
			return;
		}

		loading = true;
		error = '';

		try {
			const response = await fetch('/api/ic/similar/apply', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ file_ids: fileIds, category_id: category })
			});

			if (!response.ok) {
				throw new Error('Failed to apply classification');
			}

			alert(`${fileIds.length}개 파일이 분류되었습니다.`);
			selectedFiles.clear();
			selectedFiles = selectedFiles;
			await loadSimilarSuggestions();
		} catch (err: any) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	function getThumbnailUrl(fileId: number): string {
		return `/api/ic/files/${fileId}/thumbnail`;
	}
</script>

<div class="similar-classify-page">
	<div class="header">
		<h1>유사 이미지 자동 분류 (CLIP 기반)</h1>
		<p>이미 분류된 이미지와 유사한 미분류 이미지를 찾아 자동으로 분류 제안합니다.</p>
	</div>

	<div class="controls">
		<div class="threshold-control">
			<label for="threshold">유사도 기준:</label>
			<input
				type="range"
				id="threshold"
				min="0.7"
				max="1.0"
				step="0.05"
				bind:value={threshold}
				on:change={() => loadSimilarSuggestions()}
			/>
			<span>{(threshold * 100).toFixed(0)}%</span>
		</div>

		<button on:click={() => loadSimilarSuggestions()} disabled={loading}>
			{loading ? '로딩 중...' : '새로고침'}
		</button>
	</div>

	{#if error}
		<div class="error">{error}</div>
	{/if}

	{#if loading}
		<div class="loading">로딩 중...</div>
	{:else if groups.length === 0}
		<div class="empty">유사 이미지 제안이 없습니다.</div>
	{:else}
		<div class="groups">
			{#each groups as group}
				<div class="group">
					<div class="group-header">
						<h3>
							{group.category_name}
							<span class="count">{group.file_count}장 분류됨</span>
						</h3>
						<p>→ 미분류 중 유사 이미지: {group.similar_count}장</p>
						<button on:click={() => toggleGroup(group)}>
							{group.similar_files.every((f) => selectedFiles.has(f.file_id))
								? '전체 해제'
								: '전체 선택'}
						</button>
						<button
							on:click={() => applyClassification(group.category)}
							disabled={!group.similar_files.some((f) => selectedFiles.has(f.file_id))}
						>
							선택 항목 → {group.category_name}로 분류
						</button>
					</div>

					<div class="similar-files">
						{#each group.similar_files as file}
							<div class="file-card" class:selected={selectedFiles.has(file.file_id)}>
								<input
									type="checkbox"
									checked={selectedFiles.has(file.file_id)}
									on:change={() => toggleFile(file.file_id)}
								/>
								<img src={getThumbnailUrl(file.file_id)} alt={file.file_path} loading="lazy" decoding="async" />
								<div class="file-info">
									<div class="similarity">{(file.similarity * 100).toFixed(0)}% 유사</div>
									<div class="file-path">{file.file_path.split('/').pop()}</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{/if}

	{#if selectedFiles.size > 0}
		<div class="footer">
			<p>선택: {selectedFiles.size}개</p>
			<button on:click={() => selectedFiles.clear()}>선택 해제</button>
		</div>
	{/if}
</div>

<style>
	.similar-classify-page {
		padding: 2rem;
		max-width: 1400px;
		margin: 0 auto;
	}

	.header {
		margin-bottom: 2rem;
	}

	.header h1 {
		font-size: 1.8rem;
		margin-bottom: 0.5rem;
	}

	.header p {
		color: #666;
	}

	.controls {
		display: flex;
		gap: 1rem;
		align-items: center;
		margin-bottom: 2rem;
		padding: 1rem;
		background: #f5f5f5;
		border-radius: 8px;
	}

	.threshold-control {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		flex: 1;
	}

	.threshold-control label {
		font-weight: 600;
	}

	.threshold-control input[type='range'] {
		flex: 1;
		max-width: 300px;
	}

	.threshold-control span {
		font-weight: 600;
		min-width: 45px;
	}

	button {
		padding: 0.5rem 1rem;
		background: #007bff;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.9rem;
	}

	button:hover:not(:disabled) {
		background: #0056b3;
	}

	button:disabled {
		background: #ccc;
		cursor: not-allowed;
	}

	.error {
		padding: 1rem;
		background: #fee;
		color: #c00;
		border-radius: 4px;
		margin-bottom: 1rem;
	}

	.loading,
	.empty {
		text-align: center;
		padding: 3rem;
		color: #666;
		font-size: 1.1rem;
	}

	.groups {
		display: flex;
		flex-direction: column;
		gap: 2rem;
	}

	.group {
		border: 1px solid #ddd;
		border-radius: 8px;
		padding: 1.5rem;
		background: white;
	}

	.group-header {
		margin-bottom: 1rem;
		border-bottom: 1px solid #eee;
		padding-bottom: 1rem;
	}

	.group-header h3 {
		font-size: 1.3rem;
		margin-bottom: 0.5rem;
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.group-header .count {
		font-size: 0.9rem;
		color: #666;
		font-weight: normal;
	}

	.group-header p {
		color: #666;
		margin-bottom: 0.5rem;
	}

	.group-header button {
		margin-right: 0.5rem;
	}

	.similar-files {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: 1rem;
	}

	.file-card {
		border: 2px solid transparent;
		border-radius: 8px;
		overflow: hidden;
		cursor: pointer;
		transition: all 0.2s;
		background: #f9f9f9;
	}

	.file-card:hover {
		border-color: #007bff;
		transform: translateY(-2px);
		box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
	}

	.file-card.selected {
		border-color: #007bff;
		background: #e7f3ff;
	}

	.file-card input[type='checkbox'] {
		position: absolute;
		margin: 0.5rem;
		width: 20px;
		height: 20px;
		cursor: pointer;
	}

	.file-card img {
		width: 100%;
		height: 150px;
		object-fit: cover;
		display: block;
	}

	.file-info {
		padding: 0.5rem;
	}

	.similarity {
		font-weight: 600;
		color: #007bff;
		margin-bottom: 0.25rem;
	}

	.file-path {
		font-size: 0.8rem;
		color: #666;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.footer {
		position: fixed;
		bottom: 0;
		left: 0;
		right: 0;
		background: white;
		border-top: 1px solid #ddd;
		padding: 1rem 2rem;
		display: flex;
		justify-content: space-between;
		align-items: center;
		box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.1);
	}

	.footer p {
		margin: 0;
		font-weight: 600;
	}
</style>
