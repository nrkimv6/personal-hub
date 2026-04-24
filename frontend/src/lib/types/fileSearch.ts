/**
 * 파일 검색 모듈 TypeScript 타입 정의
 */

export type SearchMode = 'filename' | 'content' | 'both';
export type MatchSource = 'filename' | 'content' | 'both';

export interface SearchRequest {
	query: string;
	mode: SearchMode;
	regex: boolean;
	case_sensitive: boolean;
	paths: string[];
	extensions: string[];
	excludes: string[];
	preset?: string | null;
	max_results: number;
	context_lines: number;
}

export interface Submatch {
	start: number;
	end: number;
	match: string;
}

export interface ContentMatch {
	line_number: number;
	line_text: string;
	context_before: string[];
	context_after: string[];
	submatches: Submatch[];
}

export interface FileMatch {
	file_path: string;
	file_name: string;
	file_size: number | null;
	modified: string | null;
	matches: ContentMatch[];
	match_source: MatchSource;
}

export interface SearchResponse {
	results: FileMatch[];
	total_count: number;
	search_time_ms: number;
	mode: SearchMode;
	truncated: boolean;
}

export interface StatusResponse {
	everything_ok: boolean;
	everything_message: string;
	ripgrep_ok: boolean;
	ripgrep_path: string | null;
}

export interface DirectoryItem {
	name: string;
	path: string;
}

export interface BrowseResponse {
	current: string;
	parent: string | null;
	directories: DirectoryItem[];
}

export interface Preset {
	id: string;
	name: string;
	icon: string;
	paths: string[];
	extensions: string[];
	excludes: string[];
}

/** 파일 검색 무시 패턴 */
export interface IgnorePattern {
	id: number;
	label: string;
	pattern: string;
	enabled: boolean;
	sort_order: number;
}

/** POST /search 202 응답 — 비동기 검색 수락 */
export interface SearchAcceptedResponse {
	search_id: string;
	status: string;
}

/** GET /search/{search_id} 폴링 응답 */
export interface SearchPollResponse {
	search_id: string;
	/** pending | queued | processing | completed | failed */
	status: string;
	result?: SearchResponse;
	error_message?: string | null;
}

export interface FilePreviewResponse {
	file_path: string;
	file_name: string;
	extension: string;
	size_bytes: number;
	encoding: string;
	content: string;
}
