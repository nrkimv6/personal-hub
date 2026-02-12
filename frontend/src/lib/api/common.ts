/**
 * Common API - 프로필, 계정, 업체, 아이템 등 기본 엔티티
 */
import { request, API_BASE } from './client';
import type {
  BrowserProfile,
  BrowserProfileCreate,
  BrowserProfileUpdate,
  ServiceAccount,
  ServiceAccountCreate,
  ServiceAccountUpdate,
  ServiceAccountWithProfile,
  AccountSnipePreset,
  AccountSnipePresetCreate,
  Business,
  BusinessCreate,
  BusinessUpdate,
  BusinessWithItems,
  BizItem,
  BizItemCreate,
  BizItemUpdate,
  BizItemWithSchedules,
  MonitorSchedule,
  MonitorScheduleCreate,
  BulkScheduleCreate,
  NotificationSettings,
  EntitySource,
  EntitySourceCreate,
  EntitySourceUpdate,
  EntitySourceList
} from '../types';

// ============================================================
// BrowserProfile API (브라우저 프로필)
// ============================================================

export const profileApi = {
  // 목록 조회 (서비스 계정 포함)
  list: (includeInactive = false) => {
    const params = new URLSearchParams();
    if (includeInactive) params.append('include_inactive', 'true');
    const query = params.toString();
    return request<BrowserProfile[]>(`/profiles/${query ? `?${query}` : ''}`);
  },

  // 활성 프로필만 조회
  listActive: (options?: RequestInit) => request<BrowserProfile[]>('/profiles/active', options),

  // 단일 조회 (서비스 계정 포함)
  get: (id: number) => request<BrowserProfile>(`/profiles/${id}`),

  // 생성
  create: (data: BrowserProfileCreate) =>
    request<BrowserProfile>('/profiles/', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 수정
  update: (id: number, data: BrowserProfileUpdate) =>
    request<BrowserProfile>(`/profiles/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  // 삭제
  delete: (id: number, removeBrowserData = false) => {
    const params = new URLSearchParams();
    if (removeBrowserData) params.append('remove_browser_data', 'true');
    const query = params.toString();
    return request<null>(`/profiles/${id}${query ? `?${query}` : ''}`, {
      method: 'DELETE'
    });
  },

  // 사용 시간 업데이트
  markUsed: (id: number) =>
    request<BrowserProfile>(`/profiles/${id}/mark-used`, {
      method: 'POST'
    }),

  // 프로필의 서비스 계정 목록
  getAccounts: (profileId: number) =>
    request<ServiceAccount[]>(`/profiles/${profileId}/accounts`),

  // 서비스 계정 추가
  addAccount: (profileId: number, data: ServiceAccountCreate) =>
    request<ServiceAccount>(`/profiles/${profileId}/accounts`, {
      method: 'POST',
      body: JSON.stringify(data)
    })
};

// ============================================================
// ServiceAccount API (서비스 계정)
// ============================================================

export const serviceAccountApi = {
  // 활성 서비스 계정 목록 조회
  listActive: (serviceType?: string, options?: RequestInit) => {
    const params = serviceType ? `?service_type=${serviceType}` : '';
    return request<ServiceAccountWithProfile[]>(`/service-accounts/active${params}`, options);
  },

  // 서비스 계정 수정
  update: (id: number, data: ServiceAccountUpdate) =>
    request<ServiceAccount>(`/service-accounts/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  // 서비스 계정 삭제
  delete: (id: number) =>
    request<null>(`/service-accounts/${id}`, {
      method: 'DELETE'
    }),

  // 로그인 상태 업데이트
  updateLoginStatus: (id: number, isLoggedIn: boolean) =>
    request<ServiceAccount>(`/service-accounts/${id}/login-status?is_logged_in=${isLoggedIn}`, {
      method: 'PUT'
    }),

  // booking_info 업데이트 (네이버 전용)
  updateBookingInfo: (id: number, bookingInfo: Record<string, unknown>) =>
    request<ServiceAccount>(`/service-accounts/${id}/booking-info`, {
      method: 'PUT',
      body: JSON.stringify(bookingInfo)
    }),

  // credentials 업데이트
  updateCredentials: (id: number, credentials: Record<string, unknown>) =>
    request<ServiceAccount>(`/service-accounts/${id}/credentials`, {
      method: 'PUT',
      body: JSON.stringify(credentials)
    }),

  // 브라우저 제어 API
  openBrowser: (id: number) =>
    request<{ message: string; command_id: number }>(`/service-accounts/${id}/browser/open`, {
      method: 'POST'
    }),

  openLoginPage: (id: number) =>
    request<{ message: string; command_id: number }>(`/service-accounts/${id}/browser/login`, {
      method: 'POST'
    }),

  checkLogin: (id: number) =>
    request<{ is_logged_in: boolean; checked_at: string }>(`/service-accounts/${id}/browser/check-login`, {
      method: 'POST'
    }),

  closeBrowser: (id: number) =>
    request<{ message: string }>(`/service-accounts/${id}/browser/close`, {
      method: 'POST'
    }),

  // 스나이핑 프리셋 API
  getPresets: (id: number) =>
    request<AccountSnipePreset[]>(`/service-accounts/${id}/presets`),

  createPreset: (id: number, data: AccountSnipePresetCreate) =>
    request<AccountSnipePreset>(`/service-accounts/${id}/presets`, {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 모든 서비스 계정의 프리셋 (일괄 등록용)
  getAllPresets: () =>
    request<AccountSnipePreset[]>('/service-accounts/presets/all')
};

// ============================================================
// Business API (업체)
// ============================================================

export interface BusinessListParams {
  service_type?: string;
  recent_days?: number;
}

export const businessApi = {
  // 목록 조회
  list: (params?: BusinessListParams) => {
    const searchParams = new URLSearchParams();
    if (params?.service_type) searchParams.append('service_type', params.service_type);
    if (params?.recent_days) searchParams.append('recent_days', String(params.recent_days));
    const query = searchParams.toString();
    return request<Business[]>(`/businesses/${query ? `?${query}` : ''}`);
  },

  // 단일 조회 (아이템 포함)
  get: (id: number) => request<BusinessWithItems>(`/businesses/${id}`),

  // 생성
  create: (data: BusinessCreate) =>
    request<Business>('/businesses/', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 수정
  update: (id: number, data: BusinessUpdate) =>
    request<Business>(`/businesses/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  // 삭제
  delete: (id: number) =>
    request<null>(`/businesses/${id}`, {
      method: 'DELETE'
    }),

  // 업체의 아이템 목록
  getItems: (id: number) => request<BizItem[]>(`/businesses/${id}/items`),

  // URL에서 업체/아이템/일정 자동 생성
  importFromUrl: (data: {
    url: string;
    item_name: string;
    business_name?: string;
    auto_booking_enabled?: boolean;
    time_range?: string;
    max_bookings_per_schedule?: number;
  }) =>
    request<{
      success: boolean;
      message: string;
      business_id?: number;
      item_id?: number;
      schedule_id?: number;
      parsed_info?: Record<string, unknown>;
    }>('/businesses/import-url', {
      method: 'POST',
      body: JSON.stringify(data)
    })
};

// ============================================================
// BizItem API (아이템)
// ============================================================

export const itemApi = {
  // 아이템 생성 (업체 ID 필요)
  create: (businessId: number, data: BizItemCreate) =>
    request<BizItem>(`/businesses/${businessId}/items`, {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 단일 조회 (일정 포함)
  get: (id: number) => request<BizItemWithSchedules>(`/items/${id}`),

  // 수정
  update: (id: number, data: BizItemUpdate) =>
    request<BizItem>(`/items/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  // 삭제
  delete: (id: number) =>
    request<null>(`/items/${id}`, {
      method: 'DELETE'
    }),

  // 아이템의 일정 목록
  getSchedules: (id: number) => request<MonitorSchedule[]>(`/items/${id}/schedules`),

  // 일정 생성
  createSchedule: (itemId: number, data: MonitorScheduleCreate) =>
    request<MonitorSchedule>(`/items/${itemId}/schedules`, {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 일정 일괄 생성
  createBulkSchedules: (itemId: number, data: BulkScheduleCreate) =>
    request<MonitorSchedule[]>(`/items/${itemId}/schedules/bulk`, {
      method: 'POST',
      body: JSON.stringify(data)
    })
};

// ============================================================
// Notification API
// ============================================================

export const notificationApi = {
  getSettings: (): Promise<NotificationSettings> =>
    request<NotificationSettings>('/notification/settings'),

  updateSettings: (settings: NotificationSettings): Promise<NotificationSettings> =>
    request<NotificationSettings>('/notification/settings', {
      method: 'PUT',
      body: JSON.stringify(settings)
    })
};

// ============================================================
// EntitySource API (다중 출처 관리)
// ============================================================

export const entitySourceApi = {
  // 엔티티 출처 목록 조회
  list: (entityType: 'events' | 'popups', entityId: number) =>
    request<EntitySourceList>(`/${entityType}/${entityId}/sources`),

  // 출처 추가
  add: (entityType: 'events' | 'popups', entityId: number, data: EntitySourceCreate) =>
    request<EntitySource>(`/${entityType}/${entityId}/sources`, {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // 출처 제거
  remove: (entityType: 'events' | 'popups', entityId: number, sourceId: number) =>
    request<null>(`/${entityType}/${entityId}/sources/${sourceId}`, {
      method: 'DELETE'
    }),

  // 대표 출처 설정
  setPrimary: (entityType: 'events' | 'popups', entityId: number, sourceId: number) =>
    request<EntitySource>(`/${entityType}/${entityId}/sources/${sourceId}/primary`, {
      method: 'PUT'
    }),

  // 출처 정보 수정
  update: (entityType: 'events' | 'popups', entityId: number, sourceId: number, data: EntitySourceUpdate) =>
    request<EntitySource>(`/${entityType}/${entityId}/sources/${sourceId}`, {
      method: 'PATCH',
      body: JSON.stringify(data)
    })
};

// ============================================================
// Legacy API (하위 호환성) - scheduleApi 의존으로 naver-booking.ts에서 import 필요
// ============================================================
// targetsApi, bulkApi는 naver-booking.ts로 이동
