<script lang="ts">
  import { onMount } from 'svelte';
  import { coupangTravelApi, type CoupangTarget, type CoupangSchedule } from '$lib/api/coupangTravel';
  import { serviceAccountApi, type ServiceAccountWithProfile } from '$lib/api/common';

  // ── 상태 ────────────────────────────────────────────────────
  let targets = $state<CoupangTarget[]>([]);
  let schedules = $state<CoupangSchedule[]>([]);
  let accounts = $state<ServiceAccountWithProfile[]>([]);
  let loading = $state(false);
  let error = $state('');
  let successMsg = $state('');

  // 상품 등록 폼
  let newUrl = $state('');
  let newVendorItemPackageId = $state('');
  let newName = $state('');
  let submittingTarget = $state(false);

  // 일정 추가 폼
  let selectedTargetId = $state<number | null>(null);
  let newDate = $state('');
  let selectedAccountId = $state<number | null>(null);
  let submittingSchedule = $state(false);

  // ── 초기 로드 ───────────────────────────────────────────────
  onMount(async () => {
    await loadAll();
  });

  async function loadAll() {
    loading = true;
    error = '';
    try {
      const [t, s, a] = await Promise.all([
        coupangTravelApi.listTargets(),
        coupangTravelApi.listSchedules(),
        serviceAccountApi.listActive('coupang')
      ]);
      targets = t;
      schedules = s;
      accounts = a;
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : '데이터 로드 실패';
    } finally {
      loading = false;
    }
  }

  // ── 상품 등록 ────────────────────────────────────────────────
  async function submitTarget() {
    if (!newUrl.trim() || !newVendorItemPackageId.trim() || !newName.trim()) {
      error = 'URL, vendor_item_package_id, 이름을 모두 입력해주세요.';
      return;
    }
    submittingTarget = true;
    error = '';
    try {
      await coupangTravelApi.createTarget({
        url: newUrl.trim(),
        vendor_item_package_id: newVendorItemPackageId.trim(),
        name: newName.trim()
      });
      newUrl = '';
      newVendorItemPackageId = '';
      newName = '';
      successMsg = '상품이 등록되었습니다.';
      targets = await coupangTravelApi.listTargets();
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : '등록 실패';
    } finally {
      submittingTarget = false;
    }
  }

  // ── 상품 삭제 ────────────────────────────────────────────────
  async function deleteTarget(id: number) {
    if (!confirm('이 상품과 관련 일정을 모두 삭제합니까?')) return;
    try {
      await coupangTravelApi.deleteTarget(id);
      targets = targets.filter(t => t.id !== id);
      schedules = schedules.filter(s => {
        const tgt = targets.find(t => t.id === id);
        return !tgt || s.product_id !== tgt.product_id;
      });
      schedules = await coupangTravelApi.listSchedules();
      successMsg = '상품이 삭제되었습니다.';
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : '삭제 실패';
    }
  }

  // ── 일정 추가 ────────────────────────────────────────────────
  async function submitSchedule() {
    if (!selectedTargetId || !newDate || !selectedAccountId) {
      error = '상품, 날짜, 계정을 모두 선택해주세요.';
      return;
    }
    submittingSchedule = true;
    error = '';
    try {
      const res = await coupangTravelApi.createSchedules({
        biz_item_id: selectedTargetId,
        dates: [newDate],
        service_account_id: selectedAccountId
      });
      successMsg = `일정 ${res.created}건이 추가되었습니다.`;
      newDate = '';
      schedules = await coupangTravelApi.listSchedules();
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : '일정 추가 실패';
    } finally {
      submittingSchedule = false;
    }
  }

  // ── 일정 삭제 ────────────────────────────────────────────────
  async function deleteSchedule(id: number) {
    try {
      await coupangTravelApi.deleteSchedule(id);
      schedules = schedules.filter(s => s.id !== id);
      successMsg = '일정이 삭제되었습니다.';
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : '일정 삭제 실패';
    }
  }

  function clearMessages() {
    error = '';
    successMsg = '';
  }
</script>

