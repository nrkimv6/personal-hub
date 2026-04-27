/**
 * 파일 검색 API 클라이언트
 */
import { request } from './client';
import type {
	BrowseResponse,
	FilePreviewResponse,
	FrequentSearchComboItem,
	IgnorePattern,
	Preset,
	SearchAcceptedResponse,
	SearchHistoryItem,
	SearchPollResponse,
	SearchRequest,
	SearchResponse,
	SearchSuggestionItem,
	StatusResponse
} from '$lib/types/fileSearch';

const BASE = '/file-search';

/**
 * 파일 검색 요청 (비동기, 202 반환).
 * 반환된 search_id로 pollSearchResult()를 호출하여 결과를 폴링.
 */
export async function search(
	req: SearchRequest,
	signal?: AbortSignal
): Promise<SearchAcceptedResponse> {
	return request<SearchAcceptedResponse>(`${BASE}/search`, {
		method: 'POST',
		body: JSON.stringify(req),
		signal
	});
}

/**
 * 검색 결과 폴링.
 * status가 completed/failed가 될 때까지 200ms 간격으로 호출.
 */
export async function pollSearchResult(searchId: string): Promise<SearchPollResponse> {
	return request<SearchPollResponse>(`${BASE}/search/${searchId}`);
}

export async function getHistory(limit = 20): Promise<SearchHistoryItem[]> {
	return request<SearchHistoryItem[]>(`${BASE}/history?limit=${limit}`);
}

export async function getSuggestions(limit = 10): Promise<SearchSuggestionItem[]> {
	return request<SearchSuggestionItem[]>(`${BASE}/suggestions?limit=${limit}`);
}

export async function getFrequentCombos(limit = 10): Promise<FrequentSearchComboItem[]> {
	return request<FrequentSearchComboItem[]>(`${BASE}/frequent-combos?limit=${limit}`);
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

export async function getFilePreview(path: string): Promise<FilePreviewResponse> {
	const encoded = encodeURIComponent(path);
	return request<FilePreviewResponse>(`${BASE}/preview?path=${encoded}`);
}

// ── 무시 패턴 CRUD ────────────────────────────────────────────────────

export async function getIgnorePatterns(): Promise<IgnorePattern[]> {
	return request<IgnorePattern[]>(`${BASE}/ignore-patterns`);
}

export async function addIgnorePattern(label: string, pattern: string): Promise<IgnorePattern> {
	return request<IgnorePattern>(`${BASE}/ignore-patterns`, {
		method: 'POST',
		body: JSON.stringify({ label, pattern })
	});
}

export async function toggleIgnorePattern(id: number, enabled: boolean): Promise<IgnorePattern> {
	return request<IgnorePattern>(`${BASE}/ignore-patterns/${id}`, {
		method: 'PATCH',
		body: JSON.stringify({ enabled })
	});
}

export async function deleteIgnorePattern(id: number): Promise<void> {
	await request<void>(`${BASE}/ignore-patterns/${id}`, { method: 'DELETE' });
}
