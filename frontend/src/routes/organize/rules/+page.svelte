<script lang="ts">
	import { onMount } from 'svelte';
	import PageHeader from '$lib/components/layout/PageHeader.svelte';
	import { isApiGateClosedError } from '$lib/api/client';

	let rules = $state<any[]>([]);
	let categories = $state<any[]>([]);
	let isLoading = $state(false);
	let message = $state('');

	// 새 규칙 폼
	let newRule = $state({
		rule_type: 'extension',
		category_id: null as number | null,
		rule_content: '{"value": ""}',
		priority: 0
	});

	const RULE_TYPES = [
		{ value: 'extension', label: '확장자' },
		{ value: 'filename_pattern', label: '파일명 패턴' },
		{ value: 'folder_path', label: '폴더 경로' },
		{ value: 'metadata_field', label: '메타데이터 필드' }
	];

	async function fetchRules() {
		isLoading = true;
		try {
			const res = await fetch('/api/fc/rules');
			if (res.ok) rules = await res.json();
		} catch (e) {
			message = isApiGateClosedError(e) ? 'API 서버 재시작 중' : '규칙 로드 실패';
		} finally {
			isLoading = false;
		}
	}

	async function fetchCategories() {
		try {
			const res = await fetch('/api/fc/categories');
			if (res.ok) {
				const tree = await res.json();
				const flat: any[] = [];
				function flatten(nodes: any[], depth = 0) {
					for (const node of nodes) {
						flat.push({ ...node, depth });
						if (node.children?.length) flatten(node.children, depth + 1);
					}
				}
				flatten(tree);
				categories = flat;
			}
		} catch (e) {
			message = isApiGateClosedError(e) ? 'API 서버 재시작 중' : '카테고리 로드 실패';
		}
	}

	async function createRule() {
		let content: any;
		try {
			content = JSON.parse(newRule.rule_content);
		} catch {
			message = 'rule_content가 유효한 JSON이 아닙니다';
			return;
		}
		try {
			const res = await fetch('/api/fc/rules', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					rule_type: newRule.rule_type,
					category_id: newRule.category_id,
					rule_content: content,
					priority: newRule.priority
				})
			});
			if (res.ok) {
				message = '규칙 생성됨';
				newRule = { rule_type: 'extension', category_id: null, rule_content: '{"value": ""}', priority: 0 };
				await fetchRules();
			}
		} catch (e) {
			message = isApiGateClosedError(e) ? 'API 서버 재시작 중' : '규칙 생성 실패';
		}
	}

	async function toggleRule(rule: any) {
		try {
			await fetch(`/api/fc/rules/${rule.id}/toggle`, { method: 'PUT' });
			await fetchRules();
		} catch (e) {
			message = isApiGateClosedError(e) ? 'API 서버 재시작 중' : '규칙 토글 실패';
		}
	}

	async function deleteRule(id: number) {
		if (!confirm('삭제하시겠습니까?')) return;
		try {
			await fetch(`/api/fc/rules/${id}`, { method: 'DELETE' });
			await fetchRules();
		} catch (e) {
			message = isApiGateClosedError(e) ? 'API 서버 재시작 중' : '규칙 삭제 실패';
		}
	}

	onMount(() => {
		fetchRules();
		fetchCategories();
	});
</script>

<div class="space-y-6">
	<PageHeader title="규칙 관리" />

	{#if message}
		<div class="rounded-md bg-blue-500/10 px-3 py-2 text-sm text-blue-600">{message}</div>
	{/if}

	<!-- 새 규칙 생성 폼 -->
	<div class="rounded-lg border border-border bg-card p-4 space-y-3">
		<h3 class="font-medium text-foreground">새 규칙 추가</h3>
		<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
			<select bind:value={newRule.rule_type} class="rounded-md border border-border bg-background px-2 py-1.5 text-sm">
				{#each RULE_TYPES as rt}
					<option value={rt.value}>{rt.label}</option>
				{/each}
			</select>
			<select bind:value={newRule.category_id} class="rounded-md border border-border bg-background px-2 py-1.5 text-sm">
				<option value={null}>카테고리 선택...</option>
				{#each categories as cat}
					<option value={cat.id}>{cat.full_path}</option>
				{/each}
			</select>
			<input
				bind:value={newRule.rule_content}
				placeholder='value: .mp3 (JSON 형식)'
				class="rounded-md border border-border bg-background px-2 py-1.5 text-sm font-mono"
			/>
			<input
				type="number"
				bind:value={newRule.priority}
				placeholder="우선순위"
				class="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
			/>
		</div>
		<button
			onclick={createRule}
			class="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
		>
			추가
		</button>
	</div>

	<!-- 규칙 목록 -->
	{#if isLoading}
		<div class="py-8 text-center text-sm text-muted-foreground">로딩 중...</div>
	{:else}
		<div class="overflow-x-auto rounded-lg border border-border">
			<table class="w-full text-sm">
				<thead class="bg-muted/50">
					<tr>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">타입</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">내용</th>
						<th class="px-3 py-2 text-left font-medium text-muted-foreground">카테고리</th>
						<th class="px-3 py-2 text-right font-medium text-muted-foreground">우선순위</th>
						<th class="px-3 py-2 text-right font-medium text-muted-foreground">적중수</th>
						<th class="px-3 py-2 text-center font-medium text-muted-foreground">활성</th>
						<th class="px-3 py-2"></th>
					</tr>
				</thead>
				<tbody>
					{#each rules as rule}
						<tr class="border-t border-border hover:bg-muted/30">
							<td class="px-3 py-2 text-muted-foreground">{rule.rule_type}</td>
							<td class="max-w-[200px] truncate px-3 py-2 font-mono text-xs text-foreground">
								{JSON.stringify(rule.rule_content)}
							</td>
							<td class="px-3 py-2 text-muted-foreground">{rule.category_path ?? rule.category_id}</td>
							<td class="px-3 py-2 text-right text-muted-foreground">{rule.priority}</td>
							<td class="px-3 py-2 text-right text-muted-foreground">{rule.hit_count}</td>
							<td class="px-3 py-2 text-center">
								<button
									onclick={() => toggleRule(rule)}
									class="rounded-full px-2 py-0.5 text-xs font-medium {rule.is_active ? 'bg-green-500/15 text-green-600' : 'bg-muted text-muted-foreground'}"
								>
									{rule.is_active ? '활성' : '비활성'}
								</button>
							</td>
							<td class="px-3 py-2">
								<button
									onclick={() => deleteRule(rule.id)}
									class="text-xs text-red-500 hover:text-red-600"
								>삭제</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
