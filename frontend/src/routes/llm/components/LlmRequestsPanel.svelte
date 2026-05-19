<script lang="ts">
	import { Button } from '$lib/components/ui';
	import type {
		LLMCallerGroup,
		LLMGroupedListResponse,
		LLMHistoryStats,
		LLMRequest,
		LLMStats,
		QuotaStatusMap
	} from '$lib/api';
	import {
		formatDateTime,
		getGroupKey,
		getPendingPauseInfo,
		getStatusColor,
		getStatusLabel,
		truncatePrompt
	} from '../helpers';
	import type { LlmTabId } from '../types';

	interface Props {
		activeTab: Extract<LlmTabId, 'queue' | 'history'>;
		loading: boolean;
		error: string | null;
		stats: LLMStats | null;
		requests: LLMRequest[];
		callerGroups: LLMCallerGroup[];
		groupedResponse: LLMGroupedListResponse | null;
		historyStats: LLMHistoryStats | null;
		viewMode: 'individual' | 'grouped';
		onlyWithoutSuccess: boolean;
		filterCallerType: string;
		filterRequestedBy: string;
		filterQueueName: string;
		selectedIds: number[];
		selectAll: boolean;
		selectedGroupKeys: string[];
		groupSelectAll: boolean;
		currentPage: number;
		pageSize: number;
		total: number;
		pages: number;
		groupCurrentPage: number;
		groupPageSize: number;
		groupTotal: number;
		groupPages: number;
		quotaStatus: QuotaStatusMap;
		onFilter: () => void | Promise<void>;
		onGroupFilter: () => void | Promise<void>;
		onClearFilters: () => void | Promise<void>;
		onToggleViewMode: () => void | Promise<void>;
		onRetryAllFailedWithoutSuccess: () => void | Promise<void>;
		onMultiRetrySelectedGroups: () => void | Promise<void>;
		onToggleGroupSelectAll: () => void;
		onToggleGroupSelect: (group: LLMCallerGroup) => void;
		onBatchRetry: () => void | Promise<void>;
		onBatchDelete: () => void | Promise<void>;
		onToggleSelectAll: () => void;
		onToggleSelect: (id: number) => void;
		onOpenRequest: (request: LLMRequest) => void | Promise<void>;
		onCancelRequest: (id: number) => void | Promise<void>;
		onRetryRequest: (id: number) => void | Promise<void>;
		onDeleteRequest: (id: number) => void | Promise<void>;
		onPrevPage: () => void | Promise<void>;
		onNextPage: () => void | Promise<void>;
		onGroupPrevPage: () => void | Promise<void>;
		onGroupNextPage: () => void | Promise<void>;
		onSwitchTab: (tab: LlmTabId) => void | Promise<void>;
	}

	let {
		activeTab,
		loading,
		error,
		stats,
		requests,
		callerGroups,
		groupedResponse,
		historyStats,
		viewMode = $bindable(),
		onlyWithoutSuccess = $bindable(),
		filterCallerType = $bindable(),
		filterRequestedBy = $bindable(),
		filterQueueName = $bindable(),
		selectedIds,
		selectAll,
		selectedGroupKeys,
		groupSelectAll,
		currentPage,
		pageSize,
		total,
		pages,
		groupCurrentPage,
		groupPageSize,
		groupTotal,
		groupPages,
		quotaStatus,
		onFilter,
		onGroupFilter,
		onClearFilters,
		onToggleViewMode,
		onRetryAllFailedWithoutSuccess,
		onMultiRetrySelectedGroups,
		onToggleGroupSelectAll,
		onToggleGroupSelect,
		onBatchRetry,
		onBatchDelete,
		onToggleSelectAll,
		onToggleSelect,
		onOpenRequest,
		onCancelRequest,
		onRetryRequest,
		onDeleteRequest,
		onPrevPage,
		onNextPage,
		onGroupPrevPage,
		onGroupNextPage,
		onSwitchTab
	}: Props = $props();
</script>

