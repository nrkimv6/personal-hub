<svelte:head><title>분류 규칙 — 이미지 분류기</title></svelte:head>

<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchWithTimeout } from '$lib/api/client';
	import { ListChecks, Plus, GripVertical, Pencil, Trash2, Save, X, ArrowRight } from 'lucide-svelte';

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

	let rules: Rule[] = $state([]);
	let loading = $state(false);
	let editingId = $state<number | null>(null);
	let editForm = $state<Partial<Rule>>({});
	let showAddForm = $state(false);
	let newRule = $state({ rule_type: 'keyword', rule_content: '', category_name: '', priority: 0 });

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

	async function saveRule(id: number) {
		try {
			await fetchWithTimeout(`/api/ic/rules/${id}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					rule_type: editForm.rule_type,
					rule_content: editForm.rule_content,
					category_name: editForm.category_name
				})
			});
			editingId = null;
			await loadRules();
		} catch (err) {
			alert('규칙 저장 실패');
		}
	}

	async function addRule() {
		if (!newRule.rule_content || !newRule.category_name) {
			alert('패턴과 카테고리를 입력하세요.');
			return;
		}
		try {
			await fetchWithTimeout('/api/ic/rules', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(newRule)
			});
			showAddForm = false;
			newRule = { rule_type: 'keyword', rule_content: '', category_name: '', priority: 0 };
			await loadRules();
		} catch (err) {
			alert('규칙 추가 실패');
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

	function getRuleTypeBadgeClass(type: string): string {
		if (type === 'keyword') return 'bg-primary/10 text-primary';
		if (type === 'pattern') return 'bg-amber-500/10 text-amber-700 dark:text-amber-400';
		if (type === 'regex') return 'bg-blue-500/10 text-blue-600 dark:text-blue-400';
		return 'bg-secondary text-muted-foreground';
	}

	const ruleTypeOptions = ['keyword', 'pattern', 'regex'];
</script>

<div class="space-y-6">
	<!-- 헤더 -->
	<div class="flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2">
				<ListChecks class="size-5 text-primary" />
				<h1 class="text-2xl font-bold tracking-tight">분류 규칙</h1>
			</div>
			<p class="mt-1 text-sm text-muted-foreground">
				학습된 규칙과 사용자 정의 규칙을 관리합니다.
			</p>
		</div>
		<button
			onclick={() => (showAddForm = !showAddForm)}
			class="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
		>
			<Plus class="size-4" />
			규칙 추가
		</button>
	</div>

	<!-- 규칙 추가 폼 -->
	{#if showAddForm}
		<div class="rounded-xl border bg-card p-4">
			<h3 class="text-sm font-semibold mb-3">새 규칙 추가</h3>
			<div class="flex items-center gap-2">
				<div class="flex overflow-hidden rounded-md border">
					{#each ruleTypeOptions as opt}
						<button
							class="px-2.5 py-1 text-xs font-medium transition-colors {newRule.rule_type === opt ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted'}"
							onclick={() => (newRule.rule_type = opt)}
						>{opt}</button>
					{/each}
				</div>
				<input
					type="text"
					bind:value={newRule.rule_content}
					placeholder="패턴..."
					class="min-w-0 flex-1 rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
				/>
				<ArrowRight class="size-3.5 shrink-0 text-muted-foreground" />
				<input
					type="text"
					bind:value={newRule.category_name}
					placeholder="카테고리..."
					class="w-40 rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
				/>
				<button
					onclick={addRule}
					class="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
				>
					<Plus class="size-3" />
					추가
				</button>
				<button
					onclick={() => (showAddForm = false)}
					class="flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
				>
					<X class="size-3" />
				</button>
			</div>
		</div>
	{/if}

	<!-- 규칙 리스트 카드 -->
	<div class="rounded-xl border bg-card">
		{#if loading}
			<div class="flex items-center justify-center py-16 text-sm text-muted-foreground">
				<div class="flex items-center gap-2">
					<div class="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
					로딩 중...
				</div>
			</div>
		{:else if rules.length === 0}
			<div class="py-16 text-center text-sm text-muted-foreground">
				규칙이 없습니다. 첫 번째 분류 규칙을 추가하세요.
			</div>
		{:else}
			<div class="divide-y divide-border">
				{#each rules as rule}
					{#if editingId === rule.id}
						<!-- Edit 모드 -->
						<div class="flex items-center gap-2 bg-muted/50 px-4 py-3">
							<!-- 타입 세그먼트 -->
							<div class="flex overflow-hidden rounded-md border">
								{#each ruleTypeOptions as opt}
									<button
										class="px-2.5 py-1 text-xs font-medium transition-colors {editForm.rule_type === opt ? 'bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted'}"
										onclick={() => (editForm.rule_type = opt)}
									>{opt}</button>
								{/each}
							</div>

							<!-- 패턴 입력 -->
							<input
								type="text"
								bind:value={editForm.rule_content}
								placeholder="패턴..."
								class="min-w-0 flex-1 rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
							/>

							<ArrowRight class="size-3.5 shrink-0 text-muted-foreground" />

							<!-- 카테고리 입력 -->
							<input
								type="text"
								bind:value={editForm.category_name}
								placeholder="카테고리..."
								class="w-40 rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
							/>

							<!-- Save -->
							<button
								onclick={() => saveRule(rule.id)}
								class="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
							>
								<Save class="size-3" />
								저장
							</button>

							<!-- Cancel -->
							<button
								onclick={() => (editingId = null)}
								class="flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
							>
								<X class="size-3" />
							</button>
						</div>
					{:else}
						<!-- View 모드 -->
						<div
							class="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-muted/30 {!rule.is_active ? 'opacity-50' : ''}"
						>
							<GripVertical class="size-4 shrink-0 cursor-grab text-muted-foreground" />

							<span class="w-5 shrink-0 text-xs text-muted-foreground">
								#{rule.priority}
							</span>

							<!-- 타입 뱃지 -->
							<span class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium {getRuleTypeBadgeClass(rule.rule_type)}">
								{rule.rule_type}
							</span>

							<!-- 패턴 -->
							<code class="rounded bg-muted px-2 py-0.5 font-mono text-xs">
								{rule.rule_content}
							</code>

							<ArrowRight class="size-3 shrink-0 text-muted-foreground" />

							<!-- 카테고리 -->
							<span class="text-sm">{rule.category_name}</span>

							<!-- 히트 수 -->
							<span class="ml-auto shrink-0 text-xs text-muted-foreground">
								적중 {rule.hit_count}회
							</span>

							<!-- 활성 토글 -->
							<input
								type="checkbox"
								checked={rule.is_active}
								onchange={() => toggleRule(rule.id)}
								class="size-4 shrink-0 accent-primary"
							/>

							<!-- 편집 -->
							<button
								onclick={() => {
									editingId = rule.id;
									editForm = { ...rule };
								}}
								class="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
							>
								<Pencil class="size-3.5" />
							</button>

							<!-- 삭제 -->
							<button
								onclick={() => deleteRule(rule.id)}
								class="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
							>
								<Trash2 class="size-3.5" />
							</button>
						</div>
					{/if}
				{/each}
			</div>
		{/if}
	</div>
</div>
