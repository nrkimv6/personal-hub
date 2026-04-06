<script lang="ts">
  import { onMount } from 'svelte';
  import { Badge, Button } from '$lib/components/ui';
  import { popupMonitorApi, serviceAccountApi } from '$lib/api';
  import type {
    MonitoringMode,
    PopupFallbackStrategy,
    PopupMonitorCheckNowResponse,
    PopupMonitorItem,
    PopupMonitorLatest,
    PopupRequestProfile,
    PopupUrlMonitor,
    PopupUrlMonitorRun,
    ServiceAccountWithProfile
  } from '$lib/types';

  const DEFAULT_POPUP_URL = 'https://pcmap.place.naver.com/popupstore/list';

  interface PopupMonitorFormState {
    name: string;
    url: string;
    request_profile: PopupRequestProfile;
    fallback_strategy: PopupFallbackStrategy;
    proxy_enabled: boolean;
    notify_on_new: boolean;
    min_new_count: number;
    monitoring_mode: MonitoringMode;
    service_account_id: number | null;
    browser_fallback_enabled: boolean;
    is_enabled: boolean;
  }

  const createDefaultForm = (): PopupMonitorFormState => ({
    name: '',
    url: DEFAULT_POPUP_URL,
    request_profile: 'A',
    fallback_strategy: 'reinforce',
    proxy_enabled: false,
    notify_on_new: true,
    min_new_count: 1,
    monitoring_mode: 'anonymous',
    service_account_id: null,
    browser_fallback_enabled: false,
    is_enabled: true
  });

  let monitors: PopupUrlMonitor[] = [];
  let naverAccounts: ServiceAccountWithProfile[] = [];
  let selectedMonitorId: number | null = null;
  let selectedMonitor: PopupUrlMonitor | null = null;

  let formMode: 'create' | 'edit' = 'create';
  let form: PopupMonitorFormState = createDefaultForm();

  let latest: PopupMonitorLatest | null = null;
  let runs: PopupUrlMonitorRun[] = [];
  let latestItems: PopupMonitorItem[] = [];

  let loading = true;
  let listLoading = false;
  let detailLoading = false;
  let saving = false;
  let running = false;
  let toggling = false;
  let deleting = false;
  let error: string | null = null;
  let detailError: string | null = null;
  let notice: string | null = null;

  $: selectedMonitor = monitors.find((monitor) => monitor.id === selectedMonitorId) ?? null;
  $: latestItems = Array.isArray(latest?.snapshot?.items)
    ? (latest?.snapshot?.items as PopupMonitorItem[])
    : [];

  function getErrorMessage(err: unknown): string {
    return err instanceof Error ? err.message : '알 수 없는 오류';
  }

  function formatDateTime(value: string | null | undefined): string {
    if (!value) return '-';
    try {
      return new Date(value).toLocaleString('ko-KR');
    } catch {
      return value;
    }
  }

  function applyMonitorToForm(monitor: PopupUrlMonitor): void {
    form = {
      name: monitor.name || '',
      url: monitor.url,
      request_profile: monitor.request_profile,
      fallback_strategy: monitor.fallback_strategy,
      proxy_enabled: monitor.proxy_enabled,
      notify_on_new: monitor.notify_on_new,
      min_new_count: Math.max(1, monitor.min_new_count || 1),
      monitoring_mode: monitor.monitoring_mode,
      service_account_id: monitor.service_account_id,
      browser_fallback_enabled: monitor.browser_fallback_enabled,
      is_enabled: monitor.is_enabled
    };
  }

  function setCreateMode(): void {
    formMode = 'create';
    form = createDefaultForm();
    notice = null;
  }

  async function loadAccounts(): Promise<void> {
    try {
      naverAccounts = await serviceAccountApi.listActive('naver');
    } catch (err) {
      console.warn('네이버 계정 목록 로드 실패:', err);
      naverAccounts = [];
    }
  }

  async function loadMonitors(preferredId: number | null = null): Promise<void> {
    listLoading = true;
    error = null;
    try {
      monitors = await popupMonitorApi.list();
      if (monitors.length === 0) {
        selectedMonitorId = null;
        latest = null;
        runs = [];
        latestItems = [];
        setCreateMode();
        return;
      }

      const fallbackId = selectedMonitorId ?? monitors[0].id;
      const nextId = preferredId ?? fallbackId;
      const exists = monitors.some((monitor) => monitor.id === nextId);
      selectedMonitorId = exists ? nextId : monitors[0].id;
    } catch (err) {
      error = getErrorMessage(err);
    } finally {
      listLoading = false;
    }
  }

  async function loadDetails(monitorId: number): Promise<void> {
    detailLoading = true;
    detailError = null;
    try {
      const [latestData, runsData] = await Promise.all([
        popupMonitorApi.latest(monitorId),
        popupMonitorApi.runs(monitorId, 50)
      ]);
      latest = latestData;
      runs = runsData;
    } catch (err) {
      detailError = getErrorMessage(err);
      latest = null;
      runs = [];
    } finally {
      detailLoading = false;
    }
  }

  async function selectMonitor(monitor: PopupUrlMonitor): Promise<void> {
    selectedMonitorId = monitor.id;
    formMode = 'edit';
    applyMonitorToForm(monitor);
    await loadDetails(monitor.id);
  }

  async function refreshAll(): Promise<void> {
    const prevId = selectedMonitorId;
    await loadMonitors(prevId);
    if (selectedMonitorId) {
      await loadDetails(selectedMonitorId);
    }
  }

  function buildPayload() {
    const name = form.name.trim();
    return {
      name: name.length > 0 ? name : null,
      url: form.url.trim(),
      request_profile: form.request_profile,
      fallback_strategy: form.fallback_strategy,
      proxy_enabled: form.proxy_enabled,
      notify_on_new: form.notify_on_new,
      min_new_count: Math.max(1, Number(form.min_new_count || 1)),
      monitoring_mode: form.monitoring_mode,
      service_account_id: form.service_account_id,
      browser_fallback_enabled: form.browser_fallback_enabled,
      is_enabled: form.is_enabled
    };
  }

  async function saveMonitor(): Promise<void> {
    if (!form.url.trim()) {
      alert('URL을 입력해주세요.');
      return;
    }

    saving = true;
    notice = null;
    error = null;
    try {
      const payload = buildPayload();
      let saved: PopupUrlMonitor;
      if (formMode === 'edit' && selectedMonitorId) {
        saved = await popupMonitorApi.update(selectedMonitorId, payload);
        notice = `모니터 #${saved.id} 설정을 저장했습니다.`;
      } else {
        saved = await popupMonitorApi.create(payload);
        notice = `모니터 #${saved.id}을(를) 생성했습니다.`;
      }

      await loadMonitors(saved.id);
      if (selectedMonitorId) {
        await loadDetails(selectedMonitorId);
      }
      const current = monitors.find((monitor) => monitor.id === selectedMonitorId);
      if (current) {
        formMode = 'edit';
        applyMonitorToForm(current);
      }
    } catch (err) {
      error = getErrorMessage(err);
    } finally {
      saving = false;
    }
  }

  async function runSelectedNow(monitorId: number | null = selectedMonitorId): Promise<void> {
    if (!monitorId) return;
    running = true;
    notice = null;
    error = null;
    try {
      const result: PopupMonitorCheckNowResponse = await popupMonitorApi.checkNow(monitorId);
      notice = `즉시 실행 완료: status=${result.status}, 신규 ${result.new_count}건`;
      await refreshAll();
    } catch (err) {
      error = getErrorMessage(err);
    } finally {
      running = false;
    }
  }

  async function toggleMonitor(monitor: PopupUrlMonitor): Promise<void> {
    toggling = true;
    notice = null;
    error = null;
    try {
      if (monitor.is_enabled) {
        await popupMonitorApi.disable(monitor.id);
        notice = `모니터 #${monitor.id} 비활성화 완료`;
      } else {
        await popupMonitorApi.enable(monitor.id);
        notice = `모니터 #${monitor.id} 활성화 완료`;
      }
      await refreshAll();
    } catch (err) {
      error = getErrorMessage(err);
    } finally {
      toggling = false;
    }
  }

  async function deleteSelected(): Promise<void> {
    if (!selectedMonitor) return;
    if (!confirm(`선택한 모니터 #${selectedMonitor.id}를 삭제하시겠습니까?`)) return;

    deleting = true;
    notice = null;
    error = null;
    try {
      await popupMonitorApi.delete(selectedMonitor.id);
      notice = `모니터 #${selectedMonitor.id}를 삭제했습니다.`;
      await refreshAll();
    } catch (err) {
      error = getErrorMessage(err);
    } finally {
      deleting = false;
    }
  }

  onMount(async () => {
    loading = true;
    await loadAccounts();
    await loadMonitors();
    if (selectedMonitorId) {
      const current = monitors.find((monitor) => monitor.id === selectedMonitorId);
      if (current) {
        formMode = 'edit';
        applyMonitorToForm(current);
      }
      await loadDetails(selectedMonitorId);
    }
    loading = false;
  });
