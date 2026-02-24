<script>
	import { onMount } from "svelte";
	import PageHeader from '$lib/components/layout/PageHeader.svelte';

	// Sample HTML for testing
	const SAMPLE_HTML = `<!DOCTYPE html>
<html>
<head><title>샘플 상품 목록</title></head>
<body>
  <div class="product-list">
    <div class="product-card" data-id="1">
      <img src="/images/product1.jpg" class="product-image" alt="상품 1">
      <h3 class="product-title">갤럭시 S24 Ultra</h3>
      <span class="price">1,299,000원</span>
      <span class="status in-stock">재고 있음</span>
      <a href="/products/1" class="detail-link">상세보기</a>
    </div>
    <div class="product-card" data-id="2">
      <img src="/images/product2.jpg" class="product-image" alt="상품 2">
      <h3 class="product-title">iPhone 15 Pro</h3>
      <span class="price">1,550,000원</span>
      <span class="status out-of-stock">품절</span>
      <a href="/products/2" class="detail-link">상세보기</a>
    </div>
  </div>
  <div class="pagination">
    <a href="?page=1">1</a>
    <a href="?page=2">2</a>
    <a href="?page=3">3</a>
  </div>
</body>
</html>`;

	let html = $state(SAMPLE_HTML);
	let testSelector = $state(".product-card");
	let testResult = $state(null);
	let testError = $state(null);

	// Parse config builder
	let containerSelector = $state(".product-card");
	let attributes = $state([
		{ name: "title", selector: ".product-title", type: "text" },
		{ name: "price", selector: ".price", type: "text" },
		{ name: "status", selector: ".status", type: "text" },
		{
			name: "image",
			selector: ".product-image",
			type: "attr",
			attr: "src",
		},
		{ name: "link", selector: ".detail-link", type: "attr", attr: "href" },
	]);

	let paginationType = $state("url"); // 'url', 'scroll', 'none'
	let paginationSelector = $state(".pagination a");
	let maxPages = $state(10);

	let generatedConfig = $state("");

	function loadSampleHtml() {
		html = SAMPLE_HTML;
		testError = null;
		testResult = null;
	}

	function testSelectorInBrowser() {
		testError = null;
		testResult = null;

		if (!testSelector) {
			testError = "셀렉터를 입력해주세요.";
			return;
		}

		try {
			// HTML을 임시 DOM으로 파싱
			const parser = new DOMParser();
			const doc = parser.parseFromString(html, "text/html");
			const elements = doc.querySelectorAll(testSelector);

			if (elements.length === 0) {
				testResult = { count: 0, message: "매칭되는 요소가 없습니다." };
			} else {
				const samples = Array.from(elements)
					.slice(0, 5)
					.map((el) => ({
						tagName: el.tagName.toLowerCase(),
						textContent: el.textContent.trim().substring(0, 100),
						innerHTML: el.innerHTML.substring(0, 200),
					}));

				testResult = {
					count: elements.length,
					message: `${elements.length}개의 요소가 발견되었습니다.`,
					samples,
				};
			}
		} catch (err) {
			testError = `셀렉터 오류: ${err.message}`;
		}
	}

	function addAttribute() {
		attributes = [
			...attributes,
			{ name: "", selector: "", type: "text", attr: "" },
		];
	}

	function removeAttribute(index) {
		attributes = attributes.filter((_, i) => i !== index);
	}

	function generateConfig() {
		const config = {
			version: "1.0",
			container_selector: containerSelector,
			attributes: Object.fromEntries(
				attributes
					.filter((a) => a.name && a.selector)
					.map((a) => {
						if (a.type === "attr" && a.attr) {
							return [
								a.name,
								{
									selector: a.selector,
									type: "attr",
									attr: a.attr,
								},
							];
						} else {
							return [
								a.name,
								{ selector: a.selector, type: a.type },
							];
						}
					}),
			),
			pagination:
				paginationType === "none"
					? null
					: {
							type: paginationType,
							selector: paginationSelector,
							max_pages: maxPages,
						},
		};

		generatedConfig = JSON.stringify(config, null, 2);
	}

	function copyConfig() {
		if (generatedConfig) {
			navigator.clipboard.writeText(generatedConfig);
			alert("설정이 클립보드에 복사되었습니다.");
		}
	}

	onMount(() => {
		generateConfig();
	});
