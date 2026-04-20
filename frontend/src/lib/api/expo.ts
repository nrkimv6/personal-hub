import type {
  ExpoCollectionStatusResponse,
  ExpoExportPayload,
  ExpoExportRecordResponse,
  ExpoPipelineStatusResponse,
  ExpoPublishedStatusResponse,
} from '$lib/types';

import { request } from './client';

const BASE = '/expo';

export const expoApi = {
  getPipelineStatus(slug: string) {
    return request<ExpoPipelineStatusResponse>(`${BASE}/${slug}/pipeline-status`);
  },

  getCollectionStatus(slug: string) {
    return request<ExpoCollectionStatusResponse>(`${BASE}/${slug}/collection-status`);
  },

  getPublishedStatus(slug: string) {
    return request<ExpoPublishedStatusResponse>(`${BASE}/${slug}/published-status`);
  },

  recordExport(slug: string, payload: ExpoExportPayload) {
    return request<ExpoExportRecordResponse>(`${BASE}/${slug}/exports/record`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
};
