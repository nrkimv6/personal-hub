<script lang="ts">
  import { onMount } from 'svelte';

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

  let accounts: Account[] = [];
  let loading = true;
  let error = '';
  let showCreateModal = false;
  let editingAccount: Account | null = null;

  // 생성/수정 폼 데이터
  let formData = {
    name: '',
    email: '',
    profile_dir: '',
    description: '',
    is_active: true
  };

  onMount(async () => {
    await loadAccounts();
  });

  async function loadAccounts() {
    try {
      loading = true;
      const res = await fetch('/api/v1/accounts/');
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

      const res = await fetch(url, {
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
      const res = await fetch(`/api/v1/accounts/${id}`, {
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
      const res = await fetch(`/api/v1/accounts/${account.id}`, {
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

  async function openBrowser(account: Account) {
    browserLoading[account.id] = 'open';
    try {
      const res = await fetch(`/api/v1/accounts/${account.id}/browser/open`, {
        method: 'POST'
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || '브라우저 열기 실패');
      }
      const result = await res.json();
      alert(`브라우저가 열렸습니다: ${result.message}`);
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  async function openNaverLogin(account: Account) {
    browserLoading[account.id] = 'login';
    try {
      const res = await fetch(`/api/v1/accounts/${account.id}/browser/naver-login`, {
        method: 'POST'
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || '네이버 로그인 페이지 열기 실패');
      }
      alert('네이버 로그인 페이지가 열렸습니다.\n브라우저에서 로그인 후 "상태 확인" 버튼을 눌러주세요.');
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  async function checkLoginStatus(account: Account) {
    browserLoading[account.id] = 'check';
    try {
      const res = await fetch(`/api/v1/accounts/${account.id}/browser/check-login`, {
        method: 'POST'
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || '상태 확인 실패');
      }
      const result = await res.json();
      await loadAccounts();
      alert(result.is_logged_in ? '로그인 확인됨' : '로그인 필요');
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  async function closeBrowser(account: Account) {
    browserLoading[account.id] = 'close';
    try {
      const res = await fetch(`/api/v1/accounts/${account.id}/browser/close`, {
        method: 'POST'
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || '브라우저 종료 실패');
      }
      const result = await res.json();
      alert(result.message);
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }
</script>

<div class="max-w-7xl mx-auto">
  <!-- 헤더 -->
  <div class="mb-6 flex items-center justify-between">
    <div>
      <h2 class="text-xl font-bold text-gray-900">계정 관리</h2>
      <p class="text-gray-600 mt-1">네이버 계정별 브라우저 프로필 관리</p>
    </div>
    <button
      onclick={openCreateModal}
      class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
    >
      + 계정 추가
    </button>
  </div>

  {#if loading}
    <div class="text-center py-12">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent"></div>
      <p class="mt-2 text-gray-600">로딩 중...</p>
    </div>
  {:else if error}
    <div class="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
      {error}
    </div>
  {:else if accounts.length === 0}
    <div class="text-center py-12 bg-gray-50 rounded-lg">
      <p class="text-gray-500">등록된 계정이 없습니다</p>
      <button
        onclick={openCreateModal}
        class="mt-4 text-blue-600 hover:underline"
      >
        첫 계정 추가하기
      </button>
    </div>
  {:else}
    <div class="grid gap-4">
      {#each accounts as account (account.id)}
        <div class="bg-white border border-gray-200 rounded-lg p-5 hover:shadow-md transition-shadow">
          <div class="flex items-start justify-between">
            <div class="flex-1">
              <div class="flex items-center gap-3">
                <h3 class="text-lg font-semibold text-gray-900">{account.name}</h3>
                <span class="px-2 py-1 text-xs rounded-full {account.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}">
                  {account.is_active ? '활성' : '비활성'}
                </span>
                {#if account.is_logged_in}
                  <span class="px-2 py-1 text-xs rounded-full bg-blue-100 text-blue-700">
                    로그인됨
                  </span>
                {/if}
              </div>

              <div class="mt-2 space-y-1 text-sm text-gray-600">
                {#if account.email}
                  <p>{account.email}</p>
                {/if}
                <p>프로필: <code class="bg-gray-100 px-2 py-0.5 rounded">{account.profile_dir}</code></p>
                {#if account.description}
                  <p>{account.description}</p>
                {/if}
                {#if account.last_used_at}
                  <p>마지막 사용: {formatDate(account.last_used_at)}</p>
                {/if}
              </div>

              <!-- 브라우저 제어 버튼 -->
              <div class="mt-3 flex flex-wrap gap-2">
                <button
                  onclick={() => openBrowser(account)}
                  disabled={!!browserLoading[account.id]}
                  class="px-3 py-1.5 text-sm bg-slate-100 text-slate-700 rounded hover:bg-slate-200 transition-colors disabled:opacity-50 disabled:cursor-wait"
                  title="브라우저 열기"
                >
                  {browserLoading[account.id] === 'open' ? '...' : '브라우저'}
                </button>
                <button
                  onclick={() => openNaverLogin(account)}
                  disabled={!!browserLoading[account.id]}
                  class="px-3 py-1.5 text-sm bg-green-100 text-green-700 rounded hover:bg-green-200 transition-colors disabled:opacity-50 disabled:cursor-wait"
                  title="네이버 로그인 페이지 열기"
                >
                  {browserLoading[account.id] === 'login' ? '...' : '네이버 로그인'}
                </button>
                <button
                  onclick={() => checkLoginStatus(account)}
                  disabled={!!browserLoading[account.id]}
                  class="px-3 py-1.5 text-sm bg-blue-100 text-blue-700 rounded hover:bg-blue-200 transition-colors disabled:opacity-50 disabled:cursor-wait"
                  title="로그인 상태 확인"
                >
                  {browserLoading[account.id] === 'check' ? '...' : '상태 확인'}
                </button>
                <button
                  onclick={() => closeBrowser(account)}
                  disabled={!!browserLoading[account.id]}
                  class="px-3 py-1.5 text-sm bg-orange-100 text-orange-700 rounded hover:bg-orange-200 transition-colors disabled:opacity-50 disabled:cursor-wait"
                  title="브라우저 세션 종료"
                >
                  {browserLoading[account.id] === 'close' ? '...' : '세션 종료'}
                </button>
              </div>
            </div>

            <div class="flex items-start gap-2">
              <button
                onclick={() => toggleActive(account)}
                class="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 transition-colors"
                title={account.is_active ? '비활성화' : '활성화'}
              >
                {account.is_active ? '비활성화' : '활성화'}
              </button>
              <button
                onclick={() => openEditModal(account)}
                class="px-3 py-1.5 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200 transition-colors"
              >
                수정
              </button>
              <button
                onclick={() => deleteAccount(account.id, account.name)}
                class="px-3 py-1.5 text-sm bg-red-50 text-red-600 rounded hover:bg-red-100 transition-colors"
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

<!-- 생성/수정 모달 -->
{#if showCreateModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onclick={closeModal} role="dialog" aria-modal="true">
    <div class="bg-white rounded-lg p-6 max-w-md w-full mx-4" onclick={(e) => e.stopPropagation()} role="document">
      <h2 class="text-xl font-bold mb-4">
        {editingAccount ? '계정 수정' : '계정 추가'}
      </h2>

      <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1" for="account-name">
            계정명 <span class="text-red-500">*</span>
          </label>
          <input
            id="account-name"
            type="text"
            bind:value={formData.name}
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="예: 메인계정"
            required
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1" for="profile-dir">
            프로필 디렉토리 <span class="text-red-500">*</span>
          </label>
          <input
            id="profile-dir"
            type="text"
            bind:value={formData.profile_dir}
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="예: account_1"
            required
            disabled={!!editingAccount}
          />
          <p class="text-xs text-gray-500 mt-1">영문, 숫자, 언더스코어만 사용 (수정 불가)</p>
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1" for="email">
            이메일 (선택)
          </label>
          <input
            id="email"
            type="email"
            bind:value={formData.email}
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            placeholder="예: user@naver.com"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1" for="description">
            설명 (선택)
          </label>
          <textarea
            id="description"
            bind:value={formData.description}
            class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            rows="2"
            placeholder="예: 서브 계정"
          ></textarea>
        </div>

        <div class="flex items-center gap-2">
          <input
            type="checkbox"
            id="is_active"
            bind:checked={formData.is_active}
            class="w-4 h-4 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
          />
          <label for="is_active" class="text-sm text-gray-700">활성화</label>
        </div>

        <div class="flex gap-2 pt-4">
          <button
            type="button"
            onclick={closeModal}
            class="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            취소
          </button>
          <button
            type="submit"
            class="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            {editingAccount ? '수정' : '추가'}
          </button>
        </div>
      </form>
    </div>
  </div>
{/if}
