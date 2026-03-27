<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import PageHeader from '$lib/components/layout/PageHeader.svelte';
  import { fetchWithTimeout } from '$lib/api/client';
  import { 
    Circle, ChevronUp, ChevronDown, RefreshCw, AlertTriangle, 
    Lock, Mail, Folder, MessageSquare, Clock, Globe, X, 
    Pause, Play, Check 
  } from 'lucide-svelte';

  interface Account {
    id: number;
    name: string;
    email: string | null;
    profile_dir: string;
    is_active: boolean;
    is_logged_in: boolean;
    last_used_at: string | null;
    description: string | null;
    created_at: string;
    updated_at: string;
  }

  interface BrowserStatus {
    available: boolean;
    error: string | null;
    recovery_attempts: number;
    permanently_failed: boolean;
    last_heartbeat: string | null;
  }

  interface BrowserCommand {
    id: number;
    command_type: string;
    service_account_id: number;
    status: string;
    request_data: any;
    result_data: any;
    error_message: string | null;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
  }

  let accounts: Account[] = [];
  let loading = true;
  let error = '';
  let showCreateModal = false;
  let editingAccount: Account | null = null;

  // 워커 브라우저 상태
  let browserStatus: BrowserStatus | null = null;

  // 브라우저 명령 이력
  let browserCommands: BrowserCommand[] = [];
  let commandsLoading = false;
  let showCommands = false;

  // 자동 새로고침
  let refreshInterval: ReturnType<typeof setInterval>;

  // 생성/수정 폼 데이터
  let formData = {
    name: '',
    email: '',
    profile_dir: '',
    description: '',
    is_active: true
  };

  onMount(async () => {
    const results = await Promise.allSettled([
      loadAccounts(),
      loadBrowserStatus()
    ]);
    // 실패한 항목 경고 표시
    const failedCount = results.filter(r => r.status === 'rejected').length;
    if (failedCount > 0) {
      console.warn(`[accounts] ${failedCount}개 로드 실패 - 일부 데이터 없음`);
    }
    // 10초마다 브라우저 상태 및 명령 이력 새로고침
    refreshInterval = setInterval(async () => {
      await loadBrowserStatus();
      if (showCommands) {
        await loadBrowserCommands();
      }
    }, 10000);
  });

  onDestroy(() => {
    if (refreshInterval) {
      clearInterval(refreshInterval);
    }
  });

  async function loadBrowserStatus() {
    try {
      const res = await fetchWithTimeout('/api/v1/worker/browser-status');
      if (res.ok) {
        browserStatus = await res.json();
      }
    } catch (e) {
      console.error('브라우저 상태 로드 실패:', e);
    }
  }

  async function loadBrowserCommands() {
    try {
      commandsLoading = true;
      const res = await fetchWithTimeout('/api/v1/accounts/browser/commands?limit=20');
      if (res.ok) {
        const data = await res.json();
        browserCommands = data.commands;
      }
    } catch (e) {
      console.error('브라우저 명령 이력 로드 실패:', e);
    } finally {
      commandsLoading = false;
    }
  }

  function toggleCommands() {
    showCommands = !showCommands;
    if (showCommands && browserCommands.length === 0) {
      loadBrowserCommands();
    }
  }

  async function loadAccounts() {
    try {
      loading = true;
      const res = await fetchWithTimeout('/api/v1/accounts/');
      if (!res.ok) throw new Error('계정 목록을 불러올 수 없습니다');
      accounts = await res.json();
      error = '';
    } catch (e) {
      error = e instanceof Error ? e.message : '알 수 없는 오류';
    } finally {
      loading = false;
    }
  }

  function openCreateModal() {
    formData = {
      name: '',
      email: '',
      profile_dir: '',
      description: '',
      is_active: true
    };
    editingAccount = null;
    showCreateModal = true;
  }

  function openEditModal(account: Account) {
    formData = {
      name: account.name,
      email: account.email || '',
      profile_dir: account.profile_dir,
      description: account.description || '',
      is_active: account.is_active
    };
    editingAccount = account;
    showCreateModal = true;
  }

  function closeModal() {
    showCreateModal = false;
    editingAccount = null;
  }

  async function handleSubmit() {
    try {
      if (!formData.name || !formData.profile_dir) {
        alert('계정명과 프로필 디렉토리는 필수입니다');
        return;
      }

      const url = editingAccount
        ? `/api/v1/accounts/${editingAccount.id}`
        : '/api/v1/accounts/';

      const method = editingAccount ? 'PUT' : 'POST';

      const res = await fetchWithTimeout(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || '저장 실패');
      }

      await loadAccounts();
      closeModal();
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    }
  }

  async function deleteAccount(id: number, name: string) {
    if (!confirm(`"${name}" 계정을 삭제하시겠습니까?\n(프로필 디렉토리는 유지됩니다)`)) {
      return;
    }

    try {
      const res = await fetchWithTimeout(`/api/v1/accounts/${id}`, {
        method: 'DELETE'
      });

      if (!res.ok) throw new Error('삭제 실패');
      await loadAccounts();
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    }
  }

  async function toggleActive(account: Account) {
    try {
      const res = await fetchWithTimeout(`/api/v1/accounts/${account.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !account.is_active })
      });

      if (!res.ok) throw new Error('상태 변경 실패');
      await loadAccounts();
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    }
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('ko-KR');
  }

  // 브라우저 제어 상태
  let browserLoading: { [key: number]: string } = {};

  // 명령 전송 후 알림 메시지
  let commandMessage = '';
  let commandMessageType: 'success' | 'error' = 'success';
  let commandMessageTimeout: ReturnType<typeof setTimeout>;

  function showCommandMessage(message: string, type: 'success' | 'error' = 'success') {
    commandMessage = message;
    commandMessageType = type;
    if (commandMessageTimeout) clearTimeout(commandMessageTimeout);
    commandMessageTimeout = setTimeout(() => {
      commandMessage = '';
    }, 5000);
  }

  async function openBrowser(account: Account) {
    browserLoading[account.id] = 'open';
    try {
      const res = await fetchWithTimeout(`/api/v1/accounts/${account.id}/browser/open`, {
        method: 'POST'
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || '브라우저 열기 실패');
      }
      const result = await res.json();
      showCommandMessage(result.message, 'success');
      // 명령 이력 새로고침
      if (showCommands) await loadBrowserCommands();
    } catch (e) {
      showCommandMessage(e instanceof Error ? e.message : '알 수 없는 오류', 'error');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  async function openNaverLogin(account: Account) {
    browserLoading[account.id] = 'login';
    try {
      const res = await fetchWithTimeout(`/api/v1/accounts/${account.id}/browser/naver-login`, {
        method: 'POST'
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || '네이버 로그인 페이지 열기 실패');
      }
      const result = await res.json();
      showCommandMessage(result.message, 'success');
      if (showCommands) await loadBrowserCommands();
    } catch (e) {
      showCommandMessage(e instanceof Error ? e.message : '알 수 없는 오류', 'error');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  async function checkLoginStatus(account: Account) {
    browserLoading[account.id] = 'check';
    try {
      const res = await fetchWithTimeout(`/api/v1/accounts/${account.id}/browser/check-login`, {
        method: 'POST'
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || '상태 확인 실패');
      }
      const result = await res.json();
      showCommandMessage(result.message, 'success');
      if (showCommands) await loadBrowserCommands();
    } catch (e) {
      showCommandMessage(e instanceof Error ? e.message : '알 수 없는 오류', 'error');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  async function closeBrowser(account: Account) {
    browserLoading[account.id] = 'close';
    try {
      const res = await fetchWithTimeout(`/api/v1/accounts/${account.id}/browser/close`, {
        method: 'POST'
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || '브라우저 종료 실패');
      }
      const result = await res.json();
      showCommandMessage(result.message, 'success');
      if (showCommands) await loadBrowserCommands();
    } catch (e) {
      showCommandMessage(e instanceof Error ? e.message : '알 수 없는 오류', 'error');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  function getCommandTypeLabel(type: string): string {
    const labels: { [key: string]: string } = {
      'open_browser': '브라우저 열기',
      'naver_login': '네이버 로그인',
      'check_login': '로그인 확인',
      'close_browser': '브라우저 종료'
    };
    return labels[type] || type;
  }

  function getStatusLabel(status: string): { text: string; class: string } {
    const statusMap: { [key: string]: { text: string; class: string } } = {
      'pending': { text: '대기', class: 'bg-warning-light text-warning-foreground' },
      'processing': { text: '처리 중', class: 'bg-primary-light text-primary' },
      'completed': { text: '완료', class: 'bg-success-light text-success' },
      'failed': { text: '실패', class: 'bg-error-light text-error' }
    };
    return statusMap[status] || { text: status, class: 'bg-muted text-foreground' };
  }

  function getAccountName(accountId: number): string {
    const account = accounts.find(a => a.id === accountId);
    return account?.name || `ID:${accountId}`;
  }
</script>

<div class="p-6">
  <div class="max-w-7xl mx-auto">
    <!-- 헤더 -->
    <PageHeader title="계정 관리" subtitle="네이버 계정별 브라우저 프로필 관리">
      <button
        onclick={openCreateModal}
        class="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors"
      >
        + 계정 추가
      </button>
    </PageHeader>

    <!-- 워커 브라우저 상태 -->
    {#if browserStatus}
      <div class="mb-4 p-3 rounded-lg border {browserStatus.available
        ? 'bg-success-light border-green-200'
        : browserStatus.permanently_failed
          ? 'bg-error-light border-red-200'
          : 'bg-warning-light border-yellow-200'}">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="flex items-center">
              {#if browserStatus.available}
                <Circle class="w-4 h-4 fill-success text-success" />
              {:else if browserStatus.permanently_failed}
                <Circle class="w-4 h-4 fill-error text-error" />
              {:else}
                <Circle class="w-4 h-4 fill-warning text-warning" />
              {/if}
            </span>
            <span class="font-medium">
              브라우저 서비스:
              {browserStatus.available
                ? '사용 가능'
                : browserStatus.permanently_failed
                  ? '복구 포기 상태'
                  : `복구 시도 중 (${browserStatus.recovery_attempts}/3)`}
            </span>
            {#if browserStatus.error}
              <span class="text-sm text-muted-foreground">- {browserStatus.error}</span>
            {/if}
          </div>
          <button
            onclick={toggleCommands}
            class="px-3 py-1 text-sm bg-card border border-border rounded hover:bg-muted transition-colors flex items-center gap-1"
          >
            {#if showCommands}
              <ChevronUp class="w-4 h-4" /> 명령 이력 닫기
            {:else}
              <ChevronDown class="w-4 h-4" /> 명령 이력 보기
            {/if}
          </button>
        </div>
      </div>
    {/if}

    <!-- 명령 전송 알림 -->
    {#if commandMessage}
      <div class="mb-4 p-3 rounded-lg {commandMessageType === 'success'
        ? 'bg-primary-light border border-blue-200 text-primary'
        : 'bg-error-light border border-red-200 text-error'}">
        {commandMessage}
      </div>
    {/if}

    <!-- 브라우저 명령 이력 -->
    {#if showCommands}
      <div class="mb-6 bg-card border border-border rounded-lg overflow-hidden">
        <div class="p-3 bg-background border-b border-border flex items-center justify-between">
          <h3 class="font-medium text-foreground">브라우저 명령 이력</h3>
          <button
            onclick={loadBrowserCommands}
            disabled={commandsLoading}
            class="px-2 py-1 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50 flex items-center gap-1"
          >
            {#if commandsLoading}
              로딩...
            {:else}
              <RefreshCw class="w-3 h-3" /> 새로고침
            {/if}
          </button>
        </div>
        {#if browserCommands.length === 0}
          <div class="p-4 text-center text-muted-foreground">
            {commandsLoading ? '로딩 중...' : '명령 이력이 없습니다'}
          </div>
        {:else}
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="bg-background text-muted-foreground">
                <tr>
                  <th class="px-3 py-2 text-left">ID</th>
                  <th class="px-3 py-2 text-left">명령</th>
                  <th class="px-3 py-2 text-left">계정</th>
                  <th class="px-3 py-2 text-left">상태</th>
                  <th class="px-3 py-2 text-left">생성 시간</th>
                  <th class="px-3 py-2 text-left">완료 시간</th>
                  <th class="px-3 py-2 text-left">결과/오류</th>
                </tr>
              </thead>
              <tbody>
                {#each browserCommands as cmd (cmd.id)}
                  {@const statusInfo = getStatusLabel(cmd.status)}
                  <tr class="border-t border-border hover:bg-muted">
                    <td class="px-3 py-2 text-muted-foreground">{cmd.id}</td>
                    <td class="px-3 py-2">{getCommandTypeLabel(cmd.command_type)}</td>
                    <td class="px-3 py-2">{getAccountName(cmd.service_account_id)}</td>
                    <td class="px-3 py-2">
                      <span class="px-2 py-0.5 text-xs rounded-full {statusInfo.class}">
                        {statusInfo.text}
                      </span>
                    </td>
                    <td class="px-3 py-2 text-muted-foreground">{formatDate(cmd.created_at)}</td>
                    <td class="px-3 py-2 text-muted-foreground">{formatDate(cmd.completed_at)}</td>
                    <td class="px-3 py-2 text-sm">
                      {#if cmd.error_message}
                        <span class="text-error">{cmd.error_message}</span>
                      {:else if cmd.result_data?.message}
                        <span class="text-success">{cmd.result_data.message}</span>
                      {:else}
                        -
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    {/if}

    {#if loading}
      <div class="text-center py-12">
        <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent"></div>
        <p class="mt-2 text-muted-foreground">로딩 중...</p>
      </div>
    {:else if error}
      <div class="bg-error-light border border-red-200 rounded-lg p-4 text-error flex items-center gap-2">
        <AlertTriangle class="w-5 h-5" /> {error}
      </div>
    {:else if accounts.length === 0}
      <div class="text-center py-12 bg-background rounded-lg">
        <p class="text-muted-foreground">등록된 계정이 없습니다</p>
        <button
          onclick={openCreateModal}
          class="mt-4 text-primary hover:underline"
        >
          첫 계정 추가하기
        </button>
      </div>
    {:else}
      <div class="grid gap-4">
        {#each accounts as account (account.id)}
          <div class="bg-card border border-border rounded-lg p-5 hover:shadow-md transition-shadow">
            <div class="flex items-start justify-between">
              <div class="flex-1">
                <div class="flex items-center gap-3">
                  <h3 class="text-lg font-semibold text-foreground">{account.name}</h3>
                  <span class="px-2 py-1 text-xs rounded-full {account.is_active ? 'bg-success-light text-success' : 'bg-muted text-muted-foreground'}">
                    {account.is_active ? '활성' : '비활성'}
                  </span>
                  {#if account.is_logged_in}
                    <span class="px-2 py-1 text-xs rounded-full bg-primary-light text-primary flex items-center gap-1">
                      <Lock class="w-3 h-3" /> 로그인됨
                    </span>
                  {/if}
                </div>

                <div class="mt-2 space-y-1 text-sm text-muted-foreground">
                  {#if account.email}
                    <p class="flex items-center gap-1.5"><Mail class="w-4 h-4" /> {account.email}</p>
                  {/if}
                  <p class="flex items-center gap-1.5"><Folder class="w-4 h-4" /> 프로필: <code class="bg-muted px-2 py-0.5 rounded">{account.profile_dir}</code></p>
                  {#if account.description}
                    <p class="flex items-center gap-1.5"><MessageSquare class="w-4 h-4" /> {account.description}</p>
                  {/if}
                  {#if account.last_used_at}
                    <p class="flex items-center gap-1.5"><Clock class="w-4 h-4" /> 마지막 사용: {formatDate(account.last_used_at)}</p>
                  {/if}
                </div>

                <!-- 브라우저 제어 버튼 -->
                <div class="mt-3 flex flex-wrap gap-2">
                  <button
                    onclick={() => openBrowser(account)}
                    disabled={!!browserLoading[account.id]}
                    class="px-3 py-1.5 text-sm bg-slate-100 text-slate-700 rounded hover:bg-slate-200 transition-colors disabled:opacity-50 disabled:cursor-wait flex items-center gap-1"
                    title="브라우저 열기"
                  >
                    {#if browserLoading[account.id] === 'open'}
                      <RefreshCw class="w-4 h-4 animate-spin" />
                    {:else}
                      <Globe class="w-4 h-4" /> 브라우저
                    {/if}
                  </button>
                  <button
                    onclick={() => openNaverLogin(account)}
                    disabled={!!browserLoading[account.id]}
                    class="px-3 py-1.5 text-sm bg-success-light text-success rounded hover:bg-green-200 transition-colors disabled:opacity-50 disabled:cursor-wait flex items-center gap-1"
                    title="네이버 로그인 페이지 열기"
                  >
                    {#if browserLoading[account.id] === 'login'}
                      <RefreshCw class="w-4 h-4 animate-spin" />
                    {:else}
                      <Lock class="w-4 h-4" /> 네이버 로그인
                    {/if}
                  </button>
                  <button
                    onclick={() => checkLoginStatus(account)}
                    disabled={!!browserLoading[account.id]}
                    class="px-3 py-1.5 text-sm bg-primary-light text-primary rounded hover:bg-blue-200 transition-colors disabled:opacity-50 disabled:cursor-wait flex items-center gap-1"
                    title="로그인 상태 확인"
                  >
                    {#if browserLoading[account.id] === 'check'}
                      <RefreshCw class="w-4 h-4 animate-spin" />
                    {:else}
                      <RefreshCw class="w-4 h-4" /> 상태 확인
                    {/if}
                  </button>
                  <button
                    onclick={() => closeBrowser(account)}
                    disabled={!!browserLoading[account.id]}
                    class="px-3 py-1.5 text-sm bg-warning-light text-warning rounded hover:bg-orange-200 transition-colors disabled:opacity-50 disabled:cursor-wait flex items-center gap-1"
                    title="브라우저 세션 종료"
                  >
                    {#if browserLoading[account.id] === 'close'}
                      <RefreshCw class="w-4 h-4 animate-spin" />
                    {:else}
                      <X class="w-4 h-4" /> 세션 종료
                    {/if}
                  </button>
                </div>
              </div>

              <div class="flex items-start gap-2">
                <button
                  onclick={() => toggleActive(account)}
                  class="p-2 border border-border rounded hover:bg-muted transition-colors"
                  title={account.is_active ? '비활성화' : '활성화'}
                >
                  {#if account.is_active}
                    <Pause class="w-4 h-4" />
                  {:else}
                    <Play class="w-4 h-4" />
                  {/if}
                </button>
                <button
                  onclick={() => openEditModal(account)}
                  class="px-3 py-1.5 text-sm bg-muted text-foreground rounded hover:bg-secondary transition-colors"
                >
                  수정
                </button>
                <button
                  onclick={() => deleteAccount(account.id, account.name)}
                  class="px-3 py-1.5 text-sm bg-error-light text-error rounded hover:bg-error-light transition-colors"
                >
                  삭제
                </button>
              </div>
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

<!-- 생성/수정 모달 -->
{#if showCreateModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onclick={closeModal} role="presentation">
    <div class="bg-white rounded-lg p-6 max-w-md w-full mx-4" role="presentation" onclick={(e) => e.stopPropagation()}>
      <h2 class="text-xl font-bold mb-4">
        {editingAccount ? '계정 수정' : '계정 추가'}
      </h2>

      <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} class="space-y-4">
        <div>
          <label for="form_name" class="block text-sm font-medium text-foreground mb-1">
            계정명 <span class="text-error">*</span>
          </label>
          <input
            id="form_name"
            type="text"
            bind:value={formData.name}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
            placeholder="예: 메인계정"
            required
          />
        </div>

        <div>
          <label for="form_profile_dir" class="block text-sm font-medium text-foreground mb-1">
            프로필 디렉토리 <span class="text-error">*</span>
          </label>
          <input
            id="form_profile_dir"
            type="text"
            bind:value={formData.profile_dir}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
            placeholder="예: account_1"
            required
            disabled={!!editingAccount}
          />
          <p class="text-xs text-muted-foreground mt-1">영문, 숫자, 언더스코어만 사용 (수정 불가)</p>
        </div>

        <div>
          <label for="form_email" class="block text-sm font-medium text-foreground mb-1">
            이메일 (선택)
          </label>
          <input
            id="form_email"
            type="email"
            bind:value={formData.email}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
            placeholder="예: user@naver.com"
          />
        </div>

        <div>
          <label for="form_description" class="block text-sm font-medium text-foreground mb-1">
            설명 (선택)
          </label>
          <textarea
            id="form_description"
            bind:value={formData.description}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
            rows="2"
            placeholder="예: 서브 계정"
          ></textarea>
        </div>

        <div class="flex items-center gap-2">
          <input
            type="checkbox"
            id="is_active"
            bind:checked={formData.is_active}
            class="w-4 h-4 text-primary rounded focus:ring-2 focus:ring-ring"
          />
          <label for="is_active" class="text-sm text-foreground">활성화</label>
        </div>

        <div class="flex gap-2 pt-4">
          <button
            type="button"
            onclick={closeModal}
            class="flex-1 px-4 py-2 border border-border rounded-lg hover:bg-muted transition-colors"
          >
            취소
          </button>
          <button
            type="submit"
            class="flex-1 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors"
          >
            {editingAccount ? '수정' : '추가'}
          </button>
        </div>
      </form>
    </div>
  </div>
{/if}
