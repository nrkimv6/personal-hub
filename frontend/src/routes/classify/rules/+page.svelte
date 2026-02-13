<script lang="ts">
	import { onMount } from 'svelte';
  import { fetchWithTimeout } from '$lib/api/client';

	interface Rule {
		id: number;
		rule_type: string;
		category_name: string;
		rule_content: string;
		priority: number;
		is_active: boolean;
		source: string;
		hit_count: number;
	}

	let rules: Rule[] = [];
	let loading = false;

	onMount(() => {
		loadRules();
	});

	async function loadRules() {
		loading = true;
		try {
			const response = await fetchWithTimeout('/api/ic/rules');
			if (response.ok) {
				rules = await response.json();
			}
		} catch (err) {
			console.error('Failed to load rules:', err);
		} finally {
			loading = false;
		}
	}

	async function toggleRule(id: number) {
		try {
			await fetchWithTimeout(`/api/ic/rules/${id}/toggle`, { method: 'POST' });
			await loadRules();
		} catch (err) {
			alert('규칙 토글 실패');
		}
	}

	async function deleteRule(id: number) {
		if (!confirm('이 규칙을 삭제하시겠습니까?')) return;

		try {
			await fetchWithTimeout(`/api/ic/rules/${id}`, { method: 'DELETE' });
			await loadRules();
		} catch (err) {
			alert('규칙 삭제 실패');
		}
	}
</script>

<div class="rules-page">
	<div class="header">
		<h1>분류 규칙 관리</h1>
		<button on:click={loadRules}>새로고침</button>
	</div>

	<p>학습된 규칙과 사용자 정의 규칙을 관리합니다.</p>

	{#if loading}
		<div class="loading">로딩 중...</div>
	{:else if rules.length === 0}
		<div class="empty">규칙이 없습니다.</div>
	{:else}
		<table>
			<thead>
				<tr>
					<th>유형</th>
					<th>패턴</th>
					<th>카테고리</th>
					<th>우선순위</th>
					<th>출처</th>
					<th>히트</th>
					<th>활성</th>
					<th>작업</th>
				</tr>
			</thead>
			<tbody>
				{#each rules as rule}
					<tr class:inactive={!rule.is_active}>
						<td>{rule.rule_type}</td>
						<td><code>{rule.rule_content}</code></td>
						<td>{rule.category_name}</td>
						<td>{rule.priority}</td>
						<td><span class="badge badge-{rule.source}">{rule.source}</span></td>
						<td>{rule.hit_count}</td>
						<td>
							<input type="checkbox" checked={rule.is_active} on:change={() => toggleRule(rule.id)} />
						</td>
						<td>
							<button class="delete" on:click={() => deleteRule(rule.id)}>삭제</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.rules-page { padding: 2rem; max-width: 1400px; margin: 0 auto; }
	.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
	h1 { font-size: 1.8rem; }
	button { padding: 0.5rem 1rem; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
	.loading, .empty { text-align: center; padding: 3rem; color: #666; }
	table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
	th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #ddd; }
	th { background: #f5f5f5; font-weight: 600; }
	tr.inactive { opacity: 0.5; }
	code { background: #f0f0f0; padding: 0.2rem 0.4rem; border-radius: 3px; font-size: 0.85rem; }
	.badge { padding: 0.2rem 0.5rem; border-radius: 3px; font-size: 0.8rem; }
	.badge-user { background: #007bff; color: white; }
	.badge-learned { background: #28a745; color: white; }
	.badge-ai_suggested { background: #ffc107; color: black; }
	.delete { background: #dc3545; }
	.delete:hover { background: #c82333; }
</style>
