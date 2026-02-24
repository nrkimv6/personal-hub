<script lang="ts">
  import { onMount } from 'svelte';
  import { notesApi } from '$lib/api/notes';
  import type { Note, TagDef } from '$lib/api/notes';
  import { X, Loader2 } from 'lucide-svelte';
  import TagInput from './TagInput.svelte';
  import MenuPicker from './MenuPicker.svelte';
  import { navEntries, isNavGroup, type NavSingleItem } from '$lib/navigation';
  import { isCodeLike, detectLanguage } from '../utils/codeDetect';
  import { renderMarkdown } from '../utils/markdown';
  import { extractNoteLinkAtCursor } from '../utils/noteLink';

  interface Props {
    mode: 'create' | 'edit';
    note?: Note;
    onSave: () => void;
    onClose: () => void;
  }

  let { mode, note, onSave, onClose: _onClose }: Props = $props();

  function onClose() {
    clearDraft();
    _onClose();
  }

  let title = $state(note?.title ?? '');
  let content = $state(note?.content ?? '');
  let remark = $state(note?.remark ?? '');
  let tagIds = $state<number[]>(note?.tags.map((t) => t.id) ?? []);
  let linkedMenuId = $state<string | null>(note?.linked_menu_id ?? null);
  let linkedTab = $state(note?.linked_tab ?? '');
  let showMenuPicker = $state(false);
  let allTags = $state<TagDef[]>([]);
  let saving = $state(false);
  let error = $state('');
  let showPreview = $state(false);
  let textareaEl: HTMLTextAreaElement;

  // 임시 저장 (sessionStorage)
  const draftKey = mode === 'create' ? 'note-draft-create' : `note-draft-edit-${note?.id}`;
  let _draftTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    const t = title;
    const c = content;
    if (_draftTimer) clearTimeout(_draftTimer);
    _draftTimer = setTimeout(() => {
      sessionStorage.setItem(draftKey, JSON.stringify({ title: t, content: c }));
    }, 1000);
  });

  function clearDraft() {
    if (_draftTimer) clearTimeout(_draftTimer);
    sessionStorage.removeItem(draftKey);
  }

  // 자동완성 상태
  let autocompleteResults = $state<{ id: number; title: string }[]>([]);
  let showAutocomplete = $state(false);
  let autocompleteQuery = $state('');
  let autocompleteSelectedIdx = $state(-1);
  let _acDebounce: ReturnType<typeof setTimeout> | null = null;

  let previewHtml = $derived(renderMarkdown(content));

  async function loadTags() {
    allTags = await notesApi.listTags().catch(() => []);
  }

  async function refreshTags() {
    allTags = await notesApi.listTags().catch(() => []);
  }

  async function handleSave() {
    if (!title.trim()) { error = '제목을 입력해주세요.'; return; }
    saving = true;
    error = '';
    try {
      if (mode === 'create') {
        await notesApi.create({
          title: title.trim(), content, remark: remark || undefined, tag_ids: tagIds,
          linked_menu_id: linkedMenuId ?? undefined,
          linked_tab: linkedTab || undefined,
        });
      } else if (note) {
        await notesApi.update(note.id, {
          title: title.trim(), content, remark: remark || undefined, tag_ids: tagIds,
          linked_menu_id: linkedMenuId ?? undefined,
          linked_tab: linkedTab || undefined,
        });
      }
      clearDraft();
      onSave();
    } catch (e: any) {
      error = e.message;
    } finally {
      saving = false;
    }
  }

  /** textarea에서 선택 영역을 앞뒤 마커로 감쌉니다. */
  function wrapSelection(before: string, after: string) {
    const start = textareaEl.selectionStart;
    const end = textareaEl.selectionEnd;
    const selected = content.slice(start, end);
    const wrapped = before + (selected || '') + after;
    content = content.slice(0, start) + wrapped + content.slice(end);
    requestAnimationFrame(() => {
      if (selected) {
        textareaEl.selectionStart = start + before.length;
        textareaEl.selectionEnd = start + before.length + selected.length;
      } else {
        const cursor = start + before.length;
        textareaEl.selectionStart = cursor;
        textareaEl.selectionEnd = cursor;
      }
      textareaEl.focus();
    });
  }

  function handleKeydown(e: KeyboardEvent) {
    const ctrl = e.ctrlKey || e.metaKey;

    if (ctrl && e.key === 's') {
      e.preventDefault();
      handleSave();
      return;
    }

    if (ctrl && !e.shiftKey && e.key === 'b') {
      e.preventDefault();
      wrapSelection('**', '**');
      return;
    }

    if (ctrl && !e.shiftKey && e.key === 'i') {
      e.preventDefault();
      wrapSelection('*', '*');
      return;
    }

    if (ctrl && e.shiftKey && e.key === 'K') {
      e.preventDefault();
      const start = textareaEl.selectionStart;
      const block = '```\n\n```';
      content = content.slice(0, start) + block + content.slice(start);
      requestAnimationFrame(() => {
        const cursor = start + 4; // 코드블록 내부
        textareaEl.selectionStart = cursor;
        textareaEl.selectionEnd = cursor;
        textareaEl.focus();
      });
      return;
    }

    if (ctrl && e.key === 'p') {
      e.preventDefault();
      showPreview = !showPreview;
      return;
    }

    if (e.key === 'Tab') {
      e.preventDefault();
      const start = textareaEl.selectionStart;
      const end = textareaEl.selectionEnd;
      const lines = content.split('\n');

      // 선택된 줄 범위 계산
      let charCount = 0;
      let startLine = 0;
      let endLine = 0;
      for (let i = 0; i < lines.length; i++) {
        if (charCount + lines[i].length >= start && startLine === 0 && i > 0 ? charCount <= start : charCount <= start) {
          startLine = i;
        }
        if (charCount <= end) endLine = i;
        charCount += lines[i].length + 1; // +1 for \n
      }

      if (e.shiftKey) {
        // Shift+Tab: 앞 공백 2개 제거
        for (let i = startLine; i <= endLine; i++) {
          lines[i] = lines[i].replace(/^  /, '');
        }
      } else {
        // Tab: 앞에 2 spaces 추가
        for (let i = startLine; i <= endLine; i++) {
          lines[i] = '  ' + lines[i];
        }
      }
      content = lines.join('\n');
      return;
    }
  }

  function handlePaste(e: ClipboardEvent) {
    const text = e.clipboardData?.getData('text/plain') ?? '';
    if (!text || !isCodeLike(text)) return;

    e.preventDefault();
    const lang = detectLanguage(text);
    const codeBlock = `\`\`\`${lang}\n${text}\n\`\`\``;

    const start = textareaEl.selectionStart ?? content.length;
    const end = textareaEl.selectionEnd ?? content.length;
    const before = content.slice(0, start);
    const after = content.slice(end);

    // 앞에 내용이 있으면 줄바꿈 추가
    const prefix = before.length > 0 && !before.endsWith('\n') ? '\n' : '';
    const suffix = after.length > 0 && !after.startsWith('\n') ? '\n' : '';

    content = before + prefix + codeBlock + suffix + after;

    // 커서를 코드블록 뒤로
    const newPos = start + prefix.length + codeBlock.length + suffix.length;
    requestAnimationFrame(() => {
      textareaEl.selectionStart = newPos;
      textareaEl.selectionEnd = newPos;
      textareaEl.focus();
    });
  }

  function handleInput() {
    const cursorPos = textareaEl?.selectionStart ?? 0;
    const match = extractNoteLinkAtCursor(content, cursorPos);
    if (match) {
      autocompleteQuery = match.query;
      showAutocomplete = true;
      autocompleteSelectedIdx = -1;
      if (_acDebounce) clearTimeout(_acDebounce);
      _acDebounce = setTimeout(async () => {
        if (autocompleteQuery.length === 0) {
          autocompleteResults = [];
          return;
        }
        autocompleteResults = await notesApi.searchTitles(autocompleteQuery, 5).catch(() => []);
      }, 300);
    } else {
      showAutocomplete = false;
      autocompleteResults = [];
    }
  }

  function handleAutocompleteSelect(item: { id: number; title: string }) {
    const cursorPos = textareaEl?.selectionStart ?? 0;
    const match = extractNoteLinkAtCursor(content, cursorPos);
    if (!match) return;
    const replacement = `[[${item.title}]]`;
    content = content.slice(0, match.start) + replacement + content.slice(match.end);
    showAutocomplete = false;
    autocompleteResults = [];
    requestAnimationFrame(() => {
      const newPos = match.start + replacement.length;
      textareaEl.selectionStart = newPos;
      textareaEl.selectionEnd = newPos;
      textareaEl.focus();
    });
  }

  function handleAutocompleteKeydown(e: KeyboardEvent) {
    if (!showAutocomplete) return;
    if (e.key === 'Escape') {
      showAutocomplete = false;
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      autocompleteSelectedIdx = Math.min(autocompleteSelectedIdx + 1, autocompleteResults.length - 1);
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      autocompleteSelectedIdx = Math.max(autocompleteSelectedIdx - 1, 0);
      return;
    }
    if (e.key === 'Enter' && autocompleteSelectedIdx >= 0) {
      e.preventDefault();
      handleAutocompleteSelect(autocompleteResults[autocompleteSelectedIdx]);
      return;
    }
  }

  // 선택된 메뉴의 icon+label 조회
  function getMenuInfo(id: string | null): { icon: string; label: string } | null {
    if (!id) return null;
    const entry = navEntries.find((e) => !isNavGroup(e) && (e as NavSingleItem).id === id);
    if (!entry || isNavGroup(entry)) return null;
    const item = entry as NavSingleItem;
    return { icon: item.icon, label: item.label };
  }

  onMount(() => {
    loadTags();
    // draft 복원 (create 모드만)
    if (mode === 'create') {
      const raw = sessionStorage.getItem(draftKey);
      if (raw) {
        try {
          const draft = JSON.parse(raw) as { title: string; content: string };
          if (draft.title || draft.content) {
            if (confirm('임시 저장된 내용을 복원하시겠습니까?')) {
              title = draft.title ?? '';
              content = draft.content ?? '';
            } else {
              clearDraft();
            }
          }
        } catch {
          sessionStorage.removeItem(draftKey);
        }
      }
    }
  });
