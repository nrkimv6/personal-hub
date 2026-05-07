/**
 * Plan Archive organization API.
 */
export interface ArchivePreviewItem {
	source: string;
	dest: string;
	filename: string;
	category: string;
	needs_move: boolean;
}

export interface ArchivePreviewDir {
	archive_dir: string;
	items: ArchivePreviewItem[];
}

export interface ArchivePreviewResult {
	dirs: ArchivePreviewDir[];
	message?: string;
}

export interface ArchiveOrganizeResult {
	results: Array<{
		archive_dir: string;
		moved: Array<{ source: string; dest: string }>;
		skipped: number;
		errors: Array<{ source: string; error: string }>;
		removed_dirs: string[];
	}>;
	message?: string;
}

export interface DuplicateItem {
	file_a: string;
	file_b: string;
	similarity: number;
	reason: 'exact_name' | 'similar_name';
}

export interface DuplicatesResult {
	dirs: Array<{ archive_dir: string; duplicates: DuplicateItem[] }>;
	message?: string;
}

async function devRunnerRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
	const { getAuthToken, fetchWithTimeout } = await import('./client');
	const url = `/api/v1/dev-runner${endpoint}`;
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
		throw new Error(message);
	}
	return response.json();
}

export const archiveApi = {
	/**
	 * archive 폴더 정리 미리보기
	 */
	preview: () => devRunnerRequest<ArchivePreviewResult>('/plans/archive/preview'),

	/**
	 * archive 폴더 정리 실행 (파일 이동 + DB 업데이트)
	 */
	organize: (archive_dir?: string) =>
		devRunnerRequest<ArchiveOrganizeResult>('/plans/archive/organize', {
			method: 'POST',
			body: JSON.stringify(archive_dir ? { archive_dir } : {})
		}),

	/**
	 * 중복 파일 감지
	 */
	duplicates: (similarity?: number) => {
		const q = similarity != null ? `?similarity=${similarity}` : '';
		return devRunnerRequest<DuplicatesResult>(`/plans/archive/duplicates${q}`);
	}
};
