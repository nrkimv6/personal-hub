<script lang="ts">
	import { Button } from '$lib/components/ui';
	import type { LLMRequest, QuotaStatusMap } from '$lib/api';
	import { formatDateTime, formatWaitTime, getStatusColor, getStatusLabel } from '../helpers';

	interface Props {
		request: LLMRequest;
		quotaStatus: QuotaStatusMap;
		countdownSeconds: number;
		editCwd: string;
		editCwdSaving: boolean;
		onClose: () => void;
		onCancelRequest: (id: number) => void | Promise<void>;
		onRetryRequest: (id: number) => void | Promise<void>;
		onDeleteRequest: (id: number) => void | Promise<void>;
		onUpdateCwd: (andRetry?: boolean) => void | Promise<void>;
	}

	let {
		request,
		quotaStatus,
		countdownSeconds,
		editCwd = $bindable(),
		editCwdSaving,
		onClose,
		onCancelRequest,
		onRetryRequest,
		onDeleteRequest,
		onUpdateCwd
	}: Props = $props();
</script>

<div
	class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
	onclick={onClose}
	onkeydown={(e) => e.key === 'Escape' && onClose()}
	role="dialog"
	tabindex="-1"
>
	<div
		class="bg-white rounded-xl max-w-2xl w-full max-h-[90vh] overflow-auto"
		onclick={(e) => e.stopPropagation()}
		onkeydown={(e) => e.stopPropagation()}
		role="document"
		tabindex="-1"
	>
		<div class="p-6">
			<div class="flex justify-between items-start mb-4">
				<div>
					<h3 class="text-lg font-bold text-foreground">요청 상세 #{request.id}</h3>
					<span class="px-2 py-1 text-xs rounded-full {getStatusColor(request.status)}">
						{getStatusLabel(request.status)}
					</span>
				</div>
				<button onclick={onClose} class="text-muted-foreground hover:text-muted-foreground text-2xl">
					&times;
				</button>
			</div>

			<div class="grid grid-cols-2 gap-4 text-sm mb-4">
				<div>
					<span class="text-muted-foreground">타입:</span>
					<span class="ml-1">{request.caller_type}</span>
				</div>
				<div>
					<span class="text-muted-foreground">호출자 ID:</span>
					<span class="ml-1">{request.caller_id}</span>
				</div>
				<div>
					<span class="text-muted-foreground">요청자:</span>
					<span class="ml-1">{request.requested_by || '-'}</span>
				</div>
				<div>
					<span class="text-muted-foreground">출처:</span>
					<span class="ml-1">{request.request_source || '-'}</span>
				</div>
				<div>
					<span class="text-muted-foreground">Provider:</span>
					<span class="ml-1">{request.provider || 'claude'}</span>
				</div>
				<div>
					<span class="text-muted-foreground">Model:</span>
					<span class="ml-1">{request.model || '(기본)'}</span>
				</div>
				<div>
					<span class="text-muted-foreground">요청 시간:</span>
					<span class="ml-1">{formatDateTime(request.requested_at)}</span>
				</div>
				<div>
					<span class="text-muted-foreground">처리 시간:</span>
					<span class="ml-1">{formatDateTime(request.processed_at)}</span>
				</div>
				<div>
					<span class="text-muted-foreground">재시도 횟수:</span>
					<span class="ml-1">{request.retry_count}</span>
				</div>
			</div>

			{#if request.status === 'pending'}
				{@const provider = request.provider || 'claude'}
				{@const ps = quotaStatus[provider]}
				{@const windowPause = quotaStatus.__execution_window}
				{#if windowPause?.paused}
					<div class="mb-4 p-3 bg-blue-50 rounded-lg flex items-start gap-2">
						<span class="text-blue-700 text-sm font-medium">시간창 보류</span>
						<span class="text-blue-700 text-sm ml-auto">
							{windowPause.remaining_seconds != null ? `${formatWaitTime(windowPause.remaining_seconds)} 후 재개` : '다음 시간창 대기'}
						</span>
					</div>
				{:else if ps?.paused}
					<div class="mb-4 p-3 bg-warning-light rounded-lg flex items-start gap-2">
						<span class="text-warning-foreground text-sm font-medium">⏸ {provider === 'gemini' ? 'Gemini' : 'Claude'} 쿼터 소진</span>
						<span class="text-warning-foreground text-sm ml-auto">{formatWaitTime(countdownSeconds)} 후 재개</span>
					</div>
				{:else}
					<div class="mb-4 p-3 bg-muted rounded-lg">
						<span class="text-muted-foreground text-sm">⏳ 처리 대기 중</span>
					</div>
				{/if}
			{/if}

			{#if request.status === 'pending' || request.status === 'failed'}
				<div class="mb-4 p-3 bg-muted rounded-lg">
					<div class="text-sm font-medium text-foreground mb-1">실행 경로 (cwd)</div>
					<div class="flex gap-2">
						<input
							type="text"
							bind:value={editCwd}
							class="input input-sm flex-1 font-mono text-xs"
							placeholder="D:/work/project/..."
						/>
						{#if request.status === 'failed'}
							<button
								onclick={() => onUpdateCwd(true)}
								disabled={editCwdSaving}
								class="btn btn-primary btn-sm whitespace-nowrap"
							>
								{editCwdSaving ? '저장중...' : '저장 후 재시도'}
							</button>
						{:else}
							<button
								onclick={() => onUpdateCwd(false)}
								disabled={editCwdSaving}
								class="btn btn-secondary btn-sm"
							>
								{editCwdSaving ? '저장중...' : '저장'}
							</button>
						{/if}
					</div>
				</div>
			{/if}

			{#if request.error_message}
				<div class="mb-4 p-3 bg-error-light rounded-lg">
					<div class="text-sm font-medium text-error mb-1">에러 메시지</div>
					<p class="text-sm text-error whitespace-pre-wrap">{request.error_message}</p>
				</div>
			{/if}

			{#if request.result}
				<div class="mb-4 p-3 bg-background rounded-lg">
					<div class="text-sm font-medium text-foreground mb-1">결과</div>
					<pre class="text-sm text-foreground whitespace-pre-wrap overflow-auto max-h-64">{JSON.stringify(request.result, null, 2)}</pre>
				</div>
			{/if}

			{#if request.raw_response}
				<div class="mb-4 p-3 bg-background rounded-lg">
					<div class="flex items-center justify-between mb-1">
						<div class="text-sm font-medium text-foreground">LLM 원본 응답</div>
						<span class="text-xs text-muted-foreground">{request.raw_response.length.toLocaleString()}자</span>
					</div>
					<pre class="text-xs text-muted-foreground whitespace-pre-wrap overflow-auto max-h-96 border border-border rounded p-2">{request.raw_response}</pre>
				</div>
			{/if}

			<div class="flex gap-2 flex-wrap">
				{#if request.status === 'pending'}
					<button
						onclick={() => { onCancelRequest(request.id); onClose(); }}
						class="btn btn-secondary btn-sm"
					>
						취소
					</button>
				{/if}
				{#if request.status === 'failed' || request.status === 'completed'}
					<button
						onclick={() => { onRetryRequest(request.id); onClose(); }}
						class="btn btn-primary btn-sm"
					>
						{request.status === 'completed' ? '재분석' : '재시도'}
					</button>
				{/if}
				<button
					onclick={() => { onDeleteRequest(request.id); onClose(); }}
					class="btn btn-danger btn-sm"
				>
					삭제
				</button>
				<Button variant="secondary" size="sm" onclick={onClose}>닫기</Button>
			</div>
		</div>
	</div>
</div>
