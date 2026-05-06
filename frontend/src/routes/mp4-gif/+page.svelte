<script lang="ts">
import { goto } from '$app/navigation';
import { onMount } from 'svelte';

const targetPath = '/file-search?tab=mp4-gif';

onMount(() => {
	// Source of truth는 file-search 허브 탭이다.
	void goto(targetPath, { replaceState: true });
});
</script>

<svelte:head>
	<title>MP4 → GIF | Monitor Page</title>
</svelte:head>

<div class="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
	<p>
		MP4 → GIF 도구가 <a class="font-medium text-primary underline underline-offset-4" href={targetPath}>파일 도구</a>로 이동했습니다.
	</p>
</div>