</script>

<div class="space-y-6">
  <div class="flex flex-wrap gap-2">
    <Button variant="secondary" size="sm" onclick={refreshAll}>
      새로고침
    </Button>
    <Button variant="secondary" size="sm" onclick={setCreateMode}>
      신규 등록 모드
    </Button>
    {#if selectedMonitor}
      <Button variant="secondary" size="sm" onclick={() => runSelectedNow(selectedMonitor.id)} disabled={running}>
        즉시 실행
      </Button>
      <Button variant="secondary" size="sm" onclick={() => toggleMonitor(selectedMonitor)} disabled={toggling}>
        {selectedMonitor.is_enabled ? '비활성화' : '활성화'}
      </Button>
      <button class="btn btn-danger btn-sm" onclick={deleteSelected} disabled={deleting}>삭제</button>
    {/if}
  </div>

  {#if notice}
    <div class="bg-success-light border border-success/20 text-success px-4 py-2 rounded-lg text-sm">
      {notice}
    </div>
  {/if}

  {#if error}
    <div class="bg-error-light border border-red-200 text-error px-4 py-2 rounded-lg text-sm">
      {error}
    </div>
  {/if}

  {#if loading}
    <div class="flex justify-center items-center h-48">
      <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600"></div>
    </div>
  {:else}
    <div class="grid grid-cols-1 xl:grid-cols-5 gap-6">
      <div class="card xl:col-span-2">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-base font-semibold">모니터 목록</h3>
          <span class="text-xs text-muted-foreground">총 {monitors.length}개</span>
        </div>

        {#if listLoading}
          <p class="text-sm text-muted-foreground">목록 갱신 중...</p>
        {:else if monitors.length === 0}
          <p class="text-sm text-muted-foreground">등록된 팝업 모니터가 없습니다.</p>
        {:else}
          <div class="overflow-x-auto">
            <table class="table">
              <thead>
                <tr>
                  <th>상태</th>
                  <th>이름/URL</th>
                  <th>옵션</th>
                </tr>
              </thead>
              <tbody>
                {#each monitors as monitor (monitor.id)}
                  <tr
                    class="cursor-pointer {selectedMonitorId === monitor.id ? 'bg-primary-light' : ''}"
                    onclick={() => selectMonitor(monitor)}
                  >
                    <td>
                      <Badge variant={monitor.is_enabled ? 'success' : 'secondary'}>
                        {monitor.is_enabled ? '활성' : '비활성'}
                      </Badge>
                    </td>
                    <td class="max-w-56">
                      <div class="font-medium text-sm truncate" title={monitor.name || `monitor-${monitor.id}`}>
                        {monitor.name || `monitor-${monitor.id}`}
                      </div>
                      <div class="text-xs text-muted-foreground truncate" title={monitor.url}>
                        {monitor.url}
                      </div>
                      <div class="text-xs text-muted-foreground mt-1">
                        최근 체크: {formatDateTime(monitor.latest_checked_at)}
                      </div>
                    </td>
                    <td class="text-xs">
                      <div class="whitespace-nowrap">프로필: {monitor.request_profile}</div>
                      <div class="whitespace-nowrap">fallback: {monitor.fallback_strategy}</div>
                      <div class="whitespace-nowrap">프록시: {monitor.proxy_enabled ? 'ON' : 'OFF'}</div>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>

      <div class="card xl:col-span-3">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-base font-semibold">
            {formMode === 'edit' ? '모니터 설정 수정' : '모니터 신규 등록'}
          </h3>
          {#if selectedMonitor}
            <button
              class="btn btn-secondary btn-xs"
              onclick={() => {
                formMode = 'edit';
                applyMonitorToForm(selectedMonitor);
              }}
            >
              선택 모니터 불러오기
            </button>
          {/if}
        </div>

        <form class="space-y-4" onsubmit={(e) => { e.preventDefault(); saveMonitor(); }}>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label for="popup-monitor-name" class="block text-sm font-medium text-foreground mb-1">이름</label>
              <input id="popup-monitor-name" class="input" bind:value={form.name} placeholder="예: 네이버 팝업 기본 모니터" />
            </div>
            <div>
              <div class="block text-sm font-medium text-foreground mb-1">상태</div>
              <label class="flex items-center gap-2 mt-2">
                <input id="popup-monitor-enabled" type="checkbox" bind:checked={form.is_enabled} />
                <span class="text-sm text-foreground">모니터 활성화</span>
              </label>
            </div>
          </div>

          <div>
            <label for="popup-monitor-url" class="block text-sm font-medium text-foreground mb-1">팝업 URL</label>
            <input id="popup-monitor-url" class="input" bind:value={form.url} placeholder={DEFAULT_POPUP_URL} />
          </div>

          <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label for="popup-monitor-profile" class="block text-sm font-medium text-foreground mb-1">요청 프로필</label>
              <select id="popup-monitor-profile" class="input" bind:value={form.request_profile}>
                <option value="A">A (안정형)</option>
                <option value="B">B (경량형)</option>
                <option value="C">C (저지문형)</option>
              </select>
            </div>
            <div>
              <label for="popup-monitor-fallback" class="block text-sm font-medium text-foreground mb-1">Fallback 전략</label>
              <select id="popup-monitor-fallback" class="input" bind:value={form.fallback_strategy}>
                <option value="reinforce">reinforce (A→B→C)</option>
                <option value="random_rotate">random_rotate</option>
              </select>
            </div>
            <div>
              <label for="popup-monitor-mode" class="block text-sm font-medium text-foreground mb-1">모니터링 모드</label>
              <select id="popup-monitor-mode" class="input" bind:value={form.monitoring_mode}>
                <option value="anonymous">anonymous</option>
                <option value="legacy">legacy</option>
              </select>
            </div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label for="popup-monitor-account" class="block text-sm font-medium text-foreground mb-1">서비스 계정</label>
              <select
                id="popup-monitor-account"
                class="input"
                value={form.service_account_id ?? ''}
                onchange={(e) => {
                  const value = (e.currentTarget as HTMLSelectElement).value;
                  form.service_account_id = value ? Number(value) : null;
                }}
              >
                <option value="">사용 안 함</option>
                {#each naverAccounts as account (account.id)}
                  <option value={account.id}>
                    {account.identifier || account.profile_name || `계정 #${account.id}`}
                  </option>
                {/each}
              </select>
            </div>
            <div>
              <label for="popup-monitor-min-new" class="block text-sm font-medium text-foreground mb-1">신규 알림 최소 건수</label>
              <input id="popup-monitor-min-new" type="number" min="1" class="input" bind:value={form.min_new_count} />
            </div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label class="flex items-center gap-2">
              <input type="checkbox" bind:checked={form.notify_on_new} />
              <span class="text-sm text-foreground">신규 감지 시 알림 허용</span>
            </label>
            <label class="flex items-center gap-2">
              <input type="checkbox" bind:checked={form.proxy_enabled} />
              <span class="text-sm text-foreground">모니터 단위 프록시 ON</span>
            </label>
            <label class="flex items-center gap-2">
              <input type="checkbox" bind:checked={form.browser_fallback_enabled} />
              <span class="text-sm text-foreground">브라우저 fallback 허용</span>
            </label>
          </div>

          <div class="flex flex-wrap gap-2 pt-2">
            <Button variant="primary" type="submit" disabled={saving}>
              {formMode === 'edit' ? '설정 저장' : '모니터 생성'}
            </Button>
            <Button variant="secondary" type="button" onclick={setCreateMode}>
              입력 초기화
            </Button>
          </div>
        </form>
      </div>
    </div>

    <div class="card">
      <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h3 class="text-base font-semibold">실행 결과 / 최신 리스트 / 이력</h3>
        {#if selectedMonitor}
          <div class="flex items-center gap-2 text-sm">
            <Badge variant={selectedMonitor.is_enabled ? 'success' : 'secondary'}>
              {selectedMonitor.is_enabled ? '활성' : '비활성'}
            </Badge>
            {#if latest?.last_run?.has_new}
              <Badge variant="warning">신규 {latest.last_run.new_count}건</Badge>
            {:else}
              <Badge variant="secondary">신규 없음</Badge>
            {/if}
            {#if latest?.last_run}
              <Badge variant="info">
                {latest.last_run.request_profile || '-'} / {latest.last_run.proxy_url ? 'proxy' : 'direct'}
              </Badge>
            {/if}
          </div>
        {/if}
      </div>

      {#if !selectedMonitor}
        <p class="text-sm text-muted-foreground">목록에서 모니터를 선택하면 최신 결과와 실행 이력을 확인할 수 있습니다.</p>
      {:else if detailLoading}
        <p class="text-sm text-muted-foreground">상세 데이터를 불러오는 중입니다...</p>
      {:else if detailError}
        <div class="bg-error-light border border-red-200 text-error px-4 py-2 rounded-lg text-sm">
          {detailError}
        </div>
      {:else}
        <div class="space-y-6">
          <div>
            <div class="text-sm text-muted-foreground mb-2">
              마지막 체크: {formatDateTime(latest?.latest_checked_at)} / 아이템 {latest?.item_count || 0}건
            </div>
            {#if latestItems.length === 0}
              <p class="text-sm text-muted-foreground">최신 스냅샷 아이템이 없습니다.</p>
            {:else}
              <div class="overflow-x-auto">
                <table class="table">
                  <thead>
                    <tr>
                      <th>제목</th>
                      <th>장소</th>
                      <th>기간</th>
                      <th>상태</th>
                      <th>예약 URL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each latestItems as item (item.item_key)}
                      <tr>
                        <td class="max-w-56">
                          <div class="truncate font-medium" title={item.title}>{item.title}</div>
                          <div class="text-xs text-muted-foreground">{item.popup_id || item.item_key}</div>
                        </td>
                        <td>{item.place_name || '-'}</td>
                        <td class="text-xs">{item.start_date || '-'} ~ {item.end_date || '-'}</td>
                        <td>{item.status || '-'}</td>
                        <td class="max-w-64">
                          {#if item.reservation_url}
                            <a
                              href={item.reservation_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              class="text-primary underline truncate inline-block max-w-64"
                              title={item.reservation_url}
                            >
                              링크 열기
                            </a>
                          {:else}
                            <span class="text-muted-foreground">-</span>
                          {/if}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </div>

          <div>
            <div class="text-sm font-medium mb-2">실행 이력 (최근 {runs.length}건)</div>
            {#if runs.length === 0}
              <p class="text-sm text-muted-foreground">실행 이력이 없습니다.</p>
            {:else}
              <div class="overflow-x-auto">
                <table class="table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>상태</th>
                      <th>신규</th>
                      <th>요청</th>
                      <th>시작</th>
                      <th>종료</th>
                      <th>오류</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each runs as run (run.id)}
                      <tr>
                        <td>#{run.id}</td>
                        <td>
                          <Badge variant={run.status === 'success' ? 'success' : run.status === 'partial' ? 'warning' : 'secondary'}>
                            {run.status}
                          </Badge>
                        </td>
                        <td>{run.new_count}</td>
                        <td class="text-xs">
                          <div>{run.request_profile || '-'}</div>
                          <div class="text-muted-foreground">{run.proxy_url || 'direct'}</div>
                        </td>
                        <td class="text-xs">{formatDateTime(run.started_at)}</td>
                        <td class="text-xs">{formatDateTime(run.finished_at)}</td>
                        <td class="text-xs text-error max-w-64 truncate" title={run.error_message || ''}>
                          {run.error_message || '-'}
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
