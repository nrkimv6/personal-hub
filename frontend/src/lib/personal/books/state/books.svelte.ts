import { booksApi } from '../api';
import { sampleBooks } from '../sample-data';
import type { Book, Disposal } from '../types';

interface UndoSnapshot {
	message: string;
	prev: Book[];
}

function statusPatch(disposal: Disposal): Pick<Book, 'sellStatus' | 'scanStatus' | 'discardStatus'> {
	return {
		sellStatus: disposal === 'sell' ? 'ready' : 'none',
		scanStatus: disposal === 'scan' ? 'ready' : 'none',
		discardStatus: disposal === 'discard' ? 'ready' : 'none'
	};
}

function isApiId(id: string): boolean {
	return /^\d+$/.test(id);
}

class BooksState {
	books = $state<Book[]>(sampleBooks);
	pendingUndo = $state<UndoSnapshot | null>(null);
	loaded = $state(false);
	loading = $state(false);
	error = $state<string | null>(null);

	getBook(id: string): Book | undefined {
		return this.books.find((book) => book.id === id);
	}

	async load(): Promise<void> {
		if (this.loading) return;
		this.loading = true;
		this.error = null;
		try {
			const result = await booksApi.list({ limit: 100 });
			if (result.items.length > 0) {
				this.books = result.items;
			}
			this.loaded = true;
		} catch (error) {
			this.error = error instanceof Error ? error.message : '도서 API를 불러오지 못했습니다';
		} finally {
			this.loading = false;
		}
	}

	private snap(message: string, prev: Book[]): void {
		this.pendingUndo = { message, prev };
		if (typeof window === 'undefined') return;
		window.setTimeout(() => {
			if (this.pendingUndo?.prev === prev) this.pendingUndo = null;
		}, 4000);
	}

	async updateBook(id: string, patch: Partial<Book>): Promise<void> {
		this.books = this.books.map((book) => (book.id === id ? { ...book, ...patch } : book));
		if (!isApiId(id)) return;
		try {
			const updated = await booksApi.patch(id, patch);
			this.books = this.books.map((book) => (book.id === id ? updated : book));
		} catch (error) {
			this.error = error instanceof Error ? error.message : '도서 수정 실패';
		}
	}

	async setDisposal(id: string, disposal: Disposal, message = '변경됨'): Promise<void> {
		const prev = this.books;
		this.snap(message, prev);
		await this.updateBook(id, { disposal, ...statusPatch(disposal) });
	}

	addBook(book: Book): void {
		this.books = [book, ...this.books];
	}

	undo(): void {
		if (!this.pendingUndo) return;
		this.books = this.pendingUndo.prev;
		this.pendingUndo = null;
	}

	clearUndo(): void {
		this.pendingUndo = null;
	}
}

export const booksState = new BooksState();

