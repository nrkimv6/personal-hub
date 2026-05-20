<script lang="ts">
	import { Button } from '$lib/components/ui';
	import type { LLMQueueStats, LLMStats, LLMWorkerStatus } from '$lib/api';
	import type { LlmTabId } from '../types';

	interface Props {
		stats: LLMStats | null;
		workerStatus: LLMWorkerStatus | null;
		queueStats: LLMQueueStats | null;
		activeTab: LlmTabId;
		onSwitchTab: (tab: LlmTabId) => void | Promise<void>;
		onRefresh: () => void | Promise<void>;
		onRunCleanup: () => void | Promise<void>;
	}

	let {
		stats,
		workerStatus,
		queueStats,
		activeTab,
		onSwitchTab,
		onRefresh,
		onRunCleanup
	}: Props = $props();
</script>

<div class="space-y-4">
	<div class="flex flex-wrap justify-end gap-2">
		<div class="flex gap-2">
			<Button variant="secondary" size="sm" onclick={onRunCleanup} title="Stale 정리 및 오래된 이력 삭제">
				정리
			</Button>
			<Button variant="secondary" size="sm" onclick={onRefresh}>
				새로고침
			</Button>
		</div>
	</div>

	{#if queueStats}
		<div class="grid grid-cols-2 gap-4 mb-4">
			<div class="card p-4 border-l-4 border-blue-500">
				<div class="text-sm text-muted-foreground">system 대기</div>
				<div class="text-2xl font-bold text-blue-600">{queueStats.system.pending}</div>
				<div class="text-xs text-muted-foreground">우선순위 높음</div>
			</div>
			<div class="card p-4 border-l-4 border-gray-400">
				<div class="text-sm text-muted-foreground">utility 대기</div>
				<div class="text-2xl font-bold text-gray-600">{queueStats.utility.pending}</div>
				<div class="text-xs text-muted-foreground">일반 자동화</div>
			</div>
		</div>
	{/if}

	{#if stats || workerStatus}
		<div class="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">워커 상태</div>
				<div class="text-lg font-bold {workerStatus?.status === 'healthy' ? 'text-success' : workerStatus?.status === 'warning' ? 'text-warning-foreground' : workerStatus?.status === 'no_worker' ? 'text-muted-foreground' : 'text-error'}">
					{workerStatus?.status === 'healthy' ? '정상' : workerStatus?.status === 'warning' ? '지연' : workerStatus?.status === 'no_worker' ? '없음' : '비정상'}
				</div>
				{#if workerStatus?.state}
					<div class="text-xs text-muted-foreground">{workerStatus.state}</div>
				{/if}
				{#if workerStatus?.message && workerStatus?.status !== 'healthy'}
					<div class="text-xs text-muted-foreground">{workerStatus.message}</div>
				{/if}
			</div>

			{#if stats}
				<div class="card p-4">
					<div class="text-sm text-muted-foreground">전체</div>
					<div class="text-2xl font-bold text-foreground">{stats.total}</div>
				</div>
				<button type="button" class="card p-4 text-left {activeTab !== 'create' ? 'hover:bg-warning-light' : ''}" onclick={() => onSwitchTab('queue')} disabled={activeTab === 'create'}>
					<div class="text-sm text-muted-foreground">대기중</div>
					<div class="text-2xl font-bold text-warning-foreground">{stats.pending}</div>
				</button>
				<button type="button" class="card p-4 text-left {activeTab !== 'create' ? 'hover:bg-primary-light' : ''}" onclick={() => onSwitchTab('queue')} disabled={activeTab === 'create'}>
					<div class="text-sm text-muted-foreground">처리중</div>
					<div class="text-2xl font-bold text-primary">{stats.processing}</div>
				</button>
				<button type="button" class="card p-4 text-left {activeTab !== 'create' ? 'hover:bg-success-light' : ''}" onclick={() => onSwitchTab('history')} disabled={activeTab === 'create'}>
					<div class="text-sm text-muted-foreground">완료</div>
					<div class="text-2xl font-bold text-success">{stats.completed}</div>
				</button>
				<button type="button" class="card p-4 text-left {activeTab !== 'create' ? 'hover:bg-error-light' : ''}" onclick={() => onSwitchTab('history')} disabled={activeTab === 'create'}>
					<div class="text-sm text-muted-foreground">실패</div>
					<div class="text-2xl font-bold text-error">{stats.failed}</div>
				</button>
			{/if}
		</div>
	{/if}
</div>