</script>

<div
  class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-foreground/20 backdrop-blur-sm animate-fade-in"
  onclick={onClose}
>
  <div
    class="relative w-full max-h-[90vh] bg-card rounded-xl shadow-modal flex flex-col overflow-hidden transition-all duration-200 {showPreview ? 'max-w-4xl' : 'max-w-2xl'}"
    onclick={(e) => e.stopPropagation()}
    role="dialog"
    aria-modal="true"
  >
    <!-- 헤더 -->
    <div class="flex items-center justify-between p-5 border-b border-border">
      <h2 class="text-base font-semibold text-foreground">
        {mode === 'create' ? '새 메모' : '메모 수정'}
      </h2>
      <button
        onclick={onClose}
        class="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
      ><X class="w-4 h-4" /></button>
    </div>

    <!-- 폼 -->
    <div class="flex flex-col gap-4 p-5 overflow-y-auto">
      <!-- 제목 -->
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="block text-xs font-medium text-muted-foreground">제목 *</label>
          <span class="text-xs text-muted-foreground">{title.length}/200</span>
        </div>
        <input
          type="text"
          bind:value={title}
          placeholder="메모 제목..."
          maxlength="200"
          class="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground
            focus:outline-none focus:ring-2 focus:ring-ring/30"
        />
      </div>

      <!-- 본문 -->
      <div>
        <div class="flex items-center justify-between mb-1">
          <label class="block text-xs font-medium text-muted-foreground">내용 (마크다운 지원)</label>
          <button
            type="button"
            onclick={() => (showPreview = !showPreview)}
            class="flex items-center gap-1 text-xs px-2 py-0.5 rounded border transition-colors
              {showPreview
                ? 'border-primary text-primary bg-primary/10'
                : 'border-border text-muted-foreground hover:text-foreground hover:bg-muted'}"
            title="미리보기 토글 (Ctrl+P)"
          >
            👁 미리보기
          </button>
        </div>
        <div class="{showPreview ? 'grid grid-cols-2 gap-3' : ''}">
          <div class="relative">
            <textarea
              bind:value={content}
              bind:this={textareaEl}
              onpaste={handlePaste}
              onkeydown={(e) => { handleAutocompleteKeydown(e); handleKeydown(e); }}
              oninput={handleInput}
              placeholder="마크다운 또는 코드블록 입력... ([[제목]]으로 메모 링크)"
              class="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground
                focus:outline-none focus:ring-2 focus:ring-ring/30 font-mono resize-y"
              style="min-height: 240px"
            ></textarea>
            {#if showAutocomplete && autocompleteResults.length > 0}
              <ul
                class="absolute left-0 z-20 mt-1 w-full max-w-xs bg-card border border-border rounded-lg shadow-lg overflow-hidden"
                style="top: 100%"
              >
                {#each autocompleteResults as item, idx}
                  <li>
                    <button
                      type="button"
                      class="w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors {idx === autocompleteSelectedIdx ? 'bg-muted' : ''}"
                      onmousedown={(e) => { e.preventDefault(); handleAutocompleteSelect(item); }}
                    >
                      {item.title}
                    </button>
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
          {#if showPreview}
            <div
              class="prose prose-sm dark:prose-invert overflow-y-auto border border-border rounded-lg p-3 max-h-[40vh] bg-background text-foreground"
              style="min-height: 240px"
            >
              {@html previewHtml}
            </div>
          {/if}
        </div>
      </div>

      <!-- 비고 -->
      <div>
        <label class="block text-xs font-medium text-muted-foreground mb-1">비고</label>
        <input
          type="text"
          bind:value={remark}
          placeholder="URL, source, or reference…"
          class="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground
            focus:outline-none focus:ring-2 focus:ring-ring/30"
        />
      </div>

      <!-- 연결 메뉴 -->
      <div>
        <label class="block text-xs font-medium text-muted-foreground mb-1">연결 메뉴</label>
        <div class="relative">
          <button
            type="button"
            onclick={() => (showMenuPicker = !showMenuPicker)}
            class="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground
              hover:bg-muted transition-colors text-left"
          >
            {#if linkedMenuId && getMenuInfo(linkedMenuId)}
              {@const info = getMenuInfo(linkedMenuId)!}
              <span>{info.icon}</span>
              <span>{info.label}</span>
            {:else}
              <span class="text-muted-foreground">메뉴 선택...</span>
            {/if}
          </button>
          {#if showMenuPicker}
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <div
              class="absolute top-full left-0 mt-1 z-30"
              onmouseleave={() => {}}
            >
              <MenuPicker
                selectedMenuId={linkedMenuId}
                onSelect={(id) => {
                  linkedMenuId = id;
                  if (!id) linkedTab = '';
                  showMenuPicker = false;
                }}
              />
            </div>
            <!-- 외부 클릭 닫기 -->
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <div
              class="fixed inset-0 z-20"
              onclick={() => (showMenuPicker = false)}
            ></div>
          {/if}
        </div>
        {#if linkedMenuId}
          <input
            type="text"
            bind:value={linkedTab}
            placeholder="탭 이름 (선택)"
            class="mt-2 w-full px-3 py-2 text-sm rounded-lg border border-border bg-background text-foreground
              focus:outline-none focus:ring-2 focus:ring-ring/30"
          />
        {/if}
      </div>

      <!-- 태그 -->
      <div>
        <label class="block text-xs font-medium text-muted-foreground mb-1">태그</label>
        <TagInput
          selectedTagIds={tagIds}
          {allTags}
          onChange={(ids) => (tagIds = ids)}
          onTagsRefresh={refreshTags}
        />
      </div>

      {#if error}
        <p class="text-sm text-destructive">{error}</p>
      {/if}
    </div>

    <!-- 하단 -->
    <div class="flex justify-end gap-2 p-4 border-t border-border">
      <button
        onclick={onClose}
        class="px-4 py-2 text-sm rounded-lg bg-muted text-foreground hover:bg-muted/80 transition-colors"
      >취소</button>
      <button
        onclick={handleSave}
        disabled={saving}
        class="flex items-center gap-1.5 px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary-hover disabled:opacity-50 transition-colors"
      >
        {#if saving}
          <Loader2 class="w-4 h-4 animate-spin" />
          저장 중...
        {:else}
          저장
        {/if}
      </button>
    </div>
  </div>
</div>
