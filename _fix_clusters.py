path = r'D:\work\project\tools\monitor-page\frontend\src\routes\classify\images\ClustersTab.svelte'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

replacements = [
    ('showToast(`카테고리 할당 완료: ${catName}`)', 'toast.success(`카테고리 할당 완료: ${catName}`)'),
    ('alert(`카테고리 지정 실패: ${(err as Error).message}`)', 'toast.error(`카테고리 지정 실패: ${(err as Error).message}`)'),
    ('alert(`클러스터 상세 로드 실패: ${(err as Error).message}`)', 'toast.error(`클러스터 상세 로드 실패: ${(err as Error).message}`)'),
    ('showToast(`클러스터 #${clusterId} 검토 완료`)', 'toast.success(`클러스터 #${clusterId} 검토 완료`)'),
    ('alert(`검토 완료 실패: ${(err as Error).message}`)', 'toast.error(`검토 완료 실패: ${(err as Error).message}`)'),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print(f'Replaced: {old[:40]}...')
    else:
        print(f'NOT FOUND: {old[:40]}...')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
