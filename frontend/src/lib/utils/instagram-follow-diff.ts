export interface FollowUser {
	id: string;
	link: string;
}

export interface DiffResult {
	notFollowingMeBack: FollowUser[];
	iDontFollowBack: FollowUser[];
}

export function extractUsers(html: string): Map<string, string> {
	const users = new Map<string, string>();
	const regex = /<a\s+[^>]*href="([^"]*instagram\.com[^"]*)"/g;
	let match: RegExpExecArray | null;

	while ((match = regex.exec(html)) !== null) {
		const link = match[1];
		const id = link.split('/').filter(Boolean).pop();
		if (id) {
			users.set(id, link);
		}
	}

	return users;
}

export function calculateDiff(followersHtml: string, followingHtml: string): DiffResult {
	const followers = extractUsers(followersHtml);
	const following = extractUsers(followingHtml);

	const notFollowingMeBack: FollowUser[] = [];
	const iDontFollowBack: FollowUser[] = [];

	for (const [id, link] of following.entries()) {
		if (!followers.has(id)) {
			notFollowingMeBack.push({ id, link });
		}
	}

	for (const [id, link] of followers.entries()) {
		if (!following.has(id)) {
			iDontFollowBack.push({ id, link });
		}
	}

	return { notFollowingMeBack, iDontFollowBack };
}