<div class="mb-4 flex flex-wrap gap-2 items-center">
	<span class="text-sm text-muted-foreground">
		{activeTab === 'queue' ? '대기열: pending, processing' : '이력: completed, failed, cancelled'}
	</span>
	<div class="flex gap-1">
		<button
			onclick={() => { filterQueueName = ''; onFilter(); }}
			class="px-2 py-1 text-xs rounded-full border transition-colors {filterQueueName === '' ? 'bg-foreground text-background border-foreground' : 'border-border text-muted-foreground hover:border-gray-400'}"
		>전체</button>
		<button
			onclick={() => { filterQueueName = 'system'; onFilter(); }}
			class="px-2 py-1 text-xs rounded-full border transition-colors {filterQueueName === 'system' ? 'bg-blue-600 text-white border-blue-600' : 'border-border text-muted-foreground hover:border-blue-400'}"
		>system</button>
		<button
			onclick={() => { filterQueueName = 'utility'; onFilter(); }}
			class="px-2 py-1 text-xs rounded-full border transition-colors {filterQueueName === 'utility' ? 'bg-gray-500 text-white border-gray-500' : 'border-border text-muted-foreground hover:border-gray-400'}"
		>utility</button>
	</div>
	<select bind:value={filterCallerType} class="px-3 py-1.5 border border-border rounded-lg text-sm">
		<option value="">전체 타입</option>
		<option value="instagram">Instagram</option>
		<option value="test">Test</option>
	</select>
	{#if activeTab === 'history' && viewMode === 'individual'}
		<input
			type="text"
			placeholder="요청자"
			bind:value={filterRequestedBy}
			class="px-3 py-1.5 border border-border rounded-lg text-sm"
		/>
	{/if}
	{#if activeTab === 'queue'}
		<input
			type="text"
			placeholder="요청자"
			bind:value={filterRequestedBy}
			class="px-3 py-1.5 border border-border rounded-lg text-sm"
		/>
	{/if}
	{#if activeTab === 'history' && viewMode === 'grouped'}
		<label class="flex items-center gap-1 text-sm">
			<input
				type="checkbox"
				bind:checked={onlyWithoutSuccess}
				onchange={onGroupFilter}
				class="rounded"
			/>
			성공 없는 것만
		</label>
	{/if}
	<Button variant="primary" size="sm" onclick={viewMode === 'grouped' ? onGroupFilter : onFilter}>필터</Button>
	<Button variant="secondary" size="sm" onclick={onClearFilters}>초기화</Button>

	{#if activeTab === 'history'}
		<div class="ml-auto flex items-center gap-2">
			<Button
				variant={viewMode === 'grouped' ? 'primary' : 'secondary'}
				size="sm"
				onclick={onToggleViewMode}
			>
				{viewMode === 'individual' ? '그룹 뷰' : '개별 뷰'}
			</Button>
		</div>
	{/if}
</div>

{#if activeTab === 'history' && viewMode === 'grouped' && groupedResponse}
	<div class="mb-4 flex gap-4 items-center p-3 bg-background rounded-lg flex-wrap">
		<div class="text-sm">
			<span class="text-muted-foreground">전체:</span>
			<span class="font-bold text-foreground">{groupedResponse.summary.total_callers}</span>
		</div>
		<div class="text-sm">
			<span class="text-success">성공 있음:</span>
			<span class="font-bold text-success">{groupedResponse.summary.callers_with_success}</span>
		</div>
		<div class="text-sm">
			<span class="text-error">성공 없음:</span>
			<span class="font-bold text-error">{groupedResponse.summary.callers_without_success}</span>
		</div>
		<div class="ml-auto flex gap-2">
			{#if selectedGroupKeys.length > 0}
				<span class="text-sm text-muted-foreground self-center">{selectedGroupKeys.length}개 선택</span>
				<Button variant="secondary" size="sm" onclick={onMultiRetrySelectedGroups}>
					선택 그룹 재시도
				</Button>
			{/if}
			{#if groupedResponse.summary.callers_without_success > 0}
				<Button variant="primary" size="sm" onclick={onRetryAllFailedWithoutSuccess}>
					성공 없는 것 일괄 재시도
				</Button>
			{/if}
		</div>
	</div>
{/if}

{#if viewMode === 'individual' && selectedIds.length > 0}
	<div class="mb-4 flex gap-2 items-center">
		<span class="text-sm text-muted-foreground">{selectedIds.length}개 선택</span>
		{#if activeTab === 'history'}
			<Button variant="secondary" size="sm" onclick={onBatchRetry}>일괄 재시도</Button>
		{/if}
		<button onclick={onBatchDelete} class="btn btn-danger btn-sm">일괄 삭제</button>
	</div>
{/if}

{#if loading}
	<div class="flex justify-center items-center h-64">
		<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
	</div>
{:else if error}
	<div class="bg-error-light border border-red-200 text-error px-4 py-3 rounded-lg">{error}</div>
{:else if activeTab === 'history' && viewMode === 'grouped'}
	{#if callerGroups.length === 0}
		<div class="text-center py-12 text-muted-foreground">
			<p class="text-lg">그룹화된 이력이 없습니다</p>
		</div>
	{:else}
		<div class="bg-white rounded-lg border border-border overflow-x-auto mb-6">
			<table class="w-full min-w-[900px]">
				<thead class="bg-background border-b border-border">
					<tr>
						<th class="px-4 py-3 text-left whitespace-nowrap">
							<input
								type="checkbox"
								checked={groupSelectAll}
								onchange={onToggleGroupSelectAll}
								class="rounded"
							/>
						</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">타입</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">호출자 ID</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">요청내용</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">요청 수</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">성공</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">실패</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">대기</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">성공 여부</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">최근 상태</th>
						<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">마지막 요청</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-border">
					{#each callerGroups as group}
						<tr class="hover:bg-muted {group.has_success ? '' : 'bg-error-light'}">
							<td class="px-4 py-3">
								<input
									type="checkbox"
									checked={selectedGroupKeys.includes(getGroupKey(group))}
									onchange={() => onToggleGroupSelect(group)}
									class="rounded"
								/>
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground">{group.caller_type}</td>
							<td class="px-4 py-3 text-sm text-foreground font-mono">{group.caller_id}</td>
							<td class="px-4 py-3 text-sm text-foreground max-w-xs truncate" title={group.prompt}>
								{truncatePrompt(group.prompt)}
							</td>
							<td class="px-4 py-3 text-sm text-foreground font-bold">{group.total_count}</td>
							<td class="px-4 py-3 text-sm text-success font-bold">{group.completed_count}</td>
							<td class="px-4 py-3 text-sm text-error font-bold">{group.failed_count}</td>
							<td class="px-4 py-3 text-sm text-warning-foreground">{group.pending_count}</td>
							<td class="px-4 py-3">
								{#if group.has_success}
									<span class="px-2 py-1 text-xs rounded-full bg-success-light text-success">있음</span>
								{:else}
									<span class="px-2 py-1 text-xs rounded-full bg-error-light text-error">없음</span>
								{/if}
							</td>
							<td class="px-4 py-3">
								<span class="px-2 py-1 text-xs rounded-full {getStatusColor(group.last_status)}">
									{getStatusLabel(group.last_status)}
								</span>
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(group.last_requested_at)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		{#if groupPages > 1}
			<div class="flex justify-between items-center">
				<span class="text-sm text-muted-foreground">
					전체 {groupTotal}개 중 {(groupCurrentPage - 1) * groupPageSize + 1} - {Math.min(groupCurrentPage * groupPageSize, groupTotal)}
				</span>
				<div class="flex gap-2">
					<button
						onclick={onGroupPrevPage}
						disabled={groupCurrentPage === 1}
						class="btn btn-secondary btn-sm disabled:opacity-50"
					>
						이전
					</button>
					<span class="px-3 py-1.5 text-sm">{groupCurrentPage} / {groupPages}</span>
					<button
						onclick={onGroupNextPage}
						disabled={groupCurrentPage >= groupPages}
						class="btn btn-secondary btn-sm disabled:opacity-50"
					>
						다음
					</button>
				</div>
			</div>
		{/if}
	{/if}
{:else if requests.length === 0}
	<div class="text-center py-12 text-muted-foreground">
		<p class="text-lg">{activeTab === 'queue' ? '대기열이 비어있습니다' : '이력이 없습니다'}</p>
		{#if activeTab === 'queue' && stats && (stats.completed + stats.failed) > 0}
			<div class="mt-3">
				<Button variant="secondary" size="sm" onclick={() => onSwitchTab('history')}>
					이력 보기
				</Button>
			</div>
		{/if}
	</div>
{:else}
	<div class="bg-white rounded-lg border border-border overflow-x-auto mb-6">
		<table class="w-full min-w-[700px]">
			<thead class="bg-background border-b border-border">
				<tr>
					<th class="px-4 py-3 text-left whitespace-nowrap">
						<input
							type="checkbox"
							checked={selectAll}
							onchange={onToggleSelectAll}
							class="rounded"
						/>
					</th>
					<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">ID</th>
					<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">큐</th>
					<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">타입</th>
					<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">호출자 ID</th>
					<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">요청자</th>
					<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">Provider</th>
					<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">상태</th>
					<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">요청시간</th>
					<th class="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase whitespace-nowrap">액션</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#each requests as request (request.id)}
					{@const pauseInfo = getPendingPauseInfo(request, quotaStatus)}
					<tr
						class="hover:bg-muted cursor-pointer"
						onclick={() => onOpenRequest(request)}
					>
						<td class="px-4 py-3" onclick={(e) => e.stopPropagation()}>
							<input
								type="checkbox"
								checked={selectedIds.includes(request.id)}
								onchange={() => onToggleSelect(request.id)}
								class="rounded"
							/>
						</td>
						<td class="px-4 py-3 text-sm text-foreground">{request.id}</td>
						<td class="px-4 py-3">
							{#if request.queue_name === 'system'}
								<span class="px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700">system</span>
							{:else}
								<span class="px-2 py-0.5 text-xs rounded-full bg-gray-100 text-gray-600">utility</span>
							{/if}
						</td>
						<td class="px-4 py-3 text-sm text-muted-foreground">{request.caller_type}</td>
						<td class="px-4 py-3 text-sm text-muted-foreground">{request.caller_id}</td>
						<td class="px-4 py-3 text-sm text-muted-foreground">{request.requested_by || '-'}</td>
						<td class="px-4 py-3 text-sm text-muted-foreground">
							{request.provider ? (request.provider === 'claude' ? 'Claude' : 'Gemini') : 'Claude'}
						</td>
						<td class="px-4 py-3">
							<span class="px-2 py-1 text-xs rounded-full {getStatusColor(request.status)}">
								{getStatusLabel(request.status)}
							</span>
							{#if pauseInfo}
								<span
									class="ml-1 px-2 py-1 text-xs rounded-full {pauseInfo.tone === 'window' ? 'bg-blue-100 text-blue-700' : 'bg-warning-light text-warning-foreground'}"
									title={pauseInfo.title}
								>
									{pauseInfo.label}
								</span>
							{/if}
						</td>
						<td class="px-4 py-3 text-sm text-muted-foreground">{formatDateTime(request.requested_at)}</td>
						<td class="px-4 py-3" onclick={(e) => e.stopPropagation()}>
							<div class="flex gap-1">
								{#if request.status === 'pending'}
									<button
										onclick={() => onCancelRequest(request.id)}
										class="text-warning-foreground hover:text-warning-foreground text-sm"
									>
										취소
									</button>
								{/if}
								{#if request.status === 'failed' || request.status === 'completed'}
									<button
										onclick={() => onRetryRequest(request.id)}
										class="text-primary hover:text-primary-hover text-sm"
									>
										{request.status === 'completed' ? '재분석' : '재시도'}
									</button>
								{/if}
								<button
									onclick={() => onDeleteRequest(request.id)}
									class="text-error hover:text-error text-sm"
								>
									삭제
								</button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if pages > 1}
		<div class="flex justify-between items-center">
			<span class="text-sm text-muted-foreground">
				전체 {total}개 중 {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, total)}
			</span>
			<div class="flex gap-2">
				<button
					onclick={onPrevPage}
					disabled={currentPage === 1}
					class="btn btn-secondary btn-sm disabled:opacity-50"
				>
					이전
				</button>
				<span class="px-3 py-1.5 text-sm">{currentPage} / {pages}</span>
				<button
					onclick={onNextPage}
					disabled={currentPage >= pages}
					class="btn btn-secondary btn-sm disabled:opacity-50"
				>
					다음
				</button>
			</div>
		</div>
	{/if}
{/if}

{#if activeTab === 'history' && historyStats}
	<div class="mt-8">
		<h3 class="text-lg font-bold text-foreground mb-4">7일간 통계</h3>
		<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">총 요청</div>
				<div class="text-2xl font-bold text-foreground">{historyStats.summary.total}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">성공률</div>
				<div class="text-2xl font-bold text-success">{historyStats.summary.success_rate}%</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">완료</div>
				<div class="text-2xl font-bold text-success">{historyStats.summary.completed}</div>
			</div>
			<div class="card p-4">
				<div class="text-sm text-muted-foreground">평균 처리 시간</div>
				<div class="text-2xl font-bold text-primary">{historyStats.summary.avg_processing_time_seconds}s</div>
			</div>
		</div>
	</div>
{/if}
