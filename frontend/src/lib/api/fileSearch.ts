/**
 * 파일 검색 API 클라이언트
 */
import { request } from './client';
import type {
	BrowseResponse,
	Preset,
	SearchRequest,
	SearchResponse,
	StatusResponse
} from '$lib/types/fileSearch';

const BASE = '/file-search';

export async function search(req: SearchRequest, signal?: AbortSignal): Promise<SearchResponse> {
	return request<SearchResponse>(`${BASE}/search`, {
		method: 'POST',
		body: JSON.stringify(req),
		signal
	});
}

export async function getPresets(): Promise<Preset[]> {
	return request<Preset[]>(`${BASE}/presets`);
}

export async function openFile(filePath: string, lineNumber?: number): Promise<{ ok: boolean }> {
	return request<{ ok: boolean }>(`${BASE}/open`, {
		method: 'POST',
		body: JSON.stringify({ file_path: filePath, line_number: lineNumber ?? null })
	});
}

export async function getStatus(): Promise<StatusResponse> {
	return request<StatusResponse>(`${BASE}/status`);
}

export async function browseDirectory(path: string): Promise<BrowseResponse> {
	const encoded = encodeURIComponent(path);
	return request<BrowseResponse>(`${BASE}/browse?path=${encoded}`);
}
