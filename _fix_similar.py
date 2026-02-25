path = r'D:\work\project\tools\monitor-page\frontend\src\routes\classify\duplicates\SimilarTab.svelte'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add toast import after existing imports block
old_import = "	import { Search, RefreshCw, Tag, ArrowRight, Cpu, AlertTriangle, Eye, FolderOpen, Clipboard } from 'lucide-svelte';"
new_import = old_import + "\n\timport { toast } from '$lib/stores/toast';"
content = content.replace(old_import, new_import)
print('import:', 'ok' if "from '$lib/stores/toast'" in content else 'FAIL')

# 2. Remove toastMessage, toastTimer state and showToast function
old_toast_state = """\tlet toastMessage = $state<string | null>(null);
\tlet toastTimer: ReturnType<typeof setTimeout> | null = null;

\t// 카테고리 맵 (폴백용)"""
new_toast_state = """\t// 카테고리 맵 (폴백용)"""
if old_toast_state in content:
    content = content.replace(old_toast_state, new_toast_state)
    print('Removed toastMessage/toastTimer state')
else:
    print('State block not found')

old_show_toast = """\tfunction showToast(msg: string) {
\t\ttoastMessage = msg;
\t\tif (toastTimer) clearTimeout(toastTimer);
\t\ttoastTimer = setTimeout(() => { toastMessage = null; }, 3000);
\t}

\t// CLIP 임베딩 상태"""
new_show_toast = """\t// CLIP 임베딩 상태"""
if old_show_toast in content:
    content = content.replace(old_show_toast, new_show_toast)
    print('Removed showToast function')
else:
    print('showToast function not found')

# 3. Replace showToast calls
content = content.replace(
    'showToast(`${fileIds.length}개 파일이 "${group.category_path}"로 분류되었습니다.`)',
    'toast.success(`${fileIds.length}개 파일이 "${group.category_path}"로 분류되었습니다.`)'
)

# 4. Replace alert calls - error cases
replacements = [
    ("alert(`CLIP 임베딩 계산 시작 실패: ${getErrorMessage(err)}`)", "toast.error(`CLIP 임베딩 계산 시작 실패: ${getErrorMessage(err)}`)"),
    ("alert(`CLIP 임베딩 오류: ${data.error}`)", "toast.error(`CLIP 임베딩 오류: ${data.error}`)"),
    ("alert('FAISS 인덱스 빌드 완료!')", "toast.success('FAISS 인덱스 빌드 완료!')"),
    ("alert(`인덱스 빌드 실패: ${getErrorMessage(err)}`)", "toast.error(`인덱스 빌드 실패: ${getErrorMessage(err)}`)"),
    ("alert('파일을 선택해주세요.')", "toast.warning('파일을 선택해주세요.')"),
    ("alert(err.detail || '뷰어 열기 실패')", "toast.error(err.detail || '뷰어 열기 실패')"),
    ("alert(`뷰어 열기 실패: ${getErrorMessage(err)}`)", "toast.error(`뷰어 열기 실패: ${getErrorMessage(err)}`)"),
    ("alert(err.detail || '탐색기 열기 실패')", "toast.error(err.detail || '탐색기 열기 실패')"),
    ("alert(`탐색기 열기 실패: ${getErrorMessage(err)}`)", "toast.error(`탐색기 열기 실패: ${getErrorMessage(err)}`)"),
    ("alert('클립보드 복사 실패')", "toast.error('클립보드 복사 실패')"),
]
for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print(f'Replaced: {old[:50]}')
    else:
        print(f'NOT FOUND: {old[:50]}')

# 5. Remove toastMessage template block
toast_block = '\n<!-- Toast -->\n{#if toastMessage}\n\t<div class="fixed bottom-6 left-1/2 z-[60] -translate-x-1/2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-medium text-foreground shadow-lg">\n\t\t{toastMessage}\n\t</div>\n{/if}'
if toast_block in content:
    content = content.replace(toast_block, '')
    print('Removed toast template block')
else:
    print('Toast template block not found')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
