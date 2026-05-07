/**
 * Shared request helper for Plan Records API modules.
 */
import { getAuthToken, fetchWithTimeout } from './client';

export class PlanRecordsRequestError extends Error {
	status: number;
	detail: unknown;

	constructor(message: string, status: number, detail: unknown) {
		super(message);
		this.name = 'PlanRecordsRequestError';
		this.status = status;
		this.detail = detail;
	}
}

export async function planRecordsRequest<T>(
	endpoint: string,
	options: RequestInit = {}
): Promise<T> {
	const url = `/api/v1/plans${endpoint}`;

	const token = getAuthToken();
	const headers: HeadersInit = {
		'Content-Type': 'application/json',
		...(token ? { Authorization: `Bearer ${token}` } : {}),
		...options.headers
	};

	const response = await fetchWithTimeout(url, { ...options, headers, credentials: 'include' });

	if (!response.ok) {
		const error = await response.json().catch(() => ({ detail: response.statusText }));
		const detail = error.detail;
		const message = typeof detail === 'string' ? detail : detail?.message || '요청 실패';
		throw new PlanRecordsRequestError(message, response.status, detail);
	}

	if (response.status === 204) {
		return null as T;
	}

	return response.json();
}
