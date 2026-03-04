<script lang="ts">
  import { onMount } from 'svelte';
  import { profileApi, serviceAccountApi } from '$lib/api';
  import type { BrowserProfile, ServiceAccount, BrowserProfileCreate, ServiceAccountCreate } from '$lib/types';

  let profiles: BrowserProfile[] = [];
  let loading = true;
  let error = '';
  let showCreateModal = false;
  let editingProfile: BrowserProfile | null = null;
  let showAddAccountModal = false;
  let addAccountProfileId: number | null = null;

  // 생성/수정 폼 데이터
  let formData = {
    name: '',
    profile_dir: '',
    description: '',
    is_active: true
  };

  // 서비스 계정 추가 폼 데이터
  let accountFormData: ServiceAccountCreate = {
    service_type: 'naver',
    identifier: ''
  };

  onMount(async () => {
    await loadProfiles();
  });

  async function loadProfiles() {
    try {
      loading = true;
      profiles = await profileApi.list(true);  // include inactive
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
      profile_dir: '',
      description: '',
      is_active: true
    };
    editingProfile = null;
    showCreateModal = true;
  }

  function openEditModal(profile: BrowserProfile) {
    formData = {
      name: profile.name,
      profile_dir: profile.profile_dir,
      description: profile.description || '',
      is_active: profile.is_active
    };
    editingProfile = profile;
    showCreateModal = true;
  }

  function closeModal() {
    showCreateModal = false;
    editingProfile = null;
  }

  async function handleSubmit() {
    try {
      if (!formData.name || !formData.profile_dir) {
        alert('프로필명과 프로필 디렉토리는 필수입니다');
        return;
      }

      if (editingProfile) {
        await profileApi.update(editingProfile.id, {
          name: formData.name,
          description: formData.description || undefined,
          is_active: formData.is_active
        });
      } else {
        await profileApi.create(formData as BrowserProfileCreate);
      }

      await loadProfiles();
      closeModal();
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    }
  }

  async function deleteProfile(id: number, name: string) {
    if (!confirm(`"${name}" 프로필을 삭제하시겠습니까?\n(브라우저 데이터는 유지됩니다)`)) {
      return;
    }

    try {
      await profileApi.delete(id);
      await loadProfiles();
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    }
  }

  async function toggleActive(profile: BrowserProfile) {
    try {
      await profileApi.update(profile.id, { is_active: !profile.is_active });
      await loadProfiles();
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    }
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('ko-KR');
  }

  // 서비스 계정 추가 모달
  function openAddAccountModal(profileId: number) {
    addAccountProfileId = profileId;
    accountFormData = {
      service_type: 'naver',
      identifier: ''
    };
    showAddAccountModal = true;
  }

  function closeAddAccountModal() {
    showAddAccountModal = false;
    addAccountProfileId = null;
  }

  async function handleAddAccount() {
    if (!addAccountProfileId) return;

    try {
      await profileApi.addAccount(addAccountProfileId, accountFormData);
      await loadProfiles();
      closeAddAccountModal();
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    }
  }

  async function deleteServiceAccount(accountId: number, identifier: string | null) {
    if (!confirm(`"${identifier || '(미설정)'}" 서비스 계정을 삭제하시겠습니까?`)) {
      return;
    }

    try {
      await serviceAccountApi.delete(accountId);
      await loadProfiles();
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    }
  }

  // 브라우저 제어 상태
  let browserLoading: { [key: number]: string } = {};

  async function openBrowser(account: ServiceAccount) {
    browserLoading[account.id] = 'open';
    try {
      const result = await serviceAccountApi.openBrowser(account.id);
      alert(`브라우저가 열렸습니다: ${result.message}`);
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  async function openLoginPage(account: ServiceAccount) {
    browserLoading[account.id] = 'login';
    try {
      await serviceAccountApi.openLoginPage(account.id);
      const serviceName = account.service_type === 'naver' ? '네이버' :
                         account.service_type === 'instagram' ? 'Instagram' : '쿠팡';
      alert(`${serviceName} 로그인 페이지가 열렸습니다.\n브라우저에서 로그인 후 "상태 확인" 버튼을 눌러주세요.`);
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  async function checkLoginStatus(account: ServiceAccount) {
    browserLoading[account.id] = 'check';
    try {
      const result = await serviceAccountApi.checkLogin(account.id);
      await loadProfiles();
      alert(result.is_logged_in ? '로그인 확인됨' : '로그인 필요');
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  async function closeBrowser(account: ServiceAccount) {
    browserLoading[account.id] = 'close';
    try {
      const result = await serviceAccountApi.closeBrowser(account.id);
      alert(result.message);
    } catch (e) {
      alert(e instanceof Error ? e.message : '알 수 없는 오류');
    } finally {
      delete browserLoading[account.id];
      browserLoading = browserLoading;
    }
  }

  function getServiceTypeLabel(type: string): string {
    switch (type) {
      case 'naver': return '네이버';
      case 'instagram': return 'Instagram';
      case 'coupang': return '쿠팡';
      default: return type;
    }
  }

  function getServiceTypeColor(type: string): string {
    switch (type) {
      case 'naver': return 'bg-success-light text-success';
      case 'instagram': return 'bg-pink-light text-pink';
      case 'coupang': return 'bg-error-light text-error';
      default: return 'bg-muted text-foreground';
    }
  }
</script>

<div class="max-w-7xl mx-auto">
  <!-- 헤더 -->
  <div class="mb-6 flex items-center justify-between">
    <div>
      <h2 class="text-xl font-bold text-foreground">브라우저 프로필 관리</h2>
      <p class="text-muted-foreground mt-1">브라우저 프로필 및 서비스별 계정 관리</p>
    </div>
    <button
      onclick={openCreateModal}
      class="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors"
    >
      + 프로필 추가
    </button>
  </div>

  {#if loading}
    <div class="text-center py-12">
      <div class="inline-block animate-spin rounded-full h-8 w-8 border-4 border-blue-500 border-t-transparent"></div>
      <p class="mt-2 text-muted-foreground">로딩 중...</p>
    </div>
  {:else if error}
    <div class="bg-error-light border border-red-200 rounded-lg p-4 text-error">
      {error}
    </div>
  {:else if profiles.length === 0}
    <div class="text-center py-12 bg-background rounded-lg">
      <p class="text-muted-foreground">등록된 프로필이 없습니다</p>
      <button
        onclick={openCreateModal}
        class="mt-4 text-primary hover:underline"
      >
        첫 프로필 추가하기
      </button>
    </div>
  {:else}
    <div class="grid gap-4">
      {#each profiles as profile (profile.id)}
        <div class="bg-card border border-border rounded-lg p-5 hover:shadow-md transition-shadow">
          <div class="flex items-start justify-between">
            <div class="flex-1">
              <!-- 프로필 헤더 -->
              <div class="flex items-center gap-3">
                <h3 class="text-lg font-semibold text-foreground">{profile.name}</h3>
                <span class="px-2 py-1 text-xs rounded-full {profile.is_active ? 'bg-success-light text-success' : 'bg-muted text-muted-foreground'}">
                  {profile.is_active ? '활성' : '비활성'}
                </span>
              </div>

              <div class="mt-2 space-y-1 text-sm text-muted-foreground">
                <p>프로필 디렉토리: <code class="bg-muted px-2 py-0.5 rounded">{profile.profile_dir}</code></p>
                {#if profile.description}
                  <p>{profile.description}</p>
                {/if}
                {#if profile.last_used_at}
                  <p>마지막 사용: {formatDate(profile.last_used_at)}</p>
                {/if}
              </div>

              <!-- 서비스 계정 목록 -->
              <div class="mt-4">
                <div class="flex items-center gap-2 mb-2">
                  <span class="text-sm font-medium text-foreground">서비스 계정</span>
                  <button
                    onclick={() => openAddAccountModal(profile.id)}
                    class="px-2 py-0.5 text-xs bg-primary-light text-primary rounded hover:bg-blue-200 transition-colors"
                  >
                    + 추가
                  </button>
                </div>

                {#if profile.service_accounts.length === 0}
                  <p class="text-sm text-muted-foreground">등록된 서비스 계정이 없습니다</p>
                {:else}
                  <div class="space-y-2">
                    {#each profile.service_accounts as account (account.id)}
                      <div class="flex items-center justify-between bg-background rounded-lg p-3">
                        <div class="flex items-center gap-3">
                          <span class="px-2 py-1 text-xs rounded-full {getServiceTypeColor(account.service_type)}">
                            {getServiceTypeLabel(account.service_type)}
                          </span>
                          <span class="text-sm text-foreground">
                            {account.identifier || '(미설정)'}
                          </span>
                          {#if account.is_logged_in}
                            <span class="px-2 py-0.5 text-xs rounded-full bg-primary-light text-primary">
                              로그인됨
                            </span>
                          {/if}
                        </div>

                        <div class="flex items-center gap-2">
                          <!-- 브라우저 제어 버튼 -->
                          <button
                            onclick={() => openBrowser(account)}
                            disabled={!!browserLoading[account.id]}
                            class="px-2 py-1 text-xs bg-slate-100 text-slate-700 rounded hover:bg-slate-200 transition-colors disabled:opacity-50 disabled:cursor-wait"
                            title="브라우저 열기"
                          >
                            {browserLoading[account.id] === 'open' ? '...' : '브라우저'}
                          </button>
                          <button
                            onclick={() => openLoginPage(account)}
                            disabled={!!browserLoading[account.id]}
                            class="px-2 py-1 text-xs bg-success-light text-success rounded hover:bg-green-200 transition-colors disabled:opacity-50 disabled:cursor-wait"
                            title="로그인 페이지 열기"
                          >
                            {browserLoading[account.id] === 'login' ? '...' : '로그인'}
                          </button>
                          <button
                            onclick={() => checkLoginStatus(account)}
                            disabled={!!browserLoading[account.id]}
                            class="px-2 py-1 text-xs bg-primary-light text-primary rounded hover:bg-blue-200 transition-colors disabled:opacity-50 disabled:cursor-wait"
                            title="로그인 상태 확인"
                          >
                            {browserLoading[account.id] === 'check' ? '...' : '확인'}
                          </button>
                          <button
                            onclick={() => closeBrowser(account)}
                            disabled={!!browserLoading[account.id]}
                            class="px-2 py-1 text-xs bg-warning-light text-warning rounded hover:bg-orange-200 transition-colors disabled:opacity-50 disabled:cursor-wait"
                            title="브라우저 세션 종료"
                          >
                            {browserLoading[account.id] === 'close' ? '...' : '종료'}
                          </button>
                          <button
                            onclick={() => deleteServiceAccount(account.id, account.identifier)}
                            class="px-2 py-1 text-xs bg-error-light text-error rounded hover:bg-error-light transition-colors"
                          >
                            삭제
                          </button>
                        </div>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            </div>

            <!-- 프로필 액션 버튼 -->
            <div class="flex items-start gap-2 ml-4">
              <button
                onclick={() => toggleActive(profile)}
                class="px-3 py-1.5 text-sm border border-border rounded hover:bg-muted transition-colors"
                title={profile.is_active ? '비활성화' : '활성화'}
              >
                {profile.is_active ? '비활성화' : '활성화'}
              </button>
              <button
                onclick={() => openEditModal(profile)}
                class="px-3 py-1.5 text-sm bg-muted text-foreground rounded hover:bg-secondary transition-colors"
              >
                수정
              </button>
              <button
                onclick={() => deleteProfile(profile.id, profile.name)}
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

<!-- 프로필 생성/수정 모달 -->
{#if showCreateModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onclick={closeModal} role="dialog" aria-modal="true">
    <div class="bg-white rounded-lg p-6 max-w-md w-full mx-4" onclick={(e) => e.stopPropagation()} role="document">
      <h2 class="text-xl font-bold mb-4">
        {editingProfile ? '프로필 수정' : '프로필 추가'}
      </h2>

      <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-foreground mb-1" for="profile-name">
            프로필명 <span class="text-error">*</span>
          </label>
          <input
            id="profile-name"
            type="text"
            bind:value={formData.name}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
            placeholder="예: 메인 프로필"
            required
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-foreground mb-1" for="profile-dir">
            프로필 디렉토리 <span class="text-error">*</span>
          </label>
          <input
            id="profile-dir"
            type="text"
            bind:value={formData.profile_dir}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
            placeholder="예: profile_1"
            required
            disabled={!!editingProfile}
          />
          <p class="text-xs text-muted-foreground mt-1">영문, 숫자, 언더스코어만 사용 (수정 불가)</p>
        </div>

        <div>
          <label class="block text-sm font-medium text-foreground mb-1" for="description">
            설명 (선택)
          </label>
          <textarea
            id="description"
            bind:value={formData.description}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
            rows="2"
            placeholder="예: 서브 계정용 프로필"
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
            {editingProfile ? '수정' : '추가'}
          </button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- 서비스 계정 추가 모달 -->
{#if showAddAccountModal}
  <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onclick={closeAddAccountModal} onkeydown={(e) => e.key === 'Escape' && closeAddAccountModal()} role="dialog" aria-modal="true" tabindex="-1">
    <div class="bg-white rounded-lg p-6 max-w-md w-full mx-4" onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()} role="document">
      <h2 class="text-xl font-bold mb-4">서비스 계정 추가</h2>

      <form onsubmit={(e) => { e.preventDefault(); handleAddAccount(); }} class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-foreground mb-1" for="service-type">
            서비스 타입 <span class="text-error">*</span>
          </label>
          <select
            id="service-type"
            bind:value={accountFormData.service_type}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
          >
            <option value="naver">네이버</option>
            <option value="instagram">Instagram</option>
            <option value="coupang">쿠팡</option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-foreground mb-1" for="identifier">
            이메일/사용자명 (선택)
          </label>
          <input
            id="identifier"
            type="text"
            bind:value={accountFormData.identifier}
            class="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-ring focus:border-transparent"
            placeholder="예: user@naver.com"
          />
        </div>

        <div class="flex gap-2 pt-4">
          <button
            type="button"
            onclick={closeAddAccountModal}
            class="flex-1 px-4 py-2 border border-border rounded-lg hover:bg-muted transition-colors"
          >
            취소
          </button>
          <button
            type="submit"
            class="flex-1 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors"
          >
            추가
          </button>
        </div>
      </form>
    </div>
  </div>
{/if}
