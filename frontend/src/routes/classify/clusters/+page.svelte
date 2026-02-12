<script lang="ts">
	import { onMount } from 'svelte';

	interface Cluster {
		id: number;
		date: string;
		start_time: string;
		end_time: string;
		file_count: number;
		category_name: string | null;
		is_classified: boolean;
		files: any[];
	}

	let clusters: Cluster[] = [];
	let selectedCluster: Cluster | null = null;
	let loading = false;

	onMount(() => {
		loadClusters();
	});

	async function loadClusters() {
		loading = true;
		try {
			const response = await fetch('/api/ic/clusters');
			if (response.ok) {
				clusters = await response.json();
			}
		} catch (err) {
			console.error('Failed to load clusters:', err);
		} finally {
			loading = false;
		}
	}

	function selectCluster(cluster: Cluster) {
		selectedCluster = cluster;
	}
</script>

<div class="clusters-page">
	<h1>시간 클러스터 검토</h1>
	<p>1시간 이내 촬영된 사진을 묶어서 검토합니다.</p>

	{#if loading}
		<div class="loading">로딩 중...</div>
	{:else if clusters.length === 0}
		<div class="empty">클러스터가 없습니다.</div>
	{:else}
		<div class="cluster-list">
			{#each clusters as cluster}
				<div class="cluster-item" class:classified={cluster.is_classified} on:click={() => selectCluster(cluster)}>
					<div class="cluster-date">{cluster.date}</div>
					<div class="cluster-time">{cluster.start_time} ~ {cluster.end_time}</div>
					<div class="cluster-count">{cluster.file_count}장</div>
					{#if cluster.category_name}
						<div class="cluster-category">{cluster.category_name}</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	{#if selectedCluster}
		<div class="cluster-detail">
			<h2>클러스터 #{selectedCluster.id}</h2>
			<p>{selectedCluster.date} {selectedCluster.start_time} ~ {selectedCluster.end_time}</p>
			<p>{selectedCluster.file_count}장</p>
		</div>
	{/if}
</div>

<style>
	.clusters-page { padding: 2rem; max-width: 1200px; margin: 0 auto; }
	h1 { font-size: 1.8rem; margin-bottom: 0.5rem; }
	.loading, .empty { text-align: center; padding: 3rem; color: #666; }
	.cluster-list { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
	.cluster-item { padding: 1rem; border: 1px solid #ddd; border-radius: 8px; cursor: pointer; }
	.cluster-item:hover { background: #f5f5f5; }
	.cluster-item.classified { border-color: #28a745; background: #f0fff4; }
	.cluster-date { font-weight: 600; }
	.cluster-time { color: #666; font-size: 0.9rem; }
	.cluster-count { margin-top: 0.5rem; }
	.cluster-category { margin-top: 0.5rem; color: #007bff; font-weight: 600; }
</style>
