<script lang="ts">
	import { onMount } from 'svelte';

	let health: any = null;
	let loading = true;
	let error: string | null = null;

	async function loadHealth() {
		loading = true;
		error = null;
		try {
			const res = await fetch('/api/ic/health');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			health = await res.json();
		} catch (err: any) {
			error = err.message;
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		loadHealth();
	});
</script>

<svelte:head>
	<title>이미지 분류 대시보드</title>
</svelte:head>

<div class="max-w-7xl mx-auto">
	<h1 class="text-3xl font-bold text-gray-900 mb-2">이미지 분류 대시보드</h1>
	<p class="text-gray-600 mb-8">로컬 이미지 30만 장 자동 분류 시스템</p>

	{#if loading}
		<div class="bg-white rounded-lg shadow p-8 text-center">
			<div class="animate-spin text-4xl mb-4">⏳</div>
			<p class="text-gray-600">시스템 상태 확인 중...</p>
		</div>
	{:else if error}
		<div class="bg-red-50 border border-red-200 rounded-lg p-6">
			<h3 class="text-red-800 font-semibold mb-2">⚠️ 오류 발생</h3>
			<p class="text-red-600">{error}</p>
			<button
				on:click={loadHealth}
				class="mt-4 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
			>
				다시 시도
			</button>
		</div>
	{:else if health}
		<!-- 시스템 상태 -->
		<div class="bg-white rounded-lg shadow mb-6 p-6">
			<h2 class="text-xl font-semibold text-gray-800 mb-4">시스템 상태</h2>
			<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
				<div class="bg-green-50 rounded-lg p-4">
					<div class="text-green-600 text-sm font-medium mb-1">모듈 상태</div>
					<div class="text-2xl font-bold text-green-700">{health.status.toUpperCase()}</div>
				</div>
				<div class="bg-blue-50 rounded-lg p-4">
					<div class="text-blue-600 text-sm font-medium mb-1">데이터베이스</div>
					<div class="text-2xl font-bold text-blue-700">{health.database.toUpperCase()}</div>
				</div>
				<div class="bg-purple-50 rounded-lg p-4">
					<div class="text-purple-600 text-sm font-medium mb-1">버전</div>
					<div class="text-2xl font-bold text-purple-700">{health.version}</div>
				</div>
				<div class="bg-gray-50 rounded-lg p-4">
					<div class="text-gray-600 text-sm font-medium mb-1">AI 모드</div>
					<div class="text-2xl font-bold text-gray-700">{health.ai_adapters.mode.toUpperCase()}</div>
				</div>
			</div>
		</div>

		<!-- AI 어댑터 -->
		<div class="bg-white rounded-lg shadow mb-6 p-6">
			<h2 class="text-xl font-semibold text-gray-800 mb-4">AI 어댑터</h2>
			<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
				<div class="border rounded-lg p-4">
					<div class="flex items-center justify-between mb-2">
						<h3 class="font-semibold text-gray-700">Claude CLI</h3>
						<span class="px-3 py-1 rounded-full text-sm {health.ai_adapters.claude_cli.available
							? 'bg-green-100 text-green-700'
							: 'bg-red-100 text-red-700'}">
							{health.ai_adapters.claude_cli.available ? '사용 가능' : '사용 불가'}
						</span>
					</div>
					<p class="text-sm text-gray-600">경로: <code class="bg-gray-100 px-2 py-1 rounded">{health.ai_adapters.claude_cli.path}</code></p>
				</div>
				<div class="border rounded-lg p-4">
					<div class="flex items-center justify-between mb-2">
						<h3 class="font-semibold text-gray-700">Gemini CLI</h3>
						<span class="px-3 py-1 rounded-full text-sm {health.ai_adapters.gemini_cli.available
							? 'bg-green-100 text-green-700'
							: 'bg-red-100 text-red-700'}">
							{health.ai_adapters.gemini_cli.available ? '사용 가능' : '사용 불가'}
						</span>
					</div>
					<p class="text-sm text-gray-600">경로: <code class="bg-gray-100 px-2 py-1 rounded">{health.ai_adapters.gemini_cli.path}</code></p>
				</div>
			</div>
		</div>

		<!-- 설정 -->
		<div class="bg-white rounded-lg shadow p-6">
			<h2 class="text-xl font-semibold text-gray-800 mb-4">설정</h2>
			<div class="space-y-3">
				<div class="flex justify-between items-center py-2 border-b">
					<span class="text-gray-700">CLIP 모델</span>
					<code class="text-sm bg-gray-100 px-3 py-1 rounded">{health.settings.clip_model}</code>
				</div>
				<div class="flex justify-between items-center py-2 border-b">
					<span class="text-gray-700">GPU 사용</span>
					<span class="px-3 py-1 rounded {health.settings.clip_gpu ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'}">
						{health.settings.clip_gpu ? 'ON' : 'OFF'}
					</span>
				</div>
				<div class="flex justify-between items-center py-2 border-b">
					<span class="text-gray-700">클러스터 간격</span>
					<span class="text-sm text-gray-600">{health.settings.cluster_gap_minutes}분</span>
				</div>
				<div class="flex justify-between items-center py-2">
					<span class="text-gray-700">스캔 루트 폴더</span>
					<span class="text-sm text-gray-600">
						{#if health.settings.scan_roots.length > 0}
							{health.settings.scan_roots.length}개 설정됨
						{:else}
							<span class="text-amber-600">미설정</span>
						{/if}
					</span>
				</div>
			</div>
		</div>

		<!-- 시작 안내 -->
		<div class="bg-blue-50 border border-blue-200 rounded-lg p-6 mt-6">
			<h3 class="text-blue-800 font-semibold mb-3">🚀 시작하기</h3>
			<ol class="space-y-2 text-blue-700 text-sm">
				<li>1️⃣ <strong>설정</strong>에서 스캔할 폴더를 지정하세요.</li>
				<li>2️⃣ <strong>폴더 매핑</strong>에서 폴더-카테고리 매핑을 진행하세요.</li>
				<li>3️⃣ <strong>중복 이미지</strong>를 정리하세요.</li>
				<li>4️⃣ <strong>유사 분류</strong> 및 <strong>AI 분류</strong>를 실행하세요.</li>
				<li>5️⃣ <strong>검토</strong>에서 최종 확인 후 이동하세요.</li>
			</ol>
		</div>
	{/if}
</div>