</script>

<div class="container mx-auto p-4 max-w-7xl">
	<PageHeader title="HTML 분석 도구" subtitle="샘플 HTML을 분석하여 크롤링 설정을 생성합니다" />

	<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
		<!-- 왼쪽: HTML 입력 및 셀렉터 테스트 -->
		<div class="space-y-6">
			<!-- HTML 입력 -->
			<div class="card bg-base-100 shadow">
				<div class="card-body">
					<div
						class="flex flex-wrap justify-between items-center gap-2 mb-2"
					>
						<h2 class="card-title">HTML 입력</h2>
						<button
							class="btn btn-sm btn-ghost"
							onclick={loadSampleHtml}
						>
							샘플 로드
						</button>
					</div>

					<textarea
						bind:value={html}
						class="textarea textarea-bordered w-full font-mono text-xs"
						rows="12"
						placeholder="HTML을 붙여넣으세요..."
					></textarea>

					<div class="text-xs text-gray-500">
						크기: {(html.length / 1024).toFixed(2)} KB
					</div>
				</div>
			</div>

			<!-- 셀렉터 테스트 -->
			<div class="card bg-base-100 shadow">
				<div class="card-body">
					<h2 class="card-title">셀렉터 테스트</h2>

					<div class="form-control">
						<label class="label">
							<span class="label-text">CSS 셀렉터</span>
						</label>
						<div class="join">
							<input
								type="text"
								bind:value={testSelector}
								placeholder=".product-card"
								class="input input-bordered join-item flex-1"
							/>
							<button
								class="btn join-item btn-primary"
								onclick={testSelectorInBrowser}
							>
								테스트
							</button>
						</div>
					</div>

					{#if testError}
						<div class="alert alert-error">
							<span>{testError}</span>
						</div>
					{/if}

					{#if testResult}
						<div class="alert alert-info">
							<div>
								<div class="font-bold">
									{testResult.message}
								</div>
								{#if testResult.samples && testResult.samples.length > 0}
									<div class="text-sm mt-2">
										<div class="font-semibold mb-1">
											샘플 (최대 5개):
										</div>
										{#each testResult.samples as sample, i}
											<div
												class="bg-base-200 p-2 rounded mt-1"
											>
												<div class="font-mono text-xs">
													&lt;{sample.tagName}&gt; {sample.textContent}
												</div>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- 오른쪽: 파싱 설정 빌더 -->
		<div class="space-y-6">
			<!-- 컨테이너 셀렉터 -->
			<div class="card bg-base-100 shadow">
				<div class="card-body">
					<h2 class="card-title">1. 아이템 컨테이너</h2>

					<div class="form-control">
						<label class="label">
							<span class="label-text"
								>각 아이템을 감싸는 요소의 셀렉터</span
							>
						</label>
						<input
							type="text"
							bind:value={containerSelector}
							placeholder=".product-card, .item"
							class="input input-bordered"
							onchange={generateConfig}
						/>
					</div>
				</div>
			</div>

			<!-- 속성 추출 설정 -->
			<div class="card bg-base-100 shadow">
				<div class="card-body">
					<div class="flex justify-between items-center">
						<h2 class="card-title">2. 속성 추출 규칙</h2>
						<button
							class="btn btn-sm btn-ghost"
							onclick={addAttribute}>+ 추가</button
						>
					</div>

					<div class="space-y-3">
						{#each attributes as attr, i}
							<div class="border rounded p-3">
								<div
									class="grid grid-cols-12 gap-2 items-start"
								>
									<div class="col-span-3">
										<label class="label label-text text-xs"
											>필드명</label
										>
										<input
											type="text"
											bind:value={attr.name}
											placeholder="title"
											class="input input-sm input-bordered w-full"
											onchange={generateConfig}
										/>
									</div>
									<div class="col-span-4">
										<label class="label label-text text-xs"
											>셀렉터</label
										>
										<input
											type="text"
											bind:value={attr.selector}
											placeholder=".title"
											class="input input-sm input-bordered w-full"
											onchange={generateConfig}
										/>
									</div>
									<div class="col-span-2">
										<label class="label label-text text-xs"
											>타입</label
										>
										<select
											bind:value={attr.type}
											class="select select-sm select-bordered w-full"
											onchange={generateConfig}
										>
											<option value="text">text</option>
											<option value="attr">attr</option>
										</select>
									</div>
									<div class="col-span-2">
										{#if attr.type === "attr"}
											<label
												class="label label-text text-xs"
												>속성</label
											>
											<input
												type="text"
												bind:value={attr.attr}
												placeholder="href"
												class="input input-sm input-bordered w-full"
												onchange={generateConfig}
											/>
										{/if}
									</div>
									<div class="col-span-1 flex items-end">
										<button
											class="btn btn-sm btn-ghost btn-circle"
											onclick={() => {
												removeAttribute(i);
												generateConfig();
											}}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												class="h-4 w-4"
												fill="none"
												viewBox="0 0 24 24"
												stroke="currentColor"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M6 18L18 6M6 6l12 12"
												/>
											</svg>
										</button>
									</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			</div>

			<!-- 페이지네이션 설정 -->
			<div class="card bg-base-100 shadow">
				<div class="card-body">
					<h2 class="card-title">3. 페이지네이션</h2>

					<div class="form-control">
						<label class="label">
							<span class="label-text">타입</span>
						</label>
						<select
							bind:value={paginationType}
							class="select select-bordered"
							onchange={generateConfig}
						>
							<option value="none">없음 (단일 페이지)</option>
							<option value="url">URL 파라미터 (/?page=N)</option>
							<option value="scroll">무한 스크롤</option>
						</select>
					</div>

					{#if paginationType !== "none"}
						<div class="form-control">
							<label class="label">
								<span class="label-text"
									>다음 페이지 링크 셀렉터</span
								>
							</label>
							<input
								type="text"
								bind:value={paginationSelector}
								placeholder=".pagination a, .next-page"
								class="input input-bordered"
								onchange={generateConfig}
							/>
						</div>

						<div class="form-control">
							<label class="label">
								<span class="label-text">최대 페이지 수</span>
							</label>
							<input
								type="number"
								bind:value={maxPages}
								min="1"
								max="100"
								class="input input-bordered w-full max-w-xs"
								onchange={generateConfig}
							/>
						</div>
					{/if}
				</div>
			</div>

			<!-- 생성된 JSON -->
			<div class="card bg-base-100 shadow">
				<div class="card-body">
					<div
						class="flex flex-wrap justify-between items-center gap-2 mb-2"
					>
						<h2 class="card-title">4. 생성된 설정 (JSON)</h2>
						<button
							class="btn btn-sm btn-ghost"
							onclick={copyConfig}>복사</button
						>
					</div>

					<textarea
						bind:value={generatedConfig}
						class="textarea textarea-bordered w-full font-mono text-xs"
						rows="15"
						readonly
					></textarea>

					<div class="alert alert-info">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							class="stroke-current shrink-0 w-6 h-6"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
							></path>
						</svg>
						<span class="text-sm"
							>이 JSON을 크롤링 대상 등록 시 "파싱 설정" 필드에
							붙여넣으세요.</span
						>
					</div>
				</div>
			</div>
		</div>
	</div>
</div>
