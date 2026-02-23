<script lang="ts">
  import { onMount } from 'svelte';
  import { marked } from 'marked';
  import hljs from 'highlight.js';
  import DOMPurify from 'dompurify';
  import type { Note, NoteHistoryItem } from '$lib/api/notes';
  import { notesApi } from '$lib/api/notes';
  import { ArrowLeft, Copy, Archive, Pencil, Pin, ChevronDown, ChevronUp, Check, X } from 'lucide-svelte';
  import TagBadge from './TagBadge.svelte';

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
  let copied = $state(false);
  let showArchiveConfirm = $state(false);

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

  async function handleArchiveConfirm() {
    archiving = true;
    showArchiveConfirm = false;
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
    navigator.clipboard.writeText(note.content).then(() => {
      copied = true;
      setTimeout(() => (copied = false), 1500);
    }).catch(() => {});
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleString('ko-KR');
  }

  // 코드블록 복사 버튼 삽입 (렌더링 후)
  function addCopyButtons(el: HTMLElement) {
    el.querySelectorAll('pre').forEach((pre) => {
      if (pre.querySelector('.copy-btn')) return;
      const btn = document.createElement('button');
      btn.textContent = 'Copy';
      btn.className = 'copy-btn absolute top-2 right-2 text-xs px-2 py-1 bg-muted text-muted-foreground rounded hover:bg-border transition-colors';
      btn.onclick = () => {
        const code = pre.querySelector('code')?.textContent || '';
        navigator.clipboard.writeText(code).catch(() => {});
        btn.textContent = 'Copied!';
        setTimeout(() => (btn.textContent = 'Copy'), 1200);
      };
      pre.style.position = 'relative';
      pre.appendChild(btn);
    });
  }

  let contentEl = $state<HTMLElement | null>(null);
  $effect(() => {
    if (contentEl && renderedHtml) {
      setTimeout(() => contentEl && addCopyButtons(contentEl), 50);
    }
  });
</script>

<!-- 오버레이 -->
<div
  class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-foreground/20 backdrop-blur-sm animate-fade-in"
  onclick={onClose}
>
  <div
    class="relative w-full max-w-2xl max-h-[90vh] bg-card rounded-xl shadow-modal flex flex-col overflow-hidden"
    onclick={(e) => e.stopPropagation()}
    role="dialog"
    aria-modal="true"
  >
    <!-- 헤더 -->
    <div class="flex items-start justify-between p-5 border-b border-border">
      <div class="flex-1 pr-4">
        <div class="flex items-center gap-2">
          <h2 class="text-lg font-semibold text-foreground">{note.title}</h2>
          {#if note.is_pinned}
            <Pin class="w-4 h-4 text-primary fill-current flex-shrink-0" />
          {/if}
        </div>
        <p class="text-xs text-muted-foreground mt-1">
          수정: {formatDate(note.updated_at)}
        </p>
        {#if note.tags.length > 0}
          <div class="flex flex-wrap gap-1 mt-2">
            {#each note.tags as tag}
              <TagBadge {tag} />
            {/each}
          </div>
        {/if}
      </div>
      <button
        onclick={onClose}
        class="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
      ><X class="w-4 h-4" /></button>
    </div>

    <!-- 본문 -->
    <div class="flex-1 overflow-y-auto p-5">
      {#if note.remark}
        <div class="mb-3 p-3 bg-info-light rounded-lg text-sm text-info">
          {note.remark}
        </div>
      {/if}
      <div
        bind:this={contentEl}
        class="prose-notes"
      >
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        {@html renderedHtml}
      </div>

      <!-- 수정 이력 -->
      <div class="mt-4 border-t border-border pt-3">
        <button
          onclick={loadHistory}
          class="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          {#if showHistory}
            <ChevronUp class="w-4 h-4" />
          {:else}
            <ChevronDown class="w-4 h-4" />
          {/if}
          수정 이력 {history.length > 0 ? `(${history.length}건)` : ''}
        </button>
        {#if showHistory}
          {#if history.length === 0}
            <p class="text-xs text-muted-foreground mt-2">이력 없음</p>
          {:else}
            <ul class="mt-2 space-y-2">
              {#each history as h}
                <li class="text-xs text-muted-foreground border-l-2 border-border pl-3">
                  <span class="font-medium text-foreground">{h.title}</span>
                  <span class="ml-2">{formatDate(h.changed_at)}</span>
                </li>
              {/each}
            </ul>
          {/if}
        {/if}
      </div>
    </div>

    <!-- 하단 액션 -->
    <div class="flex gap-2 p-4 border-t border-border">
      <button
        onclick={handleCopyAll}
        class="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-border hover:bg-muted transition-colors"
      >
        {#if copied}
          <Check class="w-4 h-4 text-success" />
          <span class="text-success">Copied!</span>
        {:else}
          <Copy class="w-4 h-4" />
          Copy All
        {/if}
      </button>
      <div class="flex-1"></div>

      {#if showArchiveConfirm}
        <span class="flex items-center gap-1">
          <button
            onclick={handleArchiveConfirm}
            class="px-3 py-2 text-sm rounded-lg bg-warning/20 text-warning border border-warning/30 hover:bg-warning/30 transition-colors"
          >Confirm</button>
          <button
            onclick={() => (showArchiveConfirm = false)}
            class="px-3 py-2 text-sm rounded-lg bg-muted text-muted-foreground hover:bg-border transition-colors"
          >Cancel</button>
        </span>
      {:else}
        <button
          onclick={() => (showArchiveConfirm = true)}
          disabled={archiving}
          class="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-border text-warning hover:bg-warning/10 transition-colors"
        ><Archive class="w-4 h-4" /> Archive</button>
      {/if}

      <button
        onclick={() => onEdit(note)}
        class="flex items-center gap-1.5 px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary-hover transition-colors"
      ><Pencil class="w-4 h-4" /> Edit</button>
    </div>
  </div>
</div>
