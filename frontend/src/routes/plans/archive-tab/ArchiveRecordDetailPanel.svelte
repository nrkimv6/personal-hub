<script lang="ts">
  import {
    type PlanRecord,
    type PlanRecordRelation,
  } from '$lib/api/plan-records';
  import MemoEditor from '../MemoEditor.svelte';
  import PlanViewer from '../PlanViewer.svelte';

  let {
    record,
    relations,
    relationsLoading,
    detailTab,
    onClose,
    onTabChange,
  }: {
    record: PlanRecord;
    relations: PlanRecordRelation[];
    relationsLoading: boolean;
    detailTab: 'content' | 'memo';
    onClose: () => void;
    onTabChange: (tab: 'content' | 'memo') => void;
  } = $props();

  function formatDate(iso: string | null) {
    if (!iso) return '-';
    return new Date(iso).toLocaleDateString('ko-KR');
  }

  function getCategoryFromPath(filePath: string): string {
    const CATEGORIES = ['feature', 'bugfix', 'refactor', 'infra', 'docs', 'test', 'misc'];
    const name = filePath.split(/[\\/]/).pop() ?? filePath;
    const noDate = name.replace(/^\d{4}-\d{2}-\d{2}_/, '');
    const prefix = noDate.split('-')[0].toLowerCase();
    const map: Record<string, string> = {
      feat: 'feature', fix: 'bugfix', hotfix: 'bugfix',
      refactor: 'refactor', ref: 'refactor',
      chore: 'infra', ci: 'infra', infra: 'infra', build: 'infra',
      docs: 'docs', doc: 'docs', test: 'test',
    };
    const parts = filePath.split(/[\\/]/);
    if (parts.length >= 2) {
      const parent = parts[parts.length - 2].toLowerCase();
      if (CATEGORIES.includes(parent)) return parent;
    }
    return map[prefix] ?? 'misc';
  }

  function relationLabel(type: string) {
    const labels: Record<string, string> = {
      predecessor: '선행', successor: '후속',
      unresolved_followup: '미해결 후속', cause: '원인',
      guard: '방어', supersedes: '대체', mentions: '언급'
    };
    return labels[type] ?? type;
  }

  function relationPeer(relation: PlanRecordRelation) {
    return relation.direction === 'incoming' ? relation.source : relation.target;
  }

</script>

<div class="w-80 flex-shrink-0 border-l border-border pl-4 flex flex-col gap-2">
  <div class="flex items-center justify-between">
    <h3 class="text-xs font-semibold text-foreground truncate">
      {record.file_path.split(/[\\/]/).pop()}
    </h3>
    <button
      class="text-muted-foreground hover:text-foreground text-xs"
      onclick={onClose}
    >닫기</button>
  </div>
  <p class="text-xs text-muted-foreground">완료일: {formatDate(record.archived_at)}</p>
  <p class="text-xs text-muted-foreground">
    카테고리: <span class="font-medium">{getCategoryFromPath(record.file_path)}</span>
  </p>
  <div class="rounded border border-border p-2 text-xs">
    <div class="mb-1 flex items-center justify-between">
      <span class="font-semibold text-foreground">계획 관계</span>
      {#if relations.some((relation) => relation.relation_type === 'unresolved_followup')}
        <span class="rounded bg-red-100 px-1.5 py-0.5 text-red-700 dark:bg-red-900 dark:text-red-200">미해결 후속</span>
      {/if}
    </div>
    {#if relationsLoading}
      <p class="text-muted-foreground">불러오는 중...</p>
    {:else if relations.length === 0}
      <p class="text-muted-foreground">관계 없음</p>
    {:else}
      <div class="space-y-1">
        {#each relations.slice(0, 5) as relation}
          <div class="flex min-w-0 items-center gap-1">
            <span class="shrink-0 rounded bg-muted px-1 py-0.5 text-muted-foreground">{relation.direction === 'incoming' ? 'in' : 'out'}</span>
            <span class="shrink-0 rounded px-1 py-0.5 {relation.relation_type === 'unresolved_followup' ? 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200' : 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200'}">
              {relationLabel(relation.relation_type)}
            </span>
            <span class="truncate text-muted-foreground" title={relationPeer(relation).file_path}>
              {relationPeer(relation).title || relationPeer(relation).file_path.split(/[\\/]/).pop()}
            </span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
  <!-- 탭 버튼 -->
  <div class="flex gap-1 border-b border-border pb-1">
    <button
      class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'content' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => onTabChange('content')}
    >내용</button>
    <button
      class="text-xs px-2 py-1 rounded-t transition-colors {detailTab === 'memo' ? 'bg-muted font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground'}"
      onclick={() => onTabChange('memo')}
    >메모</button>
  </div>

  <div class="flex-1 overflow-auto">
    {#if detailTab === 'content'}
      <PlanViewer filePath={record.file_path} recordId={record.id} />
    {:else}
      <MemoEditor filePath={record.file_path} />
    {/if}
  </div>
</div>
