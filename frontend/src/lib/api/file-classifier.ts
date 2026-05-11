import { fetchWithTimeout } from './client';

const BASE = '/api/fc';

export const FILE_CLASSIFIER_TIMEOUT_MS = {
	read: 10_000,
	command: 30_000,
	longCommand: 60_000
} as const;

export function fileClassifierFetch(
	endpoint: string,
	options: RequestInit = {},
	timeout: number = FILE_CLASSIFIER_TIMEOUT_MS.read
): Promise<Response> {
	const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
	return fetchWithTimeout(`${BASE}${path}`, { ...options, credentials: 'include' }, timeout);
}
