<script lang="ts">
	import { calculateDiff, type DiffResult } from '$lib/utils/instagram-follow-diff';

	let followersHtml = $state('');
	let followingHtml = $state('');
	let result = $state<DiffResult | null>(null);
	let error = $state('');

	function readFile(file: File): Promise<string> {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(reader.result as string);
			reader.onerror = () => reject(reader.error);
			reader.readAsText(file, 'utf-8');
		});
	}

	async function handleFollowersChange(event: Event) {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		followersHtml = await readFile(file);
	}

	async function handleFollowingChange(event: Event) {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		followingHtml = await readFile(file);
	}

	$effect(() => {
		if (!followersHtml || !followingHtml) return;
		error = '';
		const diff = calculateDiff(followersHtml, followingHtml);
		if (diff.notFollowingMeBack.length === 0 && diff.iDontFollowBack.length === 0) {
			error = '파싱된 항목이 없습니다. 올바른 인스타그램 HTML 파일인지 확인해주세요.';
			result = null;
		} else {
			result = diff;
		}
	});
</script>

<div class="max-w-4xl">
	<p class="text-muted-foreground mb-6 text-sm">
		인스타그램 개인정보 다운로드에서 받은 <code>followers_1.html</code>과
		<code>following.html</code>을 업로드하면 맞팔 여부를 분석합니다.
	</p>

	<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
		<div class="border rounded-lg p-4">
			<label class="block text-sm font-medium mb-2" for="followers-input">
				팔로워 목록 <span class="text-muted-foreground font-normal">(followers_1.html)</span>
			</label>
			<input
				id="followers-input"
				type="file"
				accept=".html,.htm"
				onchange={handleFollowersChange}
				class="w-full text-sm file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-sm file:font-medium file:bg-primary/10 file:text-primary hover:file:bg-primary/20 cursor-pointer"
			/>
			{#if followersHtml}
				<p class="text-xs text-green-600 mt-1">로드 완료</p>
			{/if}
		</div>

		<div class="border rounded-lg p-4">
			<label class="block text-sm font-medium mb-2" for="following-input">
				팔로잉 목록 <span class="text-muted-foreground font-normal">(following.html)</span>
			</label>
			<input
				id="following-input"
				type="file"
				accept=".html,.htm"
				onchange={handleFollowingChange}
				class="w-full text-sm file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-sm file:font-medium file:bg-primary/10 file:text-primary hover:file:bg-primary/20 cursor-pointer"
			/>
			{#if followingHtml}
				<p class="text-xs text-green-600 mt-1">로드 완료</p>
			{/if}
		</div>
	</div>

	{#if error}
		<div class="border border-red-300 bg-red-50 text-red-700 rounded-lg p-3 mb-6 text-sm">
			{error}
		</div>
	{/if}

	{#if result}
		<div class="space-y-8">
			<section>
				<h2 class="text-lg font-semibold mb-3">
					나를 맞팔하지 않는 사람
					<span class="text-muted-foreground font-normal text-base">
						({result.notFollowingMeBack.length}명)
					</span>
				</h2>
				{#if result.notFollowingMeBack.length === 0}
					<p class="text-muted-foreground text-sm">없음</p>
				{:else}
					<div class="border rounded-lg overflow-hidden">
						<table class="w-full text-sm">
							<tbody>
								{#each result.notFollowingMeBack as user}
									<tr class="border-b last:border-0 hover:bg-muted/30">
										<td class="px-4 py-2 font-mono">{user.id}</td>
										<td class="px-4 py-2">
											<a
												href={user.link}
												target="_blank"
												rel="noopener noreferrer"
												class="text-blue-600 hover:underline text-xs"
											>
												프로필 열기
											</a>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</section>

			<section>
				<h2 class="text-lg font-semibold mb-3">
					내가 맞팔하지 않는 사람
					<span class="text-muted-foreground font-normal text-base">
						({result.iDontFollowBack.length}명)
					</span>
				</h2>
				{#if result.iDontFollowBack.length === 0}
					<p class="text-muted-foreground text-sm">없음</p>
				{:else}
					<div class="border rounded-lg overflow-hidden">
						<table class="w-full text-sm">
							<tbody>
								{#each result.iDontFollowBack as user}
									<tr class="border-b last:border-0 hover:bg-muted/30">
										<td class="px-4 py-2 font-mono">{user.id}</td>
										<td class="px-4 py-2">
											<a
												href={user.link}
												target="_blank"
												rel="noopener noreferrer"
												class="text-blue-600 hover:underline text-xs"
											>
												프로필 열기
											</a>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{/if}
			</section>
		</div>
	{/if}
</div>
