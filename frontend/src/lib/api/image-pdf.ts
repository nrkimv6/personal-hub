import { API_BASE, fetchWithTimeout, getAuthToken, request } from './client';

export interface ImagePdfHealthResponse {
	supported_extensions: string[];
	heic_supported: boolean;
	pillow_version: string;
	max_files: number;
	max_per_file_mb: number;
	max_total_mb: number;
}

export interface ImagePdfConvertOptions {
	bw: boolean;
	white: number;
	black: number;
	quality: number;
	preserveDpi: boolean;
	outputName?: string | null;
}

export interface ImagePdfErrorDetail {
	error: string;
	filename?: string | null;
	detail?: string;
}

export class ImagePdfApiError extends Error {
	constructor(
		message: string,
		public readonly detail?: ImagePdfErrorDetail,
		public readonly status?: number
	) {
		super(message);
		this.name = 'ImagePdfApiError';
	}
}

function authHeaders(): HeadersInit {
	const token = getAuthToken();
	return token ? { Authorization: `Bearer ${token}` } : {};
}

export function parseContentDispositionFilename(value: string | null): string | null {
	if (!value) return null;

	const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
	if (utf8Match?.[1]) {
		try {
			return decodeURIComponent(utf8Match[1]);
		} catch {
			return utf8Match[1];
		}
	}

	const basicMatch = value.match(/filename="?([^";]+)"?/i);
	return basicMatch?.[1] ?? null;
}

function errorMessageFromDetail(detail: ImagePdfErrorDetail | string | undefined): string {
	if (!detail) return 'PDF 변환에 실패했습니다.';
	if (typeof detail === 'string') return detail;

	const suffix = detail.filename ? ` (${detail.filename})` : '';
	switch (detail.error) {
		case 'heic_unsupported':
			return `HEIC/HEIF 변환을 지원하지 않는 환경입니다${suffix}.`;
		case 'unsupported_extension':
			return `지원하지 않는 이미지 형식입니다${suffix}.`;
		case 'empty':
			return `비어 있는 파일입니다${suffix}.`;
		case 'corrupt':
			return `이미지를 열 수 없습니다${suffix}.`;
		case 'file_too_large':
		case 'total_too_large':
		case 'too_many_files':
			return detail.detail || `업로드 제한을 초과했습니다${suffix}.`;
		case 'invalid_threshold':
		case 'validation_error':
			return detail.detail || '옵션 값을 확인하세요.';
		default:
			return detail.detail || `PDF 변환에 실패했습니다${suffix}.`;
	}
}

export function getHealth(): Promise<ImagePdfHealthResponse> {
	return request<ImagePdfHealthResponse>('/image-pdf/health');
}

export async function convertToPdf(
	files: File[],
	opts: ImagePdfConvertOptions
): Promise<{ blob: Blob; filename: string }> {
	const form = new FormData();
	for (const file of files) {
		form.append('files', file);
	}
	form.append('bw', String(opts.bw));
	form.append('white', String(opts.white));
	form.append('black', String(opts.black));
	form.append('quality', String(opts.quality));
	form.append('preserve_dpi', String(opts.preserveDpi));
	if (opts.outputName?.trim()) {
		form.append('output_name', opts.outputName.trim());
	}

	const response = await fetchWithTimeout(`${API_BASE}/image-pdf/convert`, {
		method: 'POST',
		body: form,
		headers: authHeaders(),
		credentials: 'include'
	}, 120000);

	if (!response.ok) {
		let detail: ImagePdfErrorDetail | string | undefined;
		try {
			const body = await response.json();
			detail = body?.detail;
		} catch {
			detail = response.statusText;
		}
		throw new ImagePdfApiError(errorMessageFromDetail(detail), typeof detail === 'object' ? detail : undefined, response.status);
	}

	const blob = await response.blob();
	const filename =
		parseContentDispositionFilename(response.headers.get('content-disposition')) || 'image-pdf.pdf';
	return { blob, filename };
}
