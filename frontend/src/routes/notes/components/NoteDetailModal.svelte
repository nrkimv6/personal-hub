<script lang="ts">
  import { onMount } from 'svelte';
  import { marked } from 'marked';
  import hljs from 'highlight.js';
  import DOMPurify from 'dompurify';
  import type { Note, NoteHistoryItem } from '$lib/api/notes';
  import { notesApi } from '$lib/api/notes';

  interface Props {
    note: Note;
    onClose: () => void;
    onEdit: (note: Note) => void;
    onRefresh: () => void;
  }

  let { note, onClose, onEdit, onRefresh }: Props = $props();

  let history = $state<NoteHistoryItem[]>([]);
  let showHistory = $state(false);
  let archiving = $state(false);
  let renderedHtml = $state('');

  // marked 설정 (highlight.js 연동)
  marked.setOptions({
    highlight: (code, lang) => {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return hljs.highlightAuto(code).value;
    },
  } as any);

  $effect(() => {
    const raw = marked.parse(note.content || '') as string;
    renderedHtml = DOMPurify.sanitize(raw);
  });

  async function loadHistory() {
    showHistory = !showHistory;
    if (showHistory && history.length === 0) {
      history = await notesApi.getHistory(note.id).catch(() => []);
    }
  }

  async function handleArchive() {
    if (!confirm('아카이브로 이동하시겠습니까?')) return;
    archiving = true;
    try {
      await notesApi.archive(note.id);
      onRefresh();
      onClose();
    } catch (e: any) {
      alert(e.message);
    } finally {
      archiving = false;
    }
  }

  function handleCopyAll() {
    navigator.clipboard.writeText(note.content).catch(() => {});
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleString('ko-KR');
  }

  // 코드블록 복사 버튼 삽입 (렌더링 후)
  function addCopyButtons(el: HTMLElement) {
    el.querySelectorAll('pre').forEach((pre) => {
      if (pre.querySelector('.copy-btn')) return;
      const btn = document.createElement('button');
      btn.textContent = '복사';
      btn.className = 'copy-btn absolute top-2 right-2 text-xs px-2 py-0.5 bg-gray-700 text-white rounded hover:bg-gray-500';
      btn.onclick = () => {
        const code = pre.querySelector('code')?.textContent || '';
        navigator.clipboard.writeText(code).catch(() => {});
        btn.textContent = '복사됨!';
        setTimeout(() => (btn.textContent = '복사'), 1200);
      };
      pre.style.position = 'relative';
      pre.appendChild(btn);
    });
  }

  let contentEl = $state<HTMLElement | null>(null);
  $effect(() => {
    if (contentEl && renderedHtml) {
      // 다음 틱에 실행해 DOM이 업데이트된 후 처리
      setTimeout(() => contentEl && addCopyButtons(contentEl), 50);
    }
  });
</script>

<!-- 오버레이 -->
<div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" onclick={onClose}>
  <div
    class="relative w-full max-w-2xl max-h-[90vh] bg-white dark:bg-gray-800 rounded-2xl shadow-xl flex flex-col overflow-hidden"
    onclick={(e) => e.stopPropagation()}
    role="dialog"
    aria-modal="true"
  >
    <!-- 헤더 -->
    <div class="flex items-start justify-between p-5 border-b border-gray-200 dark:border-gray-700">
      <div class="flex-1 pr-4">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">{note.title}</h2>
        <p class="text-xs text-gray-400 mt-1">
          수정: {formatDate(note.updated_at)}
          {#if note.is_pinned} · 📌 고정{/if}
        </p>
        {#if note.tags.length > 0}
          <div class="flex flex-wrap gap-1 mt-2">
            {#each note.tags as tag}
              <span class="px-2 py-0.5 text-xs rounded-full text-white" style="background-color: {tag.color}">{tag.name}</span>
            {/each}
          </div>
        {/if}
      </div>
      <button onclick={onClose} class="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
    </div>

    <!-- 본문 -->
    <div class="flex-1 overflow-y-auto p-5">
      {#if note.remark}
        <div class="mb-3 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-sm text-blue-700 dark:text-blue-300">
          📎 {note.remark}
        </div>
      {/if}
      <div
        bind:this={contentEl}
        class="prose prose-sm dark:prose-invert max-w-none"
      >
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        {@html renderedHtml}
      </div>

      <!-- 수정 이력 -->
      <div class="mt-4 border-t border-gray-200 dark:border-gray-700 pt-3">
        <button
          onclick={loadHistory}
          class="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400"
        >
          {showHistory ? '▲' : '▼'} 수정 이력 {history.length > 0 ? `(${history.length}건)` : ''}
        </button>
        {#if showHistory}
          {#if history.length === 0}
            <p class="text-xs text-gray-400 mt-2">이력 없음</p>
          {:else}
            <ul class="mt-2 space-y-2">
              {#each history as h}
                <li class="text-xs text-gray-500 dark:text-gray-400 border-l-2 border-gray-300 pl-3">
                  <span class="font-medium text-gray-700 dark:text-gray-300">{h.title}</span>
                  <span class="ml-2">{formatDate(h.changed_at)}</span>
                </li>
              {/each}
            </ul>
          {/if}
        {/if}
      </div>
    </div>

    <!-- 하단 액션 -->
    <div class="flex gap-2 p-4 border-t border-gray-200 dark:border-gray-700">
      <button onclick={handleCopyAll} class="px-3 py-2 text-sm rounded-lg border hover:bg-gray-50 dark:hover:bg-gray-700">전체 복사</button>
      <div class="flex-1"></div>
      <button
        onclick={handleArchive}
        disabled={archiving}
        class="px-3 py-2 text-sm rounded-lg border text-orange-600 hover:bg-orange-50 dark:hover:bg-orange-900/20"
      >아카이브</button>
      <button
        onclick={() => onEdit(note)}
        class="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700"
      >수정</button>
    </div>
  </div>
</div>
