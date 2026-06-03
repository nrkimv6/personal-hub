import { request } from '$lib/api/client';
import type { Book, BookListResult, Highlight } from './types';

interface ApiHighlight {
	id: number;
	book_id: number;
	page: number;
	quote: string;
	memo?: string | null;
	tags: string[];
	importance: 1 | 2 | 3 | 4 | 5;
	photo?: string | null;
}

interface ApiBook {
	id: number;
	isbn: string;
	title: string;
	author: string;
	publisher: string;
	published_year?: number | null;
	price?: number | null;
	category: string;
	cover_url?: string | null;
	condition: Book['condition'];
	location: string;
	purchased_where?: string | null;
	purchased_used?: boolean | null;
	purchased_price?: number | null;
	reason?: string | null;
	reread_intent: Book['rereadIntent'];
	notes?: string | null;
	accessibility_library: Book['library'];
	accessibility_millie: Book['millie'];
	accessibility_ebook: Book['ebook'];
	accessibility_used_buyback: Book['usedBuyback'];
	used_buyback_price?: number | null;
	last_checked_at?: string | null;
	recommendation: Book['recommendation'];
	disposal: Book['disposal'];
	sell_status: Book['sellStatus'];
	scan_status: Book['scanStatus'];
	discard_status: Book['discardStatus'];
	scan_purpose?: Book['scanPurpose'];
	review_date?: string | null;
	highlights: ApiHighlight[];
	created_at: string;
}

interface ApiBookList {
	items: ApiBook[];
	total: number;
	offset: number;
	limit: number;
}

function toBook(book: ApiBook): Book {
	return {
		id: String(book.id),
		isbn: book.isbn,
		title: book.title,
		author: book.author,
		publisher: book.publisher,
		publishedYear: book.published_year,
		price: book.price,
		category: book.category,
		cover: book.cover_url,
		condition: book.condition,
		location: book.location,
		purchasedWhere: book.purchased_where,
		purchasedUsed: book.purchased_used,
		purchasedPrice: book.purchased_price,
		reasonToKeep: book.reason,
		rereadIntent: book.reread_intent,
		notes: book.notes,
		library: book.accessibility_library,
		millie: book.accessibility_millie,
		ebook: book.accessibility_ebook,
		usedBuyback: book.accessibility_used_buyback,
		usedBuybackPrice: book.used_buyback_price,
		lastCheckedAt: book.last_checked_at,
		recommendation: book.recommendation,
		disposal: book.disposal,
		sellStatus: book.sell_status,
		scanStatus: book.scan_status,
		discardStatus: book.discard_status,
		scanPurpose: book.scan_purpose,
		reviewDate: book.review_date,
		highlights: book.highlights.map(toHighlight),
		addedAt: book.created_at?.slice(0, 10)
	};
}

function toHighlight(highlight: ApiHighlight): Highlight {
	return {
		id: String(highlight.id),
		bookId: String(highlight.book_id),
		page: highlight.page,
		quote: highlight.quote,
		memo: highlight.memo,
		tags: highlight.tags,
		importance: highlight.importance,
		photo: highlight.photo
	};
}

function toApiPatch(patch: Partial<Book>): Record<string, unknown> {
	const out: Record<string, unknown> = {};
	if (patch.location !== undefined) out.location = patch.location;
	if (patch.reasonToKeep !== undefined) out.reason = patch.reasonToKeep;
	if (patch.disposal !== undefined) out.disposal = patch.disposal;
	if (patch.reviewDate !== undefined) out.review_date = patch.reviewDate;
	if (patch.scanPurpose !== undefined) out.scan_purpose = patch.scanPurpose;
	return out;
}

export const booksApi = {
	async list(params: { offset?: number; limit?: number; disposal?: string; search?: string } = {}): Promise<BookListResult> {
		const query = new URLSearchParams();
		query.set('offset', String(params.offset ?? 0));
		query.set('limit', String(params.limit ?? 100));
		if (params.disposal && params.disposal !== 'all') query.set('disposal', params.disposal);
		if (params.search) query.set('search', params.search);
		const result = await request<ApiBookList>(`/books?${query.toString()}`);
		return {
			items: result.items.map(toBook),
			total: result.total,
			offset: result.offset,
			limit: result.limit
		};
	},
	async patch(id: string, patch: Partial<Book>): Promise<Book> {
		const result = await request<ApiBook>(`/books/${id}`, {
			method: 'PATCH',
			body: JSON.stringify(toApiPatch(patch))
		});
		return toBook(result);
	}
};

