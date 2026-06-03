export type Disposal = 'undecided' | 'keep' | 'sell' | 'scan' | 'discard' | 'review';
export type Recommendation = Disposal;
export type Condition = 'mint' | 'good' | 'fair' | 'poor' | 'damaged' | 'marked';
export type AccessState = 'yes' | 'no' | 'check';
export type SellStatus = 'none' | 'ready' | 'listed' | 'sold' | 'canceled' | 'unsellable';
export type ScanStatus = 'none' | 'ready' | 'in_progress' | 'done' | 'canceled';
export type DiscardStatus = 'none' | 'ready' | 'discarded' | 'canceled';
export type BuybackGrade = '최상' | '상' | '중';
export type BuybackAvailability = 'yes' | 'no' | 'check' | 'error';

export interface BuybackQuote {
	id?: string | null;
	provider: string;
	grade: BuybackGrade;
	price?: number | null;
	currency: string;
	availability: BuybackAvailability;
	rawStatus: string;
	message?: string | null;
	checkedAt?: string | null;
}

export interface BuybackRecommendation {
	grade?: BuybackGrade | null;
	price?: number | null;
	action: 'sell' | 'user_review' | 'no_buyback' | 'unknown';
	message: string;
}

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
	buybackQuotes?: BuybackQuote[];
	buybackRecommendation?: BuybackRecommendation | null;
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

export interface BuybackRefreshResult {
	book: Book;
	quotes: BuybackQuote[];
	availability: BuybackAvailability;
	message?: string | null;
}

