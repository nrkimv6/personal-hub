import { request } from './client';

export type TrackingStatus = 'done' | 'overdue' | 'ready' | 'upcoming';

export interface TrackingItem {
	id: number;
	title: string;
	description?: string | null;
	start_at?: string | null;
	due_at?: string | null;
	completed_at?: string | null;
	created_at: string;
	updated_at: string;
	status: TrackingStatus;
}

export interface TrackingItemListResponse {
	items: TrackingItem[];
	total: number;
}

export interface TrackingItemPayload {
	title: string;
	description?: string | null;
	start_at?: string | null;
	due_at?: string | null;
}

export interface TrackingItemListParams {
	status?: TrackingStatus | 'all';
	include_done?: boolean;
}

function buildQuery(params?: TrackingItemListParams): string {
	const qs = new URLSearchParams();
	if (params?.status && params.status !== 'all') qs.set('status', params.status);
	if (params?.include_done !== undefined) qs.set('include_done', String(params.include_done));
	const query = qs.toString();
	return query ? `?${query}` : '';
}

export const trackingApi = {
	list(params?: TrackingItemListParams): Promise<TrackingItemListResponse> {
		return request<TrackingItemListResponse>(`/tracking/items${buildQuery(params)}`);
	},

	create(payload: TrackingItemPayload): Promise<TrackingItem> {
		return request<TrackingItem>('/tracking/items', {
			method: 'POST',
			body: JSON.stringify(payload),
		});
	},

	update(id: number, payload: TrackingItemPayload): Promise<TrackingItem> {
		return request<TrackingItem>(`/tracking/items/${id}`, {
			method: 'PATCH',
			body: JSON.stringify(payload),
		});
	},

	delete(id: number): Promise<void> {
		return request<void>(`/tracking/items/${id}`, { method: 'DELETE' });
	},

	complete(id: number): Promise<TrackingItem> {
		return request<TrackingItem>(`/tracking/items/${id}/complete`, { method: 'POST' });
	},

	reopen(id: number): Promise<TrackingItem> {
		return request<TrackingItem>(`/tracking/items/${id}/reopen`, { method: 'POST' });
	},
};
