<script>
	import { goto } from '$app/navigation';

	let form = $state({
		name: '',
		url: '',
		crawl_type: 'list',
		is_active: true
	});

	let saving = $state(false);
	let error = $state(null);

	async function handleSubmit() {
		try {
			saving = true;
			error = null;

			const response = await fetch('/api/v1/mobile/targets', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(form)
			});

			if (!response.ok) {
				const data = await response.json();
				throw new Error(data.detail || '생성 실패');
			}

			const target = await response.json();
			goto(`/mobile/targets/${target.id}`);
		} catch (err) {
			error = err.message;
		} finally {
			saving = false;
		}
	}
</script>

<div class="container mx-auto p-4 max-w-2xl">
	<h1 class="text-2xl font-bold mb-6">새 크롤링 대상 추가</h1>

	<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} class="space-y-4">
		{#if error}
			<div class="alert alert-error">{error}</div>
		{/if}

		<div class="form-control">
			<label class="label">
				<span class="label-text">대상 이름</span>
			</label>
			<input
				type="text"
				bind:value={form.name}
				class="input input-bordered"
				placeholder="예: 쿠팡 이벤트 페이지"
				required
			/>
		</div>

		<div class="form-control">
			<label class="label">
				<span class="label-text">대상 URL</span>
			</label>
			<input
				type="url"
				bind:value={form.url}
				class="input input-bordered"
				placeholder="https://..."
				required
			/>
		</div>

		<div class="form-control">
			<label class="label">
				<span class="label-text">크롤링 타입</span>
			</label>
			<select bind:value={form.crawl_type} class="select select-bordered">
				<option value="list">목록 페이지</option>
				<option value="detail">상세 페이지</option>
			</select>
		</div>

		<div class="form-control">
			<label class="label cursor-pointer">
				<span class="label-text">활성화</span>
				<input type="checkbox" bind:checked={form.is_active} class="checkbox" />
			</label>
		</div>

		<div class="form-control">
			<div class="alert alert-info">
				<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" class="stroke-current shrink-0 w-6 h-6"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
				<span>파싱 설정은 대상 생성 후 수정 페이지에서 추가할 수 있습니다.</span>
			</div>
		</div>

		<div class="flex gap-2">
			<button type="submit" class="btn btn-primary" disabled={saving}>
				{saving ? '저장 중...' : '생성'}
			</button>
			<button
				type="button"
				class="btn btn-ghost"
				onclick={() => goto('/mobile/targets')}
			>
				취소
			</button>
		</div>
	</form>
</div>
