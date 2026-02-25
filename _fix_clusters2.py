path = r'D:\work\project\tools\monitor-page\frontend\src\routes\classify\images\ClustersTab.svelte'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the toastMessage block at the bottom of template
toast_block = '''\n<!-- Toast -->\n{#if toastMessage}\n\t<div class="fixed bottom-6 left-1/2 z-[60] -translate-x-1/2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm font-medium text-foreground shadow-lg">\n\t\t{toastMessage}\n\t</div>\n{/if}'''
if toast_block in content:
    content = content.replace(toast_block, '')
    print('Removed toast block')
else:
    print('Toast block not found, trying alternate')
    # find and show what's near the end
    idx = content.find('{#if toastMessage}')
    if idx >= 0:
        print(repr(content[idx-20:idx+200]))

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
