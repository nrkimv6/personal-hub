<script lang="ts">
	import { onMount } from 'svelte';
	import { devRunnerPlanApi } from '$lib/api/dev-runner';
	import { planRecordsApi, type PlanRecord } from '$lib/api/plan-records';
	import MarkdownContent from '$lib/components/markdown/MarkdownContent.svelte';

	interface Props {
		filePath: string;
		recordId?: number;
	}

	let { filePath, recordId }: Props = $props();

	let content = $state('');
	let loading = $state(false);
	let error = $state('');

	// 체인 + AI 제안
	let chainRecords = $state<PlanRecord[]>([]);
	let suggestion = $state<{ root_cause: string; pattern: string; suggestion: string } | null>(null);

	async function loadContent(path: string) {
		if (!path) return;
		loading = true;
		error = '';
		content = '';
		try {
			const encoded = btoa(unescape(encodeURIComponent(path)));
			const res = await devRunnerPlanApi.content(encoded);
			content = res.content;
		} catch (e: any) {
			error = e?.message ?? '내용을 불러오지 못했습니다.';
		} finally {
			loading = false;
		}
	}

	async function loadChain(id: number) {
		try {
			const chain = await planRecordsApi.getChain(id);
			chainRecords = chain;
			// 최신 record에서 AI 제안 파싱
			const latest = chain.slice().sort((a, b) => (b.recurrence_count ?? 1) - (a.recurrence_count ?? 1))[0];
			if (latest?.recurrence_suggestion) {
				try {
					suggestion = JSON.parse(latest.recurrence_suggestion);
				} catch {
					suggestion = null;
				}
			} else {
				suggestion = null;
			}
		} catch {
			chainRecords = [];
			suggestion = null;
		}
	}

	onMount(() => {
		loadContent(filePath);
		if (recordId) loadChain(recordId);
	});

	$effect(() => {
		loadContent(filePath);
	});

	$effect(() => {
		if (recordId) {
			loadChain(recordId);
		} else {
			chainRecords = [];
			suggestion = null;
		}
	});

	function formatDate(s: string | null) {
		if (!s) return '?';
		return s.slice(0, 10);
	}
</script>

{#if loading}
	<div class="flex items-center justify-center py-8 text-gray-400 text-sm">
		<svg class="animate-spin h-5 w-5 mr-2 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
			<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
			<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"></path>
		</svg>
		불러오는 중...
	</div>
{:else if error}
	<div class="text-red-500 text-sm py-4 px-2">
		{error}
	</div>
{:else}
	<div class="min-h-full px-4 py-3">
		<!-- 반복 체인 섹션 (2개 이상일 때만 표시) -->
		{#if chainRecords.length >= 2}
			<div class="mb-3 p-3 bg-orange-50 border border-orange-200 rounded text-xs">
				<div class="font-semibold text-orange-700 mb-1">🔁 반복 이력 ({chainRecords.length}회)</div>
				<div class="flex flex-wrap gap-1 text-orange-600">
					{#each chainRecords as r, i}
						<span>
							{i + 1}회 {formatDate(r.archived_at ?? r.created_at)}
							{#if i < chainRecords.length - 1}<span class="text-orange-400">→</span>{:else}<span class="text-orange-400 font-semibold">(현재)</span>{/if}
						</span>
					{/each}
				</div>
			</div>
		{/if}

		<!-- 마크다운 내용 -->
		<MarkdownContent content={content} variant="plan" />

		<!-- AI 제안 카드 -->
		{#if suggestion}
			<div class="mt-3 border-l-4 border-orange-400 bg-orange-50 p-3 text-xs">
				<div class="font-semibold text-orange-700 mb-1">🤖 반복 수정 AI 분석</div>
				<div class="mb-1">
					<span class="font-medium text-orange-600">근본 원인:</span>
					<span class="text-gray-700"> {suggestion.root_cause}</span>
				</div>
				<div class="mb-1">
					<span class="font-medium text-orange-600">패턴:</span>
					<span class="text-gray-700"> {suggestion.pattern}</span>
				</div>
				<div>
					<span class="font-medium text-orange-600">개선 제안:</span>
					<span class="text-gray-700"> {suggestion.suggestion}</span>
				</div>
			</div>
		{/if}
	</div>
{/if}