<div class="space-y-8">
  <h1 class="text-2xl font-bold">쿠팡 여행상품 모니터링</h1>

  <!-- 알림 -->
  {#if error}
    <div class="rounded bg-red-100 px-4 py-3 text-red-800" role="alert">
      {error}
      <button class="ml-2 text-sm underline" onclick={clearMessages}>닫기</button>
    </div>
  {/if}
  {#if successMsg}
    <div class="rounded bg-green-100 px-4 py-3 text-green-800" role="status">
      {successMsg}
      <button class="ml-2 text-sm underline" onclick={clearMessages}>닫기</button>
    </div>
  {/if}

  <!-- ── 상품 등록 폼 ── -->
  <section class="rounded border bg-white p-4 shadow-sm">
    <h2 class="mb-4 text-lg font-semibold">상품 등록</h2>
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <div>
        <label class="mb-1 block text-sm font-medium text-gray-700" for="url">상품 URL</label>
        <input
          id="url"
          type="text"
          placeholder="https://trip.coupang.com/tp/products/..."
          bind:value={newUrl}
          class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>
      <div>
        <label class="mb-1 block text-sm font-medium text-gray-700" for="vpid">vendor_item_package_id</label>
        <input
          id="vpid"
          type="text"
          placeholder="패키지 ID"
          bind:value={newVendorItemPackageId}
          class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>
      <div>
        <label class="mb-1 block text-sm font-medium text-gray-700" for="name">이름</label>
        <input
          id="name"
          type="text"
          placeholder="상품 이름"
          bind:value={newName}
          class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>
    </div>
    <button
      class="mt-3 rounded bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-50"
      onclick={submitTarget}
      disabled={submittingTarget}
    >
      {submittingTarget ? '등록 중...' : '상품 등록'}
    </button>
  </section>

  <!-- ── 상품 목록 ── -->
  <section class="rounded border bg-white p-4 shadow-sm">
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-semibold">등록된 상품 ({targets.length})</h2>
      <button
        class="rounded border px-3 py-1 text-sm text-gray-600 hover:bg-gray-100"
        onclick={loadAll}
        disabled={loading}
      >
        새로고침
      </button>
    </div>
    {#if loading}
      <p class="text-sm text-gray-500">로딩 중...</p>
    {:else if targets.length === 0}
      <p class="text-sm text-gray-500">등록된 상품이 없습니다.</p>
    {:else}
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b text-left text-gray-600">
              <th class="py-2 pr-4">이름</th>
              <th class="py-2 pr-4">product_id</th>
              <th class="py-2">관리</th>
            </tr>
          </thead>
          <tbody>
            {#each targets as target (target.id)}
              <tr class="border-b hover:bg-gray-50">
                <td class="py-2 pr-4 font-medium">{target.name}</td>
                <td class="py-2 pr-4 font-mono text-gray-500">{target.product_id}</td>
                <td class="py-2">
                  <button
                    class="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                    onclick={() => deleteTarget(target.id)}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <!-- ── 일정 추가 폼 ── -->
  <section class="rounded border bg-white p-4 shadow-sm">
    <h2 class="mb-4 text-lg font-semibold">일정 추가</h2>
    <div class="grid gap-3 sm:grid-cols-3">
      <div>
        <label class="mb-1 block text-sm font-medium text-gray-700" for="target-select">상품 선택</label>
        <select
          id="target-select"
          bind:value={selectedTargetId}
          class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        >
          <option value={null}>-- 상품 선택 --</option>
          {#each targets as t (t.id)}
            <option value={t.id}>{t.name} ({t.product_id})</option>
          {/each}
        </select>
      </div>
      <div>
        <label class="mb-1 block text-sm font-medium text-gray-700" for="date-input">날짜</label>
        <input
          id="date-input"
          type="date"
          bind:value={newDate}
          class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>
      <div>
        <label class="mb-1 block text-sm font-medium text-gray-700" for="account-select">쿠팡 계정</label>
        <select
          id="account-select"
          bind:value={selectedAccountId}
          class="w-full rounded border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        >
          <option value={null}>-- 계정 선택 --</option>
          {#each accounts as a (a.id)}
            <option value={a.id}>{a.profile?.name ?? `계정 #${a.id}`}</option>
          {/each}
        </select>
      </div>
    </div>
    <button
      class="mt-3 rounded bg-orange-500 px-4 py-2 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-50"
      onclick={submitSchedule}
      disabled={submittingSchedule}
    >
      {submittingSchedule ? '추가 중...' : '일정 추가'}
    </button>
  </section>

  <!-- ── 일정 목록 (대시보드) ── -->
  <section class="rounded border bg-white p-4 shadow-sm">
    <h2 class="mb-3 text-lg font-semibold">모니터링 일정 ({schedules.length})</h2>
    {#if schedules.length === 0}
      <p class="text-sm text-gray-500">등록된 일정이 없습니다.</p>
    {:else}
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b text-left text-gray-600">
              <th class="py-2 pr-4">상품명</th>
              <th class="py-2 pr-4">날짜</th>
              <th class="py-2 pr-4">상태</th>
              <th class="py-2">관리</th>
            </tr>
          </thead>
          <tbody>
            {#each schedules as s (s.id)}
              <tr class="border-b hover:bg-gray-50">
                <td class="py-2 pr-4 font-medium">{s.item_name ?? s.business_name ?? '-'}</td>
                <td class="py-2 pr-4">{s.date}</td>
                <td class="py-2 pr-4">
                  <span class={s.is_enabled ? 'text-green-600' : 'text-gray-400'}>
                    {s.is_enabled ? '활성' : '비활성'}
                  </span>
                </td>
                <td class="py-2">
                  <button
                    class="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                    onclick={() => deleteSchedule(s.id)}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
</div>
