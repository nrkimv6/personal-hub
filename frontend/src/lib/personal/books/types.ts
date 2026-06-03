export type Disposal = 'undecided' | 'keep' | 'sell' | 'scan' | 'discard' | 'review';
export type Recommendation = Disposal;
export type Condition = 'mint' | 'good' | 'fair' | 'poor' | 'damaged' | 'marked';
export type AccessState = 'yes' | 'no' | 'check';
export type SellStatus = 'none' | 'ready' | 'listed' | 'sold' | 'canceled' | 'unsellable';
export type ScanStatus = 'none' | 'ready' | 'in_progress' | 'done' | 'canceled';
export type DiscardStatus = 'none' | 'ready' | 'discarded' | 'canceled';

export interface Highlight {
	id: string;
	bookId?: string;
	page: number;
	quote: string;
	memo?: string | null;
	tags: string[];
	importance: 1 | 2 | 3 | 4 | 5;
	photo?: string | null;
}

export interface Book {
	id: string;
	isbn: string;
	title: string;
	author: string;
	publisher: string;
	publishedYear?: number | null;
	price?: number | null;
	category: string;
	cover?: string | null;
	condition: Condition;
	location: string;
	purchasedWhere?: string | null;
	purchasedUsed?: boolean | null;
	purchasedPrice?: number | null;
	reasonToKeep?: string | null;
	rereadIntent: 1 | 2 | 3 | 4 | 5;
	notes?: string | null;
	library: AccessState;
	millie: AccessState;
	ebook: AccessState;
	usedBuyback: AccessState;
	usedBuybackPrice?: number | null;
	lastCheckedAt?: string | null;
	recommendation: Recommendation;
	disposal: Disposal;
	sellStatus: SellStatus;
	scanStatus: ScanStatus;
	discardStatus: DiscardStatus;
	scanPurpose?: 'guillotine' | 'non_destructive' | null;
	reviewDate?: string | null;
	highlights: Highlight[];
	addedAt?: string;
}

export interface BookListResult {
	items: Book[];
	total: number;
	offset: number;
	limit: number;
}

