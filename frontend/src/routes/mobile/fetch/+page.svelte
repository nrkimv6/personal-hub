<script>
	import { onMount } from "svelte";

	let url = $state("");
	let waitForSelector = $state("");
	let waitTimeout = $state(30);
	let screenshot = $state(false);

	let loading = $state(false);
	let result = $state(null);
	let error = $state(null);

	async function fetchHtml() {
		if (!url) {
			error = "URL을 입력해주세요.";
			return;
		}

		try {
			loading = true;
			error = null;
			result = null;

			const response = await fetch("/api/v1/mobile/fetch-html", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify({
					url,
					wait_for_selector: waitForSelector || undefined,
					wait_timeout: waitTimeout,
					screenshot,
				}),
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(errorData.detail || "HTML 수집 실패");
			}

			result = await response.json();
		} catch (err) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	function clearResults() {
		result = null;
		error = null;
	}

	function copyHtml() {
		if (result?.html) {
			navigator.clipboard.writeText(result.html);
			alert("HTML이 클립보드에 복사되었습니다.");
		}
	}
</script>

<div class="container mx-auto p-4 max-w-6xl">
	<div class="mb-6">
		<h1 class="text-2xl font-bold">모바일 HTML 수집 도구</h1>
		<p class="text-gray-600 mt-1">
			모바일 서버를 통해 페이지의 렌더링된 HTML을 수집합니다.
		</p>
	</div>

	<!-- 입력 폼 -->
	<div class="card bg-base-100 shadow mb-6">
		<div class="card-body">
			<h2 class="card-title">수집 설정</h2>

			<!-- URL -->
			<div class="form-control">
				<label class="label">
					<span class="label-text">URL (필수)</span>
				</label>
				<input
					type="text"
					bind:value={url}
					placeholder="https://example.com"
					class="input input-bordered"
					disabled={loading}
				/>
			</div>

			<!-- 대기 셀렉터 -->
			<div class="form-control">
				<label class="label">
					<span class="label-text">대기 셀렉터 (선택)</span>
					<span class="label-text-alt"
						>특정 요소가 나타날 때까지 대기</span
					>
				</label>
				<input
					type="text"
					bind:value={waitForSelector}
					placeholder=".product-list, #content"
					class="input input-bordered"
					disabled={loading}
				/>
			</div>

			<!-- 타임아웃 -->
			<div class="form-control">
				<label class="label">
					<span class="label-text">최대 대기 시간 (초)</span>
				</label>
				<input
					type="number"
					bind:value={waitTimeout}
					min="5"
					max="120"
					class="input input-bordered w-full max-w-xs"
					disabled={loading}
				/>
			</div>

			<!-- 스크린샷 -->
			<div class="form-control">
				<label class="label cursor-pointer justify-start gap-2">
					<input
						type="checkbox"
						bind:checked={screenshot}
						class="checkbox"
						disabled={loading}
					/>
					<span class="label-text">스크린샷 수집</span>
				</label>
			</div>

			<!-- 버튼 -->
			<div class="card-actions justify-end mt-4">
				<button
					class="btn btn-ghost"
					onclick={clearResults}
					disabled={loading || (!result && !error)}
				>
					초기화
				</button>
				<button
					class="btn btn-primary"
					onclick={fetchHtml}
					disabled={loading}
				>
					{#if loading}
						<span class="loading loading-spinner"></span>
						수집 중...
					{:else}
						HTML 수집
					{/if}
				</button>
			</div>
		</div>
	</div>

	<!-- 에러 표시 -->
	{#if error}
		<div class="alert alert-error mb-6">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				class="stroke-current shrink-0 h-6 w-6"
				fill="none"
				viewBox="0 0 24 24"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
				/>
			</svg>
			<span>{error}</span>
		</div>
	{/if}

	<!-- 결과 표시 -->
	{#if result}
		<div class="space-y-6">
			<!-- 메타 정보 -->
			<div class="card bg-base-100 shadow">
				<div class="card-body">
					<h2 class="card-title">페이지 정보</h2>

					<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
						<div>
							<div class="text-sm font-semibold text-gray-600">
								페이지 제목
							</div>
							<div class="text-base mt-1">
								{result.title || "N/A"}
							</div>
						</div>
						<div>
							<div class="text-sm font-semibold text-gray-600">
								수집 시각
							</div>
							<div class="text-base mt-1">
								{new Date(result.fetched_at).toLocaleString()}
							</div>
						</div>
						<div class="md:col-span-2">
							<div class="text-sm font-semibold text-gray-600">
								최종 URL
							</div>
							<div class="text-base mt-1 break-all">
								<a
									href={result.final_url}
									target="_blank"
									class="link link-primary"
								>
									{result.final_url}
								</a>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- 스크린샷 -->
			{#if result.screenshot_base64}
				<div class="card bg-base-100 shadow">
					<div class="card-body">
						<h2 class="card-title">스크린샷</h2>
						<div class="border rounded-lg overflow-hidden">
							<img
								src="data:image/png;base64,{result.screenshot_base64}"
								alt="Page Screenshot"
								class="w-full"
							/>
						</div>
					</div>
				</div>
			{/if}

			<!-- HTML 원본 -->
			<div class="card bg-base-100 shadow">
				<div class="card-body">
					<div
						class="flex flex-wrap justify-between items-center gap-2 mb-2"
					>
						<h2 class="card-title">HTML 원본</h2>
						<button class="btn btn-sm btn-ghost" onclick={copyHtml}>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								class="h-4 w-4 mr-1"
								fill="none"
								viewBox="0 0 24 24"
								stroke="currentColor"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
								/>
							</svg>
							복사
						</button>
					</div>

					<div class="text-sm text-gray-600 mb-2">
						크기: {(result.html.length / 1024).toFixed(2)} KB
					</div>

					<textarea
						readonly
						value={result.html}
						class="textarea textarea-bordered w-full font-mono text-xs"
						rows="20"
					></textarea>
				</div>
			</div>
		</div>
	{/if}
</div>
