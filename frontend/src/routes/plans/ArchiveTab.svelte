<script lang="ts">
  import { onMount } from 'svelte';
  import { planRecordsApi, type PlanRecord } from '$lib/api/plan-records';
  import MemoEditor from './MemoEditor.svelte';

  let records: PlanRecord[] = [];
  let loading = true;
  let selectedRecord: PlanRecord | null = null;
  let error = '';
  let skip = 0;
  const limit = 50;
  let hasMore = false;

  async function loadRecords(append = false) {
    loading = true;
    error = '';
    try {
      const data = await planRecordsApi.list({ status: 'archived', skip: append ? skip : 0, limit });
      if (append) {
        records = [...records, ...data];
        skip += data.length;
      } else {
        records = data;
        skip = data.length;
      }
      hasMore = data.length === limit;
    } catch (e) {
      error = e instanceof Error ? e.message : '목록 로드 실패';
    } finally {
      loading = false;
    }
  }

  function selectRecord(record: PlanRecord) {
    selectedRecord = selectedRecord?.id === record.id ? null : record;
  }

  function formatDate(iso: string | null) {
    if (!iso) return '-';
    return new Date(iso).toLocaleDateString('ko-KR');
  }

  onMount(() => loadRecords());
</script>

<div class="flex gap-4 h-full">
  <!-- 목록 패널 -->
  <div class="flex-1 flex flex-col min-w-0">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-sm font-semibold text-gray-300">아카이브된 계획서</h2>
      <button
        class="px-3 py-1 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
        on:click={() => loadRecords()}
      >새로고침</button>
    </div>

    {#if error}
      <p class="text-sm text-red-400 mb-2">{error}</p>
    {/if}

    {#if loading && records.length === 0}
      <p class="text-sm text-gray-400">로드 중...</p>
    {:else if records.length === 0}
      <p class="text-sm text-gray-500">아카이브된 계획서가 없습니다.</p>
    {:else}
      <div class="overflow-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-400 text-xs border-b border-gray-700">
              <th class="pb-2 pr-4 font-medium">파일명</th>
              <th class="pb-2 pr-4 font-medium">완료일</th>
              <th class="pb-2 font-medium">메모</th>
            </tr>
          </thead>
          <tbody>
            {#each records as record (record.id)}
              <tr
                class="border-b border-gray-800 hover:bg-gray-800 cursor-pointer transition-colors {selectedRecord?.id === record.id ? 'bg-gray-800' : ''}"
                on:click={() => selectRecord(record)}
              >
                <td class="py-2 pr-4 text-gray-200 font-mono text-xs max-w-xs truncate" title={record.file_path}>
                  {record.file_path.split(/[\\/]/).pop() ?? record.file_path}
                </td>
                <td class="py-2 pr-4 text-gray-400 text-xs whitespace-nowrap">
                  {formatDate(record.archived_at)}
                </td>
                <td class="py-2">
                  {#if record.memo}
                    <span class="text-xs text-gray-400 truncate max-w-xs inline-block" title={record.memo}>
                      {record.memo.slice(0, 40)}{record.memo.length > 40 ? '...' : ''}
                    </span>
                  {:else}
                    <button
                      class="px-2 py-0.5 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-400"
                      on:click|stopPropagation={() => selectRecord(record)}
                    >메모 추가</button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      {#if hasMore}
        <button
          class="mt-3 px-4 py-2 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-300 self-center"
          disabled={loading}
          on:click={() => loadRecords(true)}
        >
          {loading ? '로드 중...' : '더 보기'}
        </button>
      {/if}
    {/if}
  </div>

  <!-- 메모 패널 -->
  {#if selectedRecord}
    <div class="w-80 flex-shrink-0 border-l border-gray-700 pl-4 flex flex-col gap-2">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-semibold text-gray-300 truncate">
          {selectedRecord.file_path.split(/[\\/]/).pop()}
        </h3>
        <button
          class="text-gray-500 hover:text-gray-300 text-xs"
          on:click={() => { selectedRecord = null; }}
        >닫기</button>
      </div>
      <p class="text-xs text-gray-500">완료일: {formatDate(selectedRecord.archived_at)}</p>
      <div class="flex-1">
        <MemoEditor filePath={selectedRecord.file_path} />
      </div>
    </div>
  {/if}
</div>
